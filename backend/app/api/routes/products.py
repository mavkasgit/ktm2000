import base64
from pathlib import Path

from typing import List
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status, Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select, type_coerce
from sqlalchemy.types import ARRAY, String
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.product import Product, ProductType

router = APIRouter(prefix="/products", tags=["products"])


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


class ProductOut(ProductIn):
    id: int


VALID_SORT_FIELDS = {"sku", "name", "length_mm", "quantity_per_hanger", "id"}


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
    stmt = select(Product)

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
    items = (await db.execute(stmt)).scalars().all()
    return [ProductOut.model_validate(i, from_attributes=True) for i in items]


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
    stmt = select(Product.id, Product.sku, Product.name)

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
    return [AliasSuggestion(id=r.id, sku=r.sku, name=r.name) for r in rows]


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> ProductOut:
    existing = await db.scalar(select(Product).where(Product.sku == payload.sku))
    if existing:
        raise HTTPException(status_code=409, detail="SKU already exists")
    item = Product(**payload.model_dump())
    db.add(item)
    await db.flush()
    await db.refresh(item)

    if payload.aliases:
        activated = await _enforce_bidirectional_aliases(db, item.id, payload.aliases, old_aliases=[])
        if activated:
            encoded = base64.b64encode(",".join(activated).encode()).decode()
            response.headers["X-Activated-Aliases"] = encoded
        await db.flush()
        await db.refresh(item)

    return ProductOut.model_validate(item, from_attributes=True)


@router.get("/{product_id}", response_model=ProductOut)
async def get_product(product_id: int, db: AsyncSession = Depends(get_db)) -> ProductOut:
    item = await db.get(Product, product_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return ProductOut.model_validate(item, from_attributes=True)


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

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await db.flush()

    if payload.aliases is not None and old_aliases is not None:
        activated = await _enforce_bidirectional_aliases(db, product_id, payload.aliases, old_aliases=list(old_aliases))
        if activated:
            encoded = base64.b64encode(",".join(activated).encode()).decode()
            response.headers["X-Activated-Aliases"] = encoded
        await db.flush()

    await db.refresh(item)
    return ProductOut.model_validate(item, from_attributes=True)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(Product, product_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Product not found")

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
    await db.refresh(item)
    return ProductOut.model_validate(item, from_attributes=True)
