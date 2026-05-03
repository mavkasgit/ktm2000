from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Literal

from app.core.database import get_db
from app.models.techcard import Techcard, TechcardLine, TechcardPair, TechcardPairLine
from app.models.product import Product

router = APIRouter(prefix="/techcards", tags=["techcards"])


class TechcardCreate(BaseModel):
    product_id: int
    version: str
    processing_type: Literal["standart_processing", "paired_processing"] = "standart_processing"
    is_active: bool = True


class TechcardLineCreate(BaseModel):
    component_product_id: int
    quantity: float
    unit: str


class TechcardOut(TechcardCreate):
    id: int


class TechcardLineOut(TechcardLineCreate):
    id: int
    techcard_id: int


class TechcardDetailOut(TechcardOut):
    product_article: str
    lines: list[TechcardLineOut]
    techcard_pairs: list["TechcardPairOut"]


class TechcardPairCreate(BaseModel):
    name: str
    priority: int = 100
    is_active: bool = True


class TechcardPairPatch(BaseModel):
    name: str | None = None
    priority: int | None = None
    is_active: bool | None = None


class TechcardPairOut(BaseModel):
    id: int
    techcard_id: int
    name: str
    priority: int
    is_active: bool


class TechcardPairLineCreate(BaseModel):
    component_product_id: int
    quantity: float
    unit: str


class TechcardPairLineOut(TechcardPairLineCreate):
    id: int
    techcard_pair_id: int


class TechcardPairDetailOut(TechcardPairOut):
    lines: list[TechcardPairLineOut]


@router.post("", response_model=TechcardOut, status_code=status.HTTP_201_CREATED)
async def create_techcard(payload: TechcardCreate, db: AsyncSession = Depends(get_db)) -> TechcardOut:
    product = await db.get(Product, payload.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    item = Techcard(**payload.model_dump())
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return TechcardOut.model_validate(item, from_attributes=True)


@router.get("", response_model=list[TechcardOut])
async def list_techcards(db: AsyncSession = Depends(get_db)) -> list[TechcardOut]:
    rows = (await db.execute(select(Techcard).order_by(Techcard.id.desc()))).scalars().all()
    return [TechcardOut.model_validate(item, from_attributes=True) for item in rows]


@router.get("/{techcard_id}", response_model=TechcardDetailOut)
async def get_techcard(techcard_id: int, db: AsyncSession = Depends(get_db)) -> TechcardDetailOut:
    item = await db.get(Techcard, techcard_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Техкарта не найдена")
    product = await db.get(Product, item.product_id)
    lines = (
        await db.execute(select(TechcardLine).where(TechcardLine.techcard_id == techcard_id).order_by(TechcardLine.id))
    ).scalars().all()
    variants = (
        await db.execute(select(TechcardPair).where(TechcardPair.techcard_id == techcard_id).order_by(TechcardPair.priority, TechcardPair.id))
    ).scalars().all()
    return TechcardDetailOut(
        id=item.id,
        product_id=item.product_id,
        product_article=product.sku if product else str(item.product_id),
        version=item.version,
        processing_type=item.processing_type,
        is_active=item.is_active,
        lines=[TechcardLineOut.model_validate(line, from_attributes=True) for line in lines],
        techcard_pairs=[TechcardPairOut.model_validate(variant, from_attributes=True) for variant in variants],
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
    if component.id == techcard.product_id and techcard.processing_type != "standart_processing":
        raise HTTPException(status_code=400, detail="Для paired_processing компонент не может совпадать с артикулом техкарты")

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
        if key in {"version", "is_active", "processing_type"}:
            setattr(item, key, value)
    await db.flush()
    await db.refresh(item)
    return TechcardOut.model_validate(item, from_attributes=True)


@router.post("/{techcard_id}/techcard-pairs", response_model=TechcardPairOut, status_code=status.HTTP_201_CREATED)
async def create_techcard_pair(
    techcard_id: int, payload: TechcardPairCreate, db: AsyncSession = Depends(get_db)
) -> TechcardPairOut:
    techcard = await db.get(Techcard, techcard_id)
    if techcard is None:
        raise HTTPException(status_code=404, detail="Техкарта не найдена")
    if techcard.processing_type != "paired_processing":
        raise HTTPException(status_code=400, detail="Варианты пар доступны только для paired_processing")
    if payload.priority < 0:
        raise HTTPException(status_code=400, detail="priority должен быть >= 0")

    item = TechcardPair(
        techcard_id=techcard_id,
        name=payload.name.strip(),
        priority=payload.priority,
        is_active=payload.is_active,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return TechcardPairOut.model_validate(item, from_attributes=True)


@router.patch("/{techcard_id}/techcard-pairs/{pair_id}", response_model=TechcardPairOut)
async def patch_techcard_pair(
    techcard_id: int,
    pair_id: int,
    payload: TechcardPairPatch,
    db: AsyncSession = Depends(get_db),
) -> TechcardPairOut:
    variant = await db.get(TechcardPair, pair_id)
    if variant is None or variant.techcard_id != techcard_id:
        raise HTTPException(status_code=404, detail="Вариант пар не найден")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        data["name"] = data["name"].strip()
    if "priority" in data and data["priority"] < 0:
        raise HTTPException(status_code=400, detail="priority должен быть >= 0")
    for key, value in data.items():
        setattr(variant, key, value)
    await db.flush()
    await db.refresh(variant)
    return TechcardPairOut.model_validate(variant, from_attributes=True)


@router.get("/{techcard_id}/techcard-pairs/{pair_id}", response_model=TechcardPairDetailOut)
async def get_techcard_pair(
    techcard_id: int, pair_id: int, db: AsyncSession = Depends(get_db)
) -> TechcardPairDetailOut:
    variant = await db.get(TechcardPair, pair_id)
    if variant is None or variant.techcard_id != techcard_id:
        raise HTTPException(status_code=404, detail="Вариант пар не найден")
    lines = (
        await db.execute(
            select(TechcardPairLine).where(TechcardPairLine.techcard_pair_id == pair_id).order_by(TechcardPairLine.id)
        )
    ).scalars().all()
    return TechcardPairDetailOut(
        **TechcardPairOut.model_validate(variant, from_attributes=True).model_dump(),
        lines=[TechcardPairLineOut.model_validate(line, from_attributes=True) for line in lines],
    )


@router.post(
    "/{techcard_id}/techcard-pairs/{pair_id}/lines",
    response_model=TechcardPairLineOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_techcard_pair_line(
    techcard_id: int,
    pair_id: int,
    payload: TechcardPairLineCreate,
    db: AsyncSession = Depends(get_db),
) -> TechcardPairLineOut:
    variant = await db.get(TechcardPair, pair_id)
    if variant is None or variant.techcard_id != techcard_id:
        raise HTTPException(status_code=404, detail="Вариант пар не найден")
    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be > 0")
    component = await db.get(Product, payload.component_product_id)
    if component is None:
        raise HTTPException(status_code=404, detail="Сырье не найдено")

    line = TechcardPairLine(techcard_pair_id=pair_id, **payload.model_dump())
    db.add(line)
    await db.flush()
    await db.refresh(line)
    return TechcardPairLineOut.model_validate(line, from_attributes=True)
