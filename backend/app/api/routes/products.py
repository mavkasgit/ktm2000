import base64
from pathlib import Path

from typing import List
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status, Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select, type_coerce, delete
from sqlalchemy.types import ARRAY, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.models.product import Product, ProductType, ProductLength, ProcessingFlag, ProductProcessingFlag
from app.models.techcard import Techcard, TechcardLine
from app.models.production_plan import PlanPosition
from app.models.work_task import WorkTask
from app.models.internal_plan import SectionPlanLine
from app.models.route import ProductionRoute, RouteRuleProfile, RouteStage, RouteOperation, SectionOperation
from app.models.section import Section
from app.services.route_selection import select_route_for_payload
from app.models.transfer import Transfer
from app.models.movement import Movement, MovementType
from app.models.defect import Defect
from app.models.rework_task import ReworkTask
from app.models.spg_remainder import SpgRemainder

router = APIRouter(prefix="/products", tags=["products"])


class ProcessingFlagOut(BaseModel):
    code: str
    name: str
    section_scope: str | None


class ProcessingFlagInfo(BaseModel):
    code: str
    name: str
    section_scope: str | None


class ProductIn(BaseModel):
    sku: str
    name: str
    type: ProductType
    unit: str = "pcs"
    is_active: bool = True
    notes: str | None = None
    profile_type: str | None = None
    alloy: str | None = None
    color: str | None = None
    anod_type: str | None = None
    length_mm: float | None = None
    weight_per_meter: float | None = None
    quantity_per_hanger: int | None = None
    cross_section: str | None = None
    photo_thumb: str | None = None
    photo_full: str | None = None
    source: str | None = None
    is_catalog_item: bool = False
    is_paired_profile: bool = False
    skip_shot_blast: bool = False
    aliases: List[str] = []
    lengths_mm: List[float] = []
    processing_flag_codes: List[str] = []
    is_laminated: bool = False


class ProductPatch(BaseModel):
    name: str | None = None
    type: ProductType | None = None
    unit: str | None = None
    is_active: bool | None = None
    notes: str | None = None
    profile_type: str | None = None
    alloy: str | None = None
    color: str | None = None
    anod_type: str | None = None
    length_mm: float | None = None
    weight_per_meter: float | None = None
    quantity_per_hanger: int | None = None
    cross_section: str | None = None
    photo_thumb: str | None = None
    photo_full: str | None = None
    source: str | None = None
    is_catalog_item: bool | None = None
    is_paired_profile: bool | None = None
    skip_shot_blast: bool | None = None
    aliases: List[str] | None = None
    lengths_mm: List[float] | None = None
    processing_flag_codes: List[str] | None = None
    is_laminated: bool | None = None


class ProductOut(BaseModel):
    id: int
    sku: str
    name: str
    type: ProductType
    unit: str
    is_active: bool
    notes: str | None
    profile_type: str | None
    alloy: str | None
    color: str | None
    anod_type: str | None
    length_mm: float | None
    weight_per_meter: float | None
    quantity_per_hanger: int | None
    cross_section: str | None
    photo_thumb: str | None
    photo_full: str | None
    source: str | None
    is_catalog_item: bool
    is_paired_profile: bool
    skip_shot_blast: bool
    aliases: List[str]
    lengths_mm: List[float]
    processing_flags: List[ProcessingFlagInfo]
    is_laminated: bool
    has_standard_techcard: bool = False
    has_paired_techcard: bool = False


VALID_SORT_FIELDS = {"sku", "name", "length_mm", "quantity_per_hanger", "id"}


async def _sync_lengths(db: AsyncSession, product_id: int, lengths: list[float]) -> None:
    """Replace all lengths for a product with the given list."""
    await db.execute(delete(ProductLength).where(ProductLength.product_id == product_id))
    for length in lengths:
        if length <= 0:
            raise HTTPException(status_code=400, detail=f"length_mm must be > 0, got {length}")
        db.add(ProductLength(product_id=product_id, length_mm=length))


async def _sync_processing_flags(db: AsyncSession, product_id: int, codes: list[str]) -> None:
    """Replace all processing flags for a product with the given codes."""
    await db.execute(delete(ProductProcessingFlag).where(ProductProcessingFlag.product_id == product_id))
    if not codes:
        return
    known = await db.scalars(select(ProcessingFlag.code).where(ProcessingFlag.code.in_(codes), ProcessingFlag.is_active == True))
    known_set = set(known.all())
    unknown = set(codes) - known_set
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown processing flag codes: {', '.join(sorted(unknown))}")
    flag_ids = await db.scalars(select(ProcessingFlag.id).where(ProcessingFlag.code.in_(codes)))
    for fid in flag_ids.all():
        db.add(ProductProcessingFlag(product_id=product_id, flag_id=fid))


def _to_product_out(product: Product, has_std: bool = False, has_paired: bool = False) -> ProductOut:
    lengths = sorted([l.length_mm for l in product.lengths]) if product.lengths else []
    flags = [
        ProcessingFlagInfo(code=f.code, name=f.name, section_scope=f.section_scope)
        for f in product.processing_flags
    ]
    return ProductOut(
        id=product.id,
        sku=product.sku,
        name=product.name,
        type=product.type,
        unit=product.unit,
        is_active=product.is_active,
        notes=product.notes,
        profile_type=product.profile_type,
        alloy=product.alloy,
        color=product.color,
        anod_type=product.anod_type,
        length_mm=product.length_mm,
        weight_per_meter=product.weight_per_meter,
        quantity_per_hanger=product.quantity_per_hanger,
        cross_section=product.cross_section,
        photo_thumb=product.photo_thumb,
        photo_full=product.photo_full,
        source=product.source,
        is_catalog_item=product.is_catalog_item,
        is_paired_profile=product.is_paired_profile,
        skip_shot_blast=product.skip_shot_blast,
        aliases=product.aliases or [],
        lengths_mm=lengths,
        processing_flags=flags,
        is_laminated=product.is_laminated,
        has_standard_techcard=has_std,
        has_paired_techcard=has_paired,
    )


async def _enforce_bidirectional_aliases(
    db: AsyncSession, product_id: int, new_aliases: list[str], old_aliases: list[str] | None = None
) -> list[str]:
    """Ensure aliases are bidirectional: if A has alias B, then B has alias A. Returns list of activated aliases."""
    current_product = await db.get(Product, product_id)
    if not current_product:
        return []

    old_set = set(old_aliases or [])
    new_alias_set = set(new_aliases)

    added = new_alias_set - old_set
    removed = old_set - new_alias_set
    activated = []

    for alias_sku in added:
        alias_product = await db.scalar(select(Product).where(Product.sku == alias_sku))
        if alias_product:
            alias_list = list(set(alias_product.aliases or []) | {current_product.sku})
            alias_product.aliases = alias_list
            activated.append(alias_sku)

    for alias_sku in removed:
        alias_product = await db.scalar(select(Product).where(Product.sku == alias_sku))
        if alias_product:
            alias_list = [a for a in (alias_product.aliases or []) if a != current_product.sku]
            alias_product.aliases = alias_list

    return activated


def _parse_sort(sort_param: str):
    """Parse sort parameter like 'sku:asc,length_mm:desc' into list of (column_attr, is_desc)."""
    rules = []
    for part in sort_param.split(","):
        part = part.strip()
        if ":" in part:
            field, order = part.rsplit(":", 1)
        else:
            field = part
            order = "asc"
        field = field.strip()
        order = order.strip().lower()
        if field not in VALID_SORT_FIELDS:
            raise HTTPException(status_code=400, detail=f"Invalid sort field: {field}")
        if order not in ("asc", "desc"):
            raise HTTPException(status_code=400, detail=f"Invalid sort order: {order}")
        col = getattr(Product, field)
        rules.append(col.desc() if order == "desc" else col)
    return rules


@router.get("", response_model=list[ProductOut])
async def list_products(
    db: AsyncSession = Depends(get_db),
    q: str | None = Query(None, description="Search by sku or name"),
    type: ProductType | None = Query(None),
    profile_type: str | None = Query(None),
    alloy: str | None = Query(None),
    color: str | None = Query(None),
    is_active: bool | None = Query(None),
    is_catalog_item: bool | None = Query(None),
    is_paired_profile: bool | None = Query(None),
    sort: str = Query("sku:asc", description="Comma-separated sort rules: field:asc|desc, e.g. sku:asc,length_mm:desc"),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> list[ProductOut]:
    stmt = select(Product).options(
        selectinload(Product.lengths),
        selectinload(Product.processing_flags),
    )

    if q:
        search = f"%{q}%"
        prefix = f"{q}%"
        # Search in sku, name, and aliases array by casting to text
        stmt = stmt.where(or_(
            Product.sku.ilike(search),
            Product.name.ilike(search),
            func.cast(Product.aliases, String).ilike(search),
        ))
        stmt = stmt.order_by((Product.sku.ilike(prefix)).desc())
    if type:
        stmt = stmt.where(Product.type == type)
    if profile_type:
        stmt = stmt.where(Product.profile_type == profile_type)
    if alloy:
        stmt = stmt.where(Product.alloy == alloy)
    if color:
        stmt = stmt.where(Product.color == color)
    if is_active is not None:
        stmt = stmt.where(Product.is_active == is_active)
    if is_catalog_item is not None:
        stmt = stmt.where(Product.is_catalog_item == is_catalog_item)
    if is_paired_profile is not None:
        stmt = stmt.where(Product.is_paired_profile == is_paired_profile)

    for order_clause in _parse_sort(sort):
        stmt = stmt.order_by(order_clause)
    stmt = stmt.limit(limit).offset(offset)
    items = (await db.execute(stmt)).scalars().unique().all()

    # Query active standard techcard product IDs (direct reference)
    std_direct_stmt = select(Techcard.product_id).where(
        Techcard.is_active == True,
        Techcard.processing_type == "standart_processing",
        Techcard.product_id.is_not(None)
    )
    std_direct_ids = set((await db.execute(std_direct_stmt)).scalars().all())

    # Query active standard techcard component IDs (from lines)
    std_line_stmt = select(TechcardLine.component_product_id).join(
        Techcard, Techcard.id == TechcardLine.techcard_id
    ).where(
        Techcard.is_active == True,
        Techcard.processing_type == "standart_processing"
    )
    std_line_ids = set((await db.execute(std_line_stmt)).scalars().all())

    has_std_ids = std_direct_ids | std_line_ids

    # Query active paired techcard component IDs (from lines)
    paired_line_stmt = select(TechcardLine.component_product_id).join(
        Techcard, Techcard.id == TechcardLine.techcard_id
    ).where(
        Techcard.is_active == True,
        Techcard.processing_type == "paired_processing"
    )
    has_paired_ids = set((await db.execute(paired_line_stmt)).scalars().all())

    return [_to_product_out(i, i.id in has_std_ids, i.id in has_paired_ids) for i in items]


@router.get("/search/suggestions", response_model=list[str])
async def product_search_suggestions(
    db: AsyncSession = Depends(get_db),
    q: str = Query(..., min_length=1),
    field: str = Query("sku", pattern="^(sku|name|profile_type|alloy|color)$"),
    limit: int = Query(20, ge=1, le=100),
) -> list[str]:
    """Return distinct values for autocomplete."""
    column = getattr(Product, field)
    stmt = (
        select(column)
        .where(column.ilike(f"%{q}%"))
        .distinct()
        .order_by(column)
        .limit(limit)
    )
    results = (await db.execute(stmt)).scalars().all()
    return [r for r in results if r is not None]


class AliasSuggestion(BaseModel):
    id: int
    sku: str
    name: str
    is_paired_profile: bool


@router.get("/search/products", response_model=list[AliasSuggestion])
async def search_products(
    db: AsyncSession = Depends(get_db),
    q: str = Query(..., min_length=0, description="Search query"),
    exclude_sku: str | None = Query(None, description="Exclude this SKU (current product)"),
    exclude_aliases: str | None = Query(None, description="Comma-separated alias SKUs to exclude"),
    paired_only: bool = Query(False, description="Only return paired profiles"),
    limit: int = Query(20, ge=1, le=100),
) -> list[AliasSuggestion]:
    """Search products by SKU/name with prefix prioritization."""
    stmt = select(Product.id, Product.sku, Product.name, Product.is_paired_profile)

    if paired_only:
        stmt = stmt.where(Product.is_paired_profile == True)

    if q:
        search = f"%{q}%"
        prefix = f"{q}%"
        # Two-tier search: prefix matches first, then contains
        stmt = stmt.where(
            or_(
                Product.sku.ilike(search),
                Product.name.ilike(search),
            )
        ).order_by(
            (Product.sku.ilike(prefix)).desc(),
            Product.sku,
        )
    else:
        stmt = stmt.order_by(Product.sku)

    if exclude_sku:
        stmt = stmt.where(Product.sku != exclude_sku)

    if exclude_aliases:
        excluded = [s.strip() for s in exclude_aliases.split(",") if s.strip()]
        if excluded:
            stmt = stmt.where(~Product.sku.in_(excluded))

    stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).all()
    return [AliasSuggestion(id=r.id, sku=r.sku, name=r.name, is_paired_profile=r.is_paired_profile) for r in rows]


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> ProductOut:
    existing = await db.scalar(select(Product).where(Product.sku == payload.sku))
    if existing:
        raise HTTPException(status_code=409, detail="SKU already exists")

    product_data = payload.model_dump(exclude={"lengths_mm", "processing_flag_codes"})
    item = Product(**product_data)
    db.add(item)
    await db.flush()

    if payload.lengths_mm:
        await _sync_lengths(db, item.id, payload.lengths_mm)
    if payload.processing_flag_codes:
        await _sync_processing_flags(db, item.id, payload.processing_flag_codes)

    if payload.aliases:
        activated = await _enforce_bidirectional_aliases(db, item.id, payload.aliases, old_aliases=[])
        if activated:
            encoded = base64.b64encode(",".join(activated).encode()).decode()
            response.headers["X-Activated-Aliases"] = encoded

    await db.flush()
    await db.refresh(item, attribute_names=["lengths", "processing_flags"])
    return _to_product_out(item)


@router.get("/processing-flags", response_model=list[ProcessingFlagOut])
async def list_processing_flags(db: AsyncSession = Depends(get_db)) -> list[ProcessingFlagOut]:
    stmt = select(ProcessingFlag).where(ProcessingFlag.is_active == True).order_by(ProcessingFlag.code)
    items = (await db.execute(stmt)).scalars().all()
    return [ProcessingFlagOut(code=f.code, name=f.name, section_scope=f.section_scope) for f in items]


async def _check_product_techcards(db: AsyncSession, product_id: int) -> tuple[bool, bool]:
    has_std = await db.scalar(
        select(Techcard.id).where(
            Techcard.is_active == True,
            Techcard.processing_type == "standart_processing",
            or_(
                Techcard.product_id == product_id,
                Techcard.id.in_(
                    select(TechcardLine.techcard_id).where(TechcardLine.component_product_id == product_id)
                )
            )
        ).limit(1)
    ) is not None

    has_paired = await db.scalar(
        select(TechcardLine.id).join(Techcard, Techcard.id == TechcardLine.techcard_id).where(
            Techcard.is_active == True,
            Techcard.processing_type == "paired_processing",
            TechcardLine.component_product_id == product_id
        ).limit(1)
    ) is not None

    return has_std, has_paired


@router.get("/{product_id}", response_model=ProductOut)
async def get_product(product_id: int, db: AsyncSession = Depends(get_db)) -> ProductOut:
    stmt = select(Product).options(
        selectinload(Product.lengths),
        selectinload(Product.processing_flags),
    ).where(Product.id == product_id)
    item = (await db.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Product not found")
    has_std, has_paired = await _check_product_techcards(db, product_id)
    return _to_product_out(item, has_std, has_paired)


@router.patch("/{product_id}", response_model=ProductOut)
async def patch_product(
    product_id: int,
    payload: ProductPatch,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> ProductOut:
    item = await db.get(Product, product_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Product not found")

    old_aliases = item.aliases if payload.aliases is not None else None

    patch_data = payload.model_dump(exclude_unset=True, exclude={"lengths_mm", "processing_flag_codes"})
    for key, value in patch_data.items():
        setattr(item, key, value)

    if payload.lengths_mm is not None:
        await _sync_lengths(db, product_id, payload.lengths_mm)
    if payload.processing_flag_codes is not None:
        await _sync_processing_flags(db, product_id, payload.processing_flag_codes)

    await db.flush()

    if payload.aliases is not None and old_aliases is not None:
        activated = await _enforce_bidirectional_aliases(db, product_id, payload.aliases, old_aliases=list(old_aliases))
        if activated:
            encoded = base64.b64encode(",".join(activated).encode()).decode()
            response.headers["X-Activated-Aliases"] = encoded
        await db.flush()

    await db.refresh(item, attribute_names=["lengths", "processing_flags"])
    has_std, has_paired = await _check_product_techcards(db, product_id)
    return _to_product_out(item, has_std, has_paired)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(Product, product_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Product not found")

    relations: list[str] = []

    pp_count = await db.scalar(select(func.count()).select_from(PlanPosition).where(PlanPosition.product_id == product_id))
    if pp_count:
        relations.append("позиции плана")

    wt_count = await db.scalar(select(func.count()).select_from(WorkTask).where(WorkTask.product_id == product_id))
    if wt_count:
        relations.append("рабочие задачи")

    spl_count = await db.scalar(select(func.count()).select_from(SectionPlanLine).where(SectionPlanLine.product_id == product_id))
    if spl_count:
        relations.append("линии плана участков")

    transfer_count = await db.scalar(select(func.count()).select_from(Transfer).where(Transfer.product_id == product_id))
    if transfer_count:
        relations.append("передачи")

    movement_count = await db.scalar(select(func.count()).select_from(Movement).where(Movement.product_id == product_id))
    if movement_count:
        relations.append("движения по складу")

    defect_count = await db.scalar(select(func.count()).select_from(Defect).where(Defect.product_id == product_id))
    if defect_count:
        relations.append("дефекты")

    rework_count = await db.scalar(select(func.count()).select_from(ReworkTask).where(ReworkTask.product_id == product_id))
    if rework_count:
        relations.append("задачи доработки")

    if relations:
        raise HTTPException(status_code=409, detail=f"Нельзя удалить: используется в ({', '.join(relations)})")

    # Cascade delete techcards referencing this product
    tc_ids_to_delete = set()
    
    # 1. Standard techcards for this product
    std_tcs = (await db.execute(select(Techcard.id).where(Techcard.product_id == product_id))).scalars().all()
    for tc_id in std_tcs:
        tc_ids_to_delete.add(tc_id)
        
    # 2. Techcards where this product is a component
    comp_tcs = (await db.execute(select(TechcardLine.techcard_id).where(TechcardLine.component_product_id == product_id))).scalars().all()
    for tc_id in comp_tcs:
        tc_ids_to_delete.add(tc_id)

    if tc_ids_to_delete:
        # Delete all lines for these techcards
        await db.execute(delete(TechcardLine).where(TechcardLine.techcard_id.in_(list(tc_ids_to_delete))))
        # Delete the techcards themselves
        await db.execute(delete(Techcard).where(Techcard.id.in_(list(tc_ids_to_delete))))

    # Delete spg remainders for this product
    await db.execute(delete(SpgRemainder).where(SpgRemainder.product_id == product_id))

    # Remove this product from other products' aliases
    all_products = (await db.execute(select(Product))).scalars().all()
    for p in all_products:
        if p.id != product_id and item.sku in (p.aliases or []):
            p.aliases = [a for a in p.aliases if a != item.sku]

    await db.delete(item)
    await db.flush()


@router.post("/{product_id}/photo", response_model=ProductOut)
async def upload_product_photo(
    product_id: int,
    file: UploadFile = File(...),
    kind: str = Query("full", pattern="^(full|thumb)$"),
    db: AsyncSession = Depends(get_db),
) -> ProductOut:
    print(f"[DEBUG] upload_product_photo: product_id={product_id}, kind={kind}, filename={file.filename}")
    item = await db.get(Product, product_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Product not found")

    storage_dir = Path(settings.PRODUCT_PHOTO_DIR)
    storage_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename or "image.jpg").suffix.lstrip(".") or "jpg"
    content = await file.read()

    if kind == "full":
        filename = f"{item.sku}_{product_id}_full.{ext}"
        full_path = storage_dir / filename
        full_path.write_bytes(content)
        item.photo_full = str(full_path.relative_to(storage_dir.parent))
    else:
        thumbname = f"{item.sku}_{product_id}_thumb.{ext}"
        thumb_path = storage_dir / thumbname
        thumb_path.write_bytes(content)
        item.photo_thumb = str(thumb_path.relative_to(storage_dir.parent))

    await db.flush()
    await db.refresh(item, attribute_names=["lengths", "processing_flags"])
    return _to_product_out(item)


class RouteOperationOut(BaseModel):
    id: int | None = None
    operation_code: str | None = None
    operation_name: str


class RouteStageOut(BaseModel):
    id: int
    sequence: int
    section_id: int
    section_code: str
    section_name: str
    is_significant: bool
    requires_acceptance: bool
    is_final: bool
    operations: list[RouteOperationOut]


@router.get("/{product_id}/route-stages", response_model=list[RouteStageOut])
async def get_product_route_stages(
    product_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[RouteStageOut]:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    # 1. Try to find route matching the product across all profiles
    profiles = (
        await db.execute(
            select(RouteRuleProfile)
            .where(RouteRuleProfile.is_active == True)
            .order_by(RouteRuleProfile.priority.desc(), RouteRuleProfile.id.asc())
        )
    ).scalars().all()

    matched_route = None
    for profile in profiles:
        selection = await select_route_for_payload(db, {}, product, profile_id=profile.id)
        if selection.route is not None:
            matched_route = selection.route
            break

    # 2. Fallback: try global selection without profile_id
    if not matched_route:
        selection = await select_route_for_payload(db, {}, product)
        if selection.route is not None:
            matched_route = selection.route

    # 3. Double Fallback: if still no route, try to find a route whose name/code matches product profile_type or type
    if not matched_route:
        if product.profile_type:
            matched_route = await db.scalar(
                select(ProductionRoute)
                .where(ProductionRoute.is_active == True)
                .where(ProductionRoute.name.ilike(f"%{product.profile_type}%"))
                .limit(1)
            )
        if not matched_route and product.type:
            matched_route = await db.scalar(
                select(ProductionRoute)
                .where(ProductionRoute.is_active == True)
                .where(ProductionRoute.name.ilike(f"%{product.type}%"))
                .limit(1)
            )
        if not matched_route:
            matched_route = await db.scalar(
                select(ProductionRoute)
                .where(ProductionRoute.is_active == True)
                .order_by(ProductionRoute.sort_order, ProductionRoute.id)
                .limit(1)
            )

    if not matched_route:
        raise HTTPException(status_code=404, detail="No route found for this product")

    # Load stages
    stages = (
        await db.execute(
            select(RouteStage)
            .where(RouteStage.route_id == matched_route.id)
            .order_by(RouteStage.sequence)
            .options(selectinload(RouteStage.operations))
        )
    ).scalars().all()

    section_ids = {stage.section_id for stage in stages}
    sections_dict = {}
    if section_ids:
        sec_rows = (await db.execute(select(Section).where(Section.id.in_(section_ids)))).scalars().all()
        sections_dict = {s.id: s for s in sec_rows}

    # Load section operations
    section_ops_dict = {}
    if section_ids:
        ops_rows = (
            await db.execute(
                select(SectionOperation)
                .where(SectionOperation.section_id.in_(section_ids))
                .where(SectionOperation.group_code.isnot(None))
                .order_by(SectionOperation.section_id, SectionOperation.sort_order, SectionOperation.operation_code)
            )
        ).scalars().all()
        for op in ops_rows:
            section_ops_dict.setdefault(op.section_id, []).append(op)

    out_stages = []
    for stage in stages:
        section = sections_dict.get(stage.section_id)
        if not section:
            continue

        # Determine operations
        has_specific_ops = any(op.operation_code is not None for op in stage.operations)
        ops_list = []
        if has_specific_ops:
            for op in stage.operations:
                if op.operation_code is not None:
                    # Ищем операцию в справочнике секции для определения group_code
                    sec_ops = section_ops_dict.get(stage.section_id) or []
                    ref_op = next((so for so in sec_ops if so.operation_code == op.operation_code), None)
                    
                    if ref_op and ref_op.group_code:
                        # Если операция входит в группу, добавляем все операции этой группы для данной секции
                        group_ops = [so for so in sec_ops if so.group_code == ref_op.group_code]
                        for go in group_ops:
                            if not any(added.operation_code == go.operation_code for added in ops_list):
                                ops_list.append(RouteOperationOut(
                                    id=go.id,
                                    operation_code=go.operation_code,
                                    operation_name=go.operation_name,
                                ))
                    else:
                        # Если группы нет, добавляем только саму операцию
                        if not any(added.operation_code == op.operation_code for added in ops_list):
                            ops_list.append(RouteOperationOut(
                                id=op.id,
                                operation_code=op.operation_code,
                                operation_name=op.operation_name,
                            ))
        else:
            # Fall back to section operations
            section_ops = section_ops_dict.get(stage.section_id) or []
            for op in section_ops:
                ops_list.append(RouteOperationOut(
                    id=op.id,
                    operation_code=op.operation_code,
                    operation_name=op.operation_name,
                ))

        out_stages.append(RouteStageOut(
            id=stage.id,
            sequence=stage.sequence,
            section_id=stage.section_id,
            section_code=section.code,
            section_name=section.name,
            is_significant=stage.is_significant,
            requires_acceptance=stage.requires_acceptance,
            is_final=stage.is_final,
            operations=ops_list,
        ))

    return out_stages


class LastCompletedOperationOut(BaseModel):
    section_id: int | None = None
    section_code: str | None = None
    section_name: str | None = None
    operation_code: str | None = None
    operation_name: str | None = None
    sequence: int | None = None


@router.get("/{product_id}/last-completed-operation", response_model=LastCompletedOperationOut)
async def get_product_last_completed_operation(
    product_id: int,
    db: AsyncSession = Depends(get_db),
) -> LastCompletedOperationOut:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    # 1. Находим последнее движение 'complete'
    movement = await db.scalar(
        select(Movement)
        .where(
            Movement.product_id == product_id,
            Movement.movement_type == MovementType.complete,
        )
        .order_by(Movement.performed_at.desc(), Movement.id.desc())
        .limit(1)
    )

    if not movement or not movement.task_id:
        return LastCompletedOperationOut()

    # 2. Находим задачу
    task = await db.get(WorkTask, movement.task_id)
    if not task:
        return LastCompletedOperationOut()

    # 3. Находим участок и этап маршрута
    section = await db.get(Section, task.section_id)
    stage = await db.get(RouteStage, task.route_stage_id)

    op_name = None
    if task.selected_operation_code:
        op_name = await db.scalar(
            select(SectionOperation.operation_name)
            .where(
                SectionOperation.section_id == task.section_id,
                SectionOperation.operation_code == task.selected_operation_code,
            )
            .limit(1)
        )

    return LastCompletedOperationOut(
        section_id=task.section_id,
        section_code=section.code if section else None,
        section_name=section.name if section else None,
        operation_code=task.selected_operation_code,
        operation_name=op_name,
        sequence=stage.sequence if stage else None,
    )


