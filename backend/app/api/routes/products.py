from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
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


class ProductOut(ProductIn):
    id: int


@router.get("", response_model=list[ProductOut])
async def list_products(
    db: AsyncSession = Depends(get_db),
    q: str | None = Query(None, description="Search by sku or name"),
    type: ProductType | None = Query(None),
    profile_type: str | None = Query(None),
    alloy: str | None = Query(None),
    color: str | None = Query(None),
    is_active: bool | None = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> list[ProductOut]:
    stmt = select(Product)
    
    if q:
        search = f"%{q}%"
        stmt = stmt.where(or_(Product.sku.ilike(search), Product.name.ilike(search)))
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
    
    stmt = stmt.order_by(Product.sku).limit(limit).offset(offset)
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


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(payload: ProductIn, db: AsyncSession = Depends(get_db)) -> ProductOut:
    existing = await db.scalar(select(Product).where(Product.sku == payload.sku))
    if existing:
        raise HTTPException(status_code=409, detail="SKU already exists")
    item = Product(**payload.model_dump())
    db.add(item)
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
async def patch_product(product_id: int, payload: ProductPatch, db: AsyncSession = Depends(get_db)) -> ProductOut:
    item = await db.get(Product, product_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Product not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await db.flush()
    await db.refresh(item)
    return ProductOut.model_validate(item, from_attributes=True)


@router.post("/{product_id}/photo", response_model=ProductOut)
async def upload_product_photo(
    product_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> ProductOut:
    item = await db.get(Product, product_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Product not found")

    storage_dir = Path(settings.PRODUCT_PHOTO_DIR)
    storage_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename or "image.jpg").suffix.lstrip(".") or "jpg"
    filename = f"{item.sku}_{product_id}_full.{ext}"
    thumbname = f"{item.sku}_{product_id}_thumb.{ext}"

    full_path = storage_dir / filename
    thumb_path = storage_dir / thumbname

    content = await file.read()
    full_path.write_bytes(content)

    # Simple thumbnail generation (placeholder - in real app use PIL)
    thumb_path.write_bytes(content)

    item.photo_full = str(full_path.relative_to(storage_dir.parent))
    item.photo_thumb = str(thumb_path.relative_to(storage_dir.parent))
    await db.flush()
    await db.refresh(item)
    return ProductOut.model_validate(item, from_attributes=True)
