from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.product import Product, ProductType

router = APIRouter(prefix="/products", tags=["products"])


class ProductIn(BaseModel):
    sku: str
    name: str
    type: ProductType
    unit: str
    is_active: bool = True
    notes: str | None = None


class ProductPatch(BaseModel):
    name: str | None = None
    type: ProductType | None = None
    unit: str | None = None
    is_active: bool | None = None
    notes: str | None = None


class ProductOut(ProductIn):
    id: int


@router.get("", response_model=list[ProductOut])
async def list_products(db: AsyncSession = Depends(get_db)) -> list[ProductOut]:
    items = (await db.execute(select(Product).order_by(Product.id))).scalars().all()
    return [ProductOut.model_validate(i, from_attributes=True) for i in items]


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
