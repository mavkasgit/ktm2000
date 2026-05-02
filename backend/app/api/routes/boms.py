from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.bom import BOM, BOMLine
from app.models.product import Product

router = APIRouter(prefix="/boms", tags=["boms"])


class BOMCreate(BaseModel):
    product_id: int
    version: str
    is_active: bool = True


class BOMLineCreate(BaseModel):
    component_product_id: int
    quantity: float
    unit: str


class BOMOut(BOMCreate):
    id: int


class BOMLineOut(BOMLineCreate):
    id: int
    bom_id: int


@router.post("", response_model=BOMOut, status_code=status.HTTP_201_CREATED)
async def create_bom(payload: BOMCreate, db: AsyncSession = Depends(get_db)) -> BOMOut:
    product = await db.get(Product, payload.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    item = BOM(**payload.model_dump())
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return BOMOut.model_validate(item, from_attributes=True)


@router.post("/{bom_id}/lines", response_model=BOMLineOut, status_code=status.HTTP_201_CREATED)
async def create_bom_line(bom_id: int, payload: BOMLineCreate, db: AsyncSession = Depends(get_db)) -> BOMLineOut:
    bom = await db.get(BOM, bom_id)
    if bom is None:
        raise HTTPException(status_code=404, detail="BOM not found")
    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be > 0")
    component = await db.get(Product, payload.component_product_id)
    if component is None:
        raise HTTPException(status_code=404, detail="Component product not found")
    if component.id == bom.product_id:
        raise HTTPException(status_code=400, detail="BOM cannot reference same product as component")

    line = BOMLine(bom_id=bom_id, **payload.model_dump())
    db.add(line)
    await db.flush()
    await db.refresh(line)
    return BOMLineOut.model_validate(line, from_attributes=True)


@router.patch("/{bom_id}", response_model=BOMOut)
async def patch_bom(bom_id: int, payload: dict, db: AsyncSession = Depends(get_db)) -> BOMOut:
    item = await db.get(BOM, bom_id)
    if item is None:
        raise HTTPException(status_code=404, detail="BOM not found")
    for key, value in payload.items():
        if key in {"version", "is_active"}:
            setattr(item, key, value)
    await db.flush()
    await db.refresh(item)
    return BOMOut.model_validate(item, from_attributes=True)
