"""Pairs-API (#146, ADR-0023): пары сырьевых артикулов.

Роуты вложены в артикул (``/products/{product_id}/pairs``), редактирование
симметричное — из формы любого из двух артикулов, без «владельца» записи;
отдельного реестра пар нет. Ручная N задаётся только в пределах
пересечения нормальных длин A и B (вне пересечения пара не существует).
``auto`` пары не хранится и не принимается — считается движком живьём только
для двух артикулов в режиме auto с равными эффективными сырьевыми длинами.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.product import (
    HANGER_MODE_AUTO,
    Product,
    ProductLength,
    ProductPair,
    _length_key,
)
from app.services.hanger_quantity_calc import (
    HangerConfigError,
    compute_paired_hanger_quantity,
)

router = APIRouter(prefix="/products", tags=["products"])


class PairHangerValue(BaseModel):
    """Значение «кол-во на подвес» пары для одной длины (вывод): авто и ручное."""

    auto: int | None = None
    manual: int | None = Field(default=None, gt=0, description="Ручное значение N пары (>0)")


class PairHangerManualIn(BaseModel):
    """Ввод ручной N пары по длине: только manual, auto считает сервер."""

    manual: int | None = Field(default=None, gt=0, description="Ручное значение N пары (>0)")


class ProductPairIn(BaseModel):
    partner_product_id: int
    quantity_per_hanger: dict[str, PairHangerManualIn] | None = None


class ProductPairPatch(BaseModel):
    quantity_per_hanger: dict[str, PairHangerManualIn]


class PairPartnerOut(BaseModel):
    id: int
    sku: str
    name: str
    is_paired_profile: bool


class ProductPairOut(BaseModel):
    id: int
    product_a_id: int
    product_b_id: int
    partner: PairPartnerOut
    # Длины пары — пересечение длин A и B, по возрастанию.
    lengths: list[float]
    quantity_per_hanger: dict[str, PairHangerValue]


async def _get_product_or_404(db: AsyncSession, product_id: int) -> Product:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


async def _get_pair_or_404(db: AsyncSession, product_id: int, pair_id: int) -> ProductPair:
    pair = await db.get(ProductPair, pair_id)
    if pair is None or product_id not in (pair.product_a_id, pair.product_b_id):
        raise HTTPException(status_code=404, detail="Pair not found for this product")
    return pair


async def _lengths_by_product(
    db: AsyncSession, product_ids: list[int]
) -> dict[int, dict[float, float]]:
    if not product_ids:
        return {}
    rows = (
        await db.execute(
            select(ProductLength).where(ProductLength.product_id.in_(product_ids))
        )
    ).scalars().all()
    result: dict[int, dict[float, float]] = {}
    for row in rows:
        result.setdefault(row.product_id, {})[float(row.length_mm)] = (
            row.effective_raw_length_mm
        )
    return result


def _intersection_lengths(
    lengths_a: dict[float, float], lengths_b: dict[float, float]
) -> list[float]:
    """Нормальные длины пары — пересечение длин A и B, по возрастанию."""
    return sorted(set(lengths_a) & set(lengths_b))


def _pair_auto_value(
    a: Product,
    b: Product,
    raw_length_a_mm: float,
    raw_length_b_mm: float,
) -> int | None:
    """Авто N пары живьём (#146): движок по сумме периметров/габаритов.

    Режим пары выведенный: авто — только если оба артикула в режиме auto.
    Разные эффективные сырьевые длины несовместимы на одном подвесе.
    """
    if a.hanger_mode != HANGER_MODE_AUTO or b.hanger_mode != HANGER_MODE_AUTO:
        return None
    if raw_length_a_mm != raw_length_b_mm:
        return None
    try:
        calc = compute_paired_hanger_quantity(
            perimeter_a_mm=a.perimeter_mm,
            mount_width_a_mm=a.mount_width_mm,
            perimeter_b_mm=b.perimeter_mm,
            mount_width_b_mm=b.mount_width_mm,
            length_mm=raw_length_a_mm,
        )
    except HangerConfigError:
        return None
    return calc.total if calc.is_calculable else None


def _manual_by_length(
    payload: dict[str, PairHangerManualIn] | None, allowed_lengths: list[float]
) -> dict[str, dict[str, int | None]]:
    """Нормализовать ручную N из payload: ключи — канонические, строго в пересечении."""
    allowed = {_length_key(length) for length in allowed_lengths}
    result: dict[str, dict[str, int | None]] = {}
    for key, value in (payload or {}).items():
        try:
            fkey = _length_key(float(key))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Некорректный ключ длины: {key}") from None
        if fkey not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"Длина {key} вне пересечения длин артикулов пары",
            )
        result[fkey] = {"auto": None, "manual": value.manual}
    return result


def _quantity_out(
    pair: ProductPair,
    a: Product,
    b: Product,
    lengths: list[float],
    raw_lengths_a: dict[float, float],
    raw_lengths_b: dict[float, float],
) -> dict[str, PairHangerValue]:
    """N пары по длине на выходе API (#146/#150): авто движком живьём + ручное из словаря пары."""
    stored = pair.quantity_per_hanger if isinstance(pair.quantity_per_hanger, dict) else {}
    quantity: dict[str, PairHangerValue] = {}
    for length in lengths:
        key = _length_key(length)
        entry = stored.get(key)
        manual = entry.get("manual") if isinstance(entry, dict) else None
        quantity[key] = PairHangerValue(
            auto=_pair_auto_value(a, b, raw_lengths_a[length], raw_lengths_b[length]),
            manual=manual,
        )
    return quantity


def _pair_out(
    pair: ProductPair,
    product: Product,
    partner: Product,
    lengths: list[float],
    raw_lengths_product: dict[float, float],
    raw_lengths_partner: dict[float, float],
) -> ProductPairOut:
    quantity = _quantity_out(
        pair, product, partner, lengths, raw_lengths_product, raw_lengths_partner
    )
    return ProductPairOut(
        id=pair.id,
        product_a_id=pair.product_a_id,
        product_b_id=pair.product_b_id,
        partner=PairPartnerOut(
            id=partner.id,
            sku=partner.sku,
            name=partner.name,
            is_paired_profile=bool(partner.is_paired_profile),
        ),
        lengths=lengths,
        quantity_per_hanger=quantity,
    )


@router.get("/{product_id}/pairs", response_model=list[ProductPairOut])
async def list_product_pairs(
    product_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[ProductPairOut]:
    product = await _get_product_or_404(db, product_id)
    pairs = (
        await db.execute(
            select(ProductPair).where(
                (ProductPair.product_a_id == product_id)
                | (ProductPair.product_b_id == product_id)
            )
        )
    ).scalars().all()
    if not pairs:
        return []

    partner_ids = sorted(
        {pair.product_b_id if pair.product_a_id == product_id else pair.product_a_id for pair in pairs}
    )
    partners = (
        await db.execute(
            select(Product).options(selectinload(Product.lengths)).where(Product.id.in_(partner_ids))
        )
    ).scalars().all()
    partners_by_id = {p.id: p for p in partners}
    raw_lengths_by_id = await _lengths_by_product(
        db, partner_ids + [product.id]
    )

    out: list[ProductPairOut] = []
    for pair in pairs:
        partner = partners_by_id.get(
            pair.product_b_id if pair.product_a_id == product_id else pair.product_a_id
        )
        if partner is None:
            continue
        lengths = _intersection_lengths(
            raw_lengths_by_id.get(pair.product_a_id, {}),
            raw_lengths_by_id.get(pair.product_b_id, {}),
        )
        out.append(
            _pair_out(
                pair,
                product,
                partner,
                lengths,
                raw_lengths_by_id[product.id],
                raw_lengths_by_id[partner.id],
            )
        )
    return out


@router.post("/{product_id}/pairs", response_model=ProductPairOut, status_code=status.HTTP_201_CREATED)
async def create_product_pair(
    product_id: int,
    payload: ProductPairIn,
    db: AsyncSession = Depends(get_db),
) -> ProductPairOut:
    product = await _get_product_or_404(db, product_id)
    partner = await db.get(Product, payload.partner_product_id)
    if partner is None:
        raise HTTPException(status_code=404, detail="Partner product not found")
    if partner.id == product.id:
        raise HTTPException(status_code=422, detail="Нельзя создать пару артикула с самим собой")

    duplicate = await db.scalar(
        select(ProductPair).where(
            ProductPair.product_a_id == min(product.id, partner.id),
            ProductPair.product_b_id == max(product.id, partner.id),
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Пара этих артикулов уже существует")

    product = await _load_with_lengths(db, product.id)
    partner = await _load_with_lengths(db, partner.id)
    # Пересечение может быть пустым: пара создаётся как намерение («нет общих
    # длин» — предупреждение в UI, а не запрет); оживает сама, когда у обоих
    # артикулов появятся общие длины. Ниже по стеку пустое пересечение уже
    # первоклассно: каталог отдаёт lengths: [], резолвер N — calc_error.
    raw_lengths_product = {
        float(length.length_mm): length.effective_raw_length_mm for length in product.lengths
    }
    raw_lengths_partner = {
        float(length.length_mm): length.effective_raw_length_mm for length in partner.lengths
    }
    lengths = _intersection_lengths(raw_lengths_product, raw_lengths_partner)

    pair = ProductPair(
        product_a_id=min(product.id, partner.id),
        product_b_id=max(product.id, partner.id),
        quantity_per_hanger=_manual_by_length(payload.quantity_per_hanger, lengths),
    )
    db.add(pair)
    try:
        await db.flush()
    except IntegrityError:
        # Гонка двух симметричных POST: уникальность неупорядоченной пары — 409.
        await db.rollback()
        raise HTTPException(status_code=409, detail="Пара этих артикулов уже существует") from None
    return _pair_out(
        pair, product, partner, lengths, raw_lengths_product, raw_lengths_partner
    )


async def _load_with_lengths(db: AsyncSession, product_id: int) -> Product:
    # select вместо Session.get: get не применяет eager-load к объекту,
    # уже лежащему в identity map — lengths осталась бы незагруженной.
    product = (
        await db.execute(
            select(Product).options(selectinload(Product.lengths)).where(Product.id == product_id)
        )
    ).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.patch("/{product_id}/pairs/{pair_id}", response_model=ProductPairOut)
async def patch_product_pair(
    product_id: int,
    pair_id: int,
    payload: ProductPairPatch,
    db: AsyncSession = Depends(get_db),
) -> ProductPairOut:
    product = await _get_product_or_404(db, product_id)
    pair = await _get_pair_or_404(db, product_id, pair_id)

    partner_id = pair.product_b_id if pair.product_a_id == product_id else pair.product_a_id
    product = await _load_with_lengths(db, product.id)
    partner = await _load_with_lengths(db, partner_id)
    raw_lengths_product = {
        float(length.length_mm): length.effective_raw_length_mm for length in product.lengths
    }
    raw_lengths_partner = {
        float(length.length_mm): length.effective_raw_length_mm for length in partner.lengths
    }
    lengths = _intersection_lengths(raw_lengths_product, raw_lengths_partner)

    pair.quantity_per_hanger = _manual_by_length(payload.quantity_per_hanger, lengths)
    await db.flush()
    return _pair_out(
        pair, product, partner, lengths, raw_lengths_product, raw_lengths_partner
    )


@router.delete("/{product_id}/pairs/{pair_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product_pair(
    product_id: int,
    pair_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    await _get_product_or_404(db, product_id)
    pair = await _get_pair_or_404(db, product_id, pair_id)
    await db.delete(pair)
    await db.flush()


class ProductPairCatalogOut(BaseModel):
    """Элемент каталога всех пар — источник парных строк расчёта подвесов (#150)."""

    id: int
    product_a_id: int
    product_b_id: int
    # Пустой список — пара вне пересечения длин («не существует на длине»),
    # но запись видна: она держит удаление артикула до разрыва пары.
    lengths: list[float]
    quantity_per_hanger: dict[str, PairHangerValue]


# Отдельный роутер без префикса /products: путь /products/pairs занял бы
# GET /products/{product_id} (product_id: int → 422 до rows пар).
catalog_router = APIRouter(tags=["products"])


@catalog_router.get("/product-pairs", response_model=list[ProductPairCatalogOut])
async def list_all_product_pairs(
    db: AsyncSession = Depends(get_db),
) -> list[ProductPairCatalogOut]:
    """Все пары одним списком (#150): витрина расчёта подвесов показывает
    парные строки «N×A + N×B» рядом с одиночными; резолв пары идёт только
    из ``product_pairs``. Пустое пересечение длин возвращается как есть —
    витрина сама решает, что с такой парой не показывать строку."""
    pairs = (await db.execute(select(ProductPair))).scalars().all()
    if not pairs:
        return []

    product_ids = sorted({p.product_a_id for p in pairs} | {p.product_b_id for p in pairs})
    products = (
        await db.execute(
            select(Product).options(selectinload(Product.lengths)).where(Product.id.in_(product_ids))
        )
    ).scalars().all()
    by_id = {p.id: p for p in products}

    out: list[ProductPairCatalogOut] = []
    for pair in pairs:
        a = by_id.get(pair.product_a_id)
        b = by_id.get(pair.product_b_id)
        if a is None or b is None:
            continue
        raw_lengths_a = {
            float(length.length_mm): length.effective_raw_length_mm for length in a.lengths
        }
        raw_lengths_b = {
            float(length.length_mm): length.effective_raw_length_mm for length in b.lengths
        }
        lengths = _intersection_lengths(raw_lengths_a, raw_lengths_b)
        out.append(
            ProductPairCatalogOut(
                id=pair.id,
                product_a_id=pair.product_a_id,
                product_b_id=pair.product_b_id,
                lengths=lengths,
                quantity_per_hanger=_quantity_out(
                    pair, a, b, lengths, raw_lengths_a, raw_lengths_b
                ),
            )
        )
    return out
