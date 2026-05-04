from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Literal

from app.core.database import get_db
from app.models.techcard import Techcard, TechcardLine
from app.models.product import Product

router = APIRouter(prefix="/techcards", tags=["techcards"])


class TechcardCreate(BaseModel):
    product_id: int | None = None
    version: str
    processing_type: Literal["standart_processing", "paired_processing"] = "standart_processing"
    is_active: bool = True
    quantity_total: int | None = None
    quantity_a_per_item: int | None = None
    quantity_b_per_item: int | None = None
    hangers_a: int | None = None
    hangers_b: int | None = None
    hangers_total: int | None = None


class TechcardLineCreate(BaseModel):
    component_product_id: int
    quantity: float
    unit: str


class TechcardOut(BaseModel):
    id: int
    product_id: int | None = None
    version: str
    processing_type: str
    is_active: bool
    quantity_total: int | None = None
    quantity_a_per_item: int | None = None
    quantity_b_per_item: int | None = None
    hangers_a: int | None = None
    hangers_b: int | None = None
    hangers_total: int | None = None


class TechcardLineOut(TechcardLineCreate):
    id: int
    techcard_id: int


class TechcardDetailOut(TechcardOut):
    product_article: str
    lines: list[TechcardLineOut]


async def _ensure_default_line(db: AsyncSession, techcard: Techcard) -> None:
    if techcard.product_id is None:
        return

    existing = await db.scalar(select(TechcardLine.id).where(TechcardLine.techcard_id == techcard.id).limit(1))
    if existing is not None:
        return

    product = await db.get(Product, techcard.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    db.add(
        TechcardLine(
            techcard_id=techcard.id,
            component_product_id=product.id,
            quantity=1,
            unit=product.unit or "pcs",
        )
    )


@router.post("", response_model=TechcardOut, status_code=status.HTTP_201_CREATED)
async def create_techcard(payload: TechcardCreate, db: AsyncSession = Depends(get_db)) -> TechcardOut:
    if payload.product_id is not None:
        product = await db.get(Product, payload.product_id)
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")
    if payload.processing_type == "standart_processing" and payload.product_id is None:
        raise HTTPException(status_code=400, detail="Для standart_processing нужен product_id")
    item = Techcard(**payload.model_dump())
    db.add(item)
    await db.flush()
    await _ensure_default_line(db, item)
    await db.flush()
    await db.refresh(item)
    return TechcardOut.model_validate(item, from_attributes=True)


@router.get("", response_model=list[TechcardOut])
async def list_techcards(db: AsyncSession = Depends(get_db)) -> list[TechcardOut]:
    stmt = select(Techcard).order_by(Techcard.id.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [TechcardOut.model_validate(item, from_attributes=True) for item in rows]


@router.get("/{techcard_id}", response_model=TechcardDetailOut)
async def get_techcard(techcard_id: int, db: AsyncSession = Depends(get_db)) -> TechcardDetailOut:
    item = await db.get(Techcard, techcard_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Техкарта не найдена")
    product = await db.get(Product, item.product_id) if item.product_id else None
    lines = (
        await db.execute(select(TechcardLine).where(TechcardLine.techcard_id == techcard_id).order_by(TechcardLine.id))
    ).scalars().all()

    return TechcardDetailOut(
        id=item.id,
        product_id=item.product_id,
        product_article=product.sku if product else "—",
        version=item.version,
        processing_type=item.processing_type,
        is_active=item.is_active,
        quantity_total=item.quantity_total,
        quantity_a_per_item=item.quantity_a_per_item,
        quantity_b_per_item=item.quantity_b_per_item,
        hangers_a=item.hangers_a,
        hangers_b=item.hangers_b,
        hangers_total=item.hangers_total,
        lines=[TechcardLineOut.model_validate(line, from_attributes=True) for line in lines],
    )


@router.post("/{techcard_id}/lines", response_model=TechcardLineOut, status_code=status.HTTP_201_CREATED)
async def create_techcard_line(techcard_id: int, payload: TechcardLineCreate, db: AsyncSession = Depends(get_db)) -> TechcardLineOut:
    techcard = await db.get(Techcard, techcard_id)
    if techcard is None:
        raise HTTPException(status_code=404, detail="Техкарта не найдена")
    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be > 0")
    component = await db.get(Product, payload.component_product_id)
    if component is None:
        raise HTTPException(status_code=404, detail="Component product not found")

    line = TechcardLine(techcard_id=techcard_id, **payload.model_dump())
    db.add(line)
    await db.flush()
    await db.refresh(line)
    return TechcardLineOut.model_validate(line, from_attributes=True)


@router.patch("/{techcard_id}", response_model=TechcardOut)
async def patch_techcard(techcard_id: int, payload: dict, db: AsyncSession = Depends(get_db)) -> TechcardOut:
    item = await db.get(Techcard, techcard_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Техкарта не найдена")
    for key, value in payload.items():
        if key in {"version", "is_active", "processing_type", "quantity_total", "quantity_a_per_item", "quantity_b_per_item", "hangers_a", "hangers_b", "hangers_total"}:
            setattr(item, key, value)
    if item.processing_type == "standart_processing" and item.product_id is None:
        raise HTTPException(status_code=400, detail="Для standart_processing нужен product_id")
    await _ensure_default_line(db, item)
    await db.flush()
    await db.refresh(item)
    return TechcardOut.model_validate(item, from_attributes=True)


@router.delete("/{techcard_id}", response_model=None, status_code=status.HTTP_204_NO_CONTENT)
async def delete_techcard(techcard_id: int, db: AsyncSession = Depends(get_db)) -> None:
    from sqlalchemy import func

    item = await db.get(Techcard, techcard_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Техкарта не найдена")

    lines_count = await db.scalar(select(func.count()).select_from(TechcardLine).where(TechcardLine.techcard_id == techcard_id))
    if lines_count:
        raise HTTPException(status_code=409, detail=f"Нельзя удалить техкарту: имеются {lines_count} строка(ек) сырья")

    await db.delete(item)
    await db.flush()
    return None
