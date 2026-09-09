"""Резолв пары сырьевых артикулов для планирования (#148, ADR-0023).

Единственный владелец поиска пары для плана: импорт, валидация, генерация
и planning rows не читают ``product_pairs`` напрямую — дубликаты поиска
(«парная техкарта» в plan_validation / plan_import_service) упразднены
вместе с техкартным gate.

Поиск — точное неупорядоченное совпадение двух SKU-компонентов:
уникальность неупорядоченной пары (#141) даёт однозначный ответ даже при
нескольких парах на артикул. Не найдена → вызывающий ставит
``product_pair_not_found``.

N пары — единая механика с одиночными нормами (#127/#142): ручная из
словаря пары по длине позиции, авто — совместный расчёт движка
(``min(by_area, by_size)``). Длина позиции — всегда сырьевая (ADR-0024:
план несёт длину ГП, импорт материализует её в сырьевую до резолва).
Расчёт невозможен (нет длины, длина вне пересечения длин A и B,
ручной нет и авто не считается) — ``calc_error=True``, вызывающий ставит
``hanger_calc_zero``. Пара с пустым пересечением длин существует
в справочнике (#146: видна в списке с ``lengths: []``), но валидной N
не даёт.

Снапшот-принцип (#142): позиция с записанным снапшотом
(``source_payload["techcard_pair"]`` с ``resolved=True``) — норматив
позиции; пару и нормы она не ревалидирует.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.services.import_normalization import normalize_sku as _normalize_sku


@dataclass(frozen=True)
class ResolvedPair:
    """Найденная пара: строка ``product_pairs`` и оба её артикула."""

    pair: ProductPair
    product_a: Product
    product_b: Product


@dataclass(frozen=True)
class PairHangerValue:
    """Разрешённое N пары для длины позиции (аналог ``PositionHangerValue``)."""

    quantity_per_hanger: int | None
    source: Literal["manual", "auto", None]
    calc_error: bool = False


def paired_component_skus(position) -> list[str]:
    """SKU-компоненты парной позиции из ``source_payload["components"]``."""
    payload = position.source_payload or {}
    components = payload.get("components") or []
    if not isinstance(components, list):
        return []
    return [
        str(item.get("sku") or "").strip()
        for item in components
        if str(item.get("sku") or "").strip()
    ]


def has_pair_snapshot(position) -> bool:
    """Непустой снапшот пары в payload (``techcard_pair.resolved=True``)."""
    snapshot = (position.source_payload or {}).get("techcard_pair")
    return isinstance(snapshot, dict) and snapshot.get("resolved") is True


async def resolve_pair_by_component_skus(
    db: AsyncSession, component_skus: list[str]
) -> ResolvedPair | None:
    """Найти пару по двум SKU-компонентам (точное неупорядоченное совпадение)."""
    normalized = {_normalize_sku(sku) for sku in component_skus if _normalize_sku(sku)}
    if len(normalized) != 2:
        return None

    pairs = (await db.execute(select(ProductPair))).scalars().all()
    if not pairs:
        return None

    product_ids = {pid for pair in pairs for pid in (pair.product_a_id, pair.product_b_id)}
    products = (
        await db.execute(select(Product).where(Product.id.in_(product_ids)))
    ).scalars().all()
    skus_by_id = {p.id: p.sku for p in products}

    for pair in pairs:
        sku_a = skus_by_id.get(pair.product_a_id)
        sku_b = skus_by_id.get(pair.product_b_id)
        if sku_a is None or sku_b is None:
            continue
        if {_normalize_sku(sku_a), _normalize_sku(sku_b)} == normalized:
            products_by_id = {p.id: p for p in products}
            return ResolvedPair(
                pair=pair,
                product_a=products_by_id[pair.product_a_id],
                product_b=products_by_id[pair.product_b_id],
            )
    return None


async def resolve_effective_product_id(
    db: AsyncSession, position
) -> int | None:
    """Эффективный продукт позиции плана (#148).

    Одиночная позиция — ``position.product_id``. Парная: позиция со
    снапшотом берёт продукт из снапшота (``inputs[0]`` — product_a, порядок
    записи резолвером), пару справочник не переинтерпретирует (#142);
    без снапшота — резолв пары из ``product_pairs`` → ``product_a_id``.
    Возвращает None, если продукт не резолвится.
    """
    if position.product_id is not None:
        return position.product_id

    if has_pair_snapshot(position):
        inputs = (position.source_payload or {}).get("techcard_pair", {}).get("inputs") or []
        first = inputs[0] if inputs else None
        product_id = first.get("product_id") if isinstance(first, dict) else None
        return int(product_id) if product_id else None

    resolved = await resolve_pair_by_component_skus(db, paired_component_skus(position))
    return resolved.pair.product_a_id if resolved is not None else None


async def pair_length_candidates_mm(db: AsyncSession, resolved: ResolvedPair) -> list[float]:
    """Отсортированные длины-кандидаты пары — пересечение длин A и B (#141).

    Каноническое множество для правила ADR-0024 «ближайшая сверху»: пара
    нормируется одной общей длиной, обе компоненты встают на подвес одной
    длиной. Пустое пересечение → [] (пара существует по #146, но валидной
    длины не даёт — вызывающий ставит ``raw_length_not_found``).
    """
    rows = (
        await db.execute(
            select(ProductLength.product_id, ProductLength.length_mm).where(
                ProductLength.product_id.in_((resolved.product_a.id, resolved.product_b.id))
            )
        )
    ).all()
    lengths_by_id: dict[int, set[float]] = {}
    for pid, length in rows:
        lengths_by_id.setdefault(pid, set()).add(float(length))
    intersection = lengths_by_id.get(resolved.product_a.id, set()) & lengths_by_id.get(
        resolved.product_b.id, set()
    )
    return sorted(intersection)


async def _pair_length_keys(db: AsyncSession, resolved: ResolvedPair) -> set[str]:
    """Канонические ключи длин пары — пересечение длин A и B (#141)."""
    return {_length_key(length) for length in await pair_length_candidates_mm(db, resolved)}


async def resolve_pair_n(
    db: AsyncSession, resolved: ResolvedPair, *, length_mm: float | None
) -> PairHangerValue:
    """Разрешить N пары для длины позиции.

    Приоритет: ручное значение из словаря пары для этой длины → совместный
    авто-расчёт (оба артикула в режиме auto) → иначе расчёт невозможен
    (``calc_error=True``). Длина позиции вне пересечения длин A и B (в том
    числе пустое пересечение, #146) — пара для этой длины не существует.
    """
    if length_mm is None or _length_key(length_mm) not in await _pair_length_keys(db, resolved):
        return PairHangerValue(None, None, calc_error=True)

    stored = resolved.pair.quantity_per_hanger if isinstance(resolved.pair.quantity_per_hanger, dict) else {}
    entry = stored.get(_length_key(length_mm))
    manual = entry.get("manual") if isinstance(entry, dict) else None
    if manual is not None and int(manual) > 0:
        return PairHangerValue(int(manual), "manual")

    a, b = resolved.product_a, resolved.product_b
    if a.hanger_mode == HANGER_MODE_AUTO and b.hanger_mode == HANGER_MODE_AUTO:
        try:
            calc = compute_paired_hanger_quantity(
                perimeter_a_mm=a.perimeter_mm,
                mount_width_a_mm=a.mount_width_mm,
                perimeter_b_mm=b.perimeter_mm,
                mount_width_b_mm=b.mount_width_mm,
                length_mm=length_mm,
            )
        except HangerConfigError:
            return PairHangerValue(None, None, calc_error=True)
        if calc.is_calculable and calc.total is not None:
            if calc.total > 0:
                return PairHangerValue(calc.total, "auto")
            return PairHangerValue(None, None, calc_error=True)

    return PairHangerValue(None, None, calc_error=True)
