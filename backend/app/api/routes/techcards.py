from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Literal

from app.core.database import get_db
from app.models.techcard import Techcard, TechcardLine
from app.models.product import Product
from app.services.techcards_queries import enrich_techcard_list_items, list_techcards_paginated

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


class TechcardLineOut(BaseModel):
    id: int
    techcard_id: int
    component_product_id: int | None = None
    quantity: int | None = None
    unit: str | None = None


class TechcardWithLinesOut(TechcardOut):
    techcard_lines: list[dict] = []
    product_sku: str | None = None


class TechcardsListOut(BaseModel):
    items: list[TechcardWithLinesOut]
    total: int
    limit: int
    offset: int


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


def _normalize_paired_quantities(
    *,
    processing_type: str,
    quantity_a_per_item: int | None,
    quantity_b_per_item: int | None,
) -> tuple[int | None, int | None]:
    """Привести кол-ва парной техкарты к инварианту равенства N (#67).

    Загрузка пары — единая ``N×A + N×B``, поэтому кол-во на подвес у обоих
    компонентов обязано совпадать. Одиночное значение копируется в оба поля
    (как делает миграция 038); одновременно заданные разные значения —
    нарушение инварианта → 422. «Разное кол-во» убрано.
    """
    if processing_type != "paired_processing":
        return quantity_a_per_item, quantity_b_per_item
    if (
        quantity_a_per_item is not None
        and quantity_b_per_item is not None
        and quantity_a_per_item != quantity_b_per_item
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Равенство N — инвариант парной техкарты: "
                f"quantity_a_per_item ({quantity_a_per_item}) != "
                f"quantity_b_per_item ({quantity_b_per_item})"
            ),
        )
    if quantity_a_per_item is None and quantity_b_per_item is not None:
        return quantity_b_per_item, quantity_b_per_item
    if quantity_b_per_item is None and quantity_a_per_item is not None:
        return quantity_a_per_item, quantity_a_per_item
    return quantity_a_per_item, quantity_b_per_item


@router.post("", response_model=TechcardOut, status_code=status.HTTP_201_CREATED)
async def create_techcard(payload: TechcardCreate, db: AsyncSession = Depends(get_db)) -> TechcardOut:
    if payload.product_id is not None:
        product = await db.get(Product, payload.product_id)
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")
    if payload.processing_type == "standart_processing" and payload.product_id is None:
        raise HTTPException(status_code=400, detail="Для standart_processing нужен product_id")
    data = payload.model_dump()
    (
        data["quantity_a_per_item"],
        data["quantity_b_per_item"],
    ) = _normalize_paired_quantities(
        processing_type=payload.processing_type,
        quantity_a_per_item=payload.quantity_a_per_item,
        quantity_b_per_item=payload.quantity_b_per_item,
    )
    item = Techcard(**data)
    db.add(item)
    await db.flush()
    await _ensure_default_line(db, item)
    await db.flush()
    await db.refresh(item)
    return TechcardOut.model_validate(item, from_attributes=True)


@router.get("", response_model=TechcardsListOut)
async def list_techcards(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    sort_by: str = Query(default="id"),
    sort_order: str = Query(default="desc"),
    processing_type: Literal["standart_processing", "paired_processing"] | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    sku: str | None = Query(default=None),
    quantity_total: int | None = Query(default=None),
) -> TechcardsListOut:
    rows, total = await list_techcards_paginated(
        db,
        limit=limit,
        offset=offset,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        processing_type=processing_type,
        is_active=is_active,
        sku=sku,
        quantity_total=quantity_total,
    )
    enriched = await enrich_techcard_list_items(db, rows)
    return TechcardsListOut(
        items=[TechcardWithLinesOut.model_validate(item) for item in enriched],
        total=total,
        limit=limit,
        offset=offset,
    )


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
    (
        item.quantity_a_per_item,
        item.quantity_b_per_item,
    ) = _normalize_paired_quantities(
        processing_type=item.processing_type,
        quantity_a_per_item=item.quantity_a_per_item,
        quantity_b_per_item=item.quantity_b_per_item,
    )
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
