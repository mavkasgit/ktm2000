"""Резолв пары сырьевых артикулов для планирования (#148, ADR-0023).

Единственный владелец поиска пары для плана: импорт, валидация, генерация
и planning rows не читают ``product_pairs`` напрямую — дубликаты поиска
(парная ветка в plan_validation / plan_import_service) упразднены.

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
(``source_payload["product_pair"]`` с ``resolved=True``) — норматив
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


def pair_snapshot(payload: dict | None) -> dict | None:
    """Снапшот пары из payload (``product_pair``), если он разрешён."""
    snapshot = (payload or {}).get("product_pair")
    if isinstance(snapshot, dict) and snapshot.get("resolved") is True:
        return snapshot
    return None


def has_pair_snapshot(position) -> bool:
    """Непустой снапшот пары в payload (``product_pair.resolved=True``)."""
    return pair_snapshot(position.source_payload) is not None


def pair_component_key(component_skus: list[str]) -> tuple[str, ...]:
    """Нормализованный ключ компонентов пары (для кэша одного вызова)."""
    return tuple(sorted(s for s in (_normalize_sku(sku) for sku in component_skus) if s))


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


async def resolve_effective_product_ids(
    db: AsyncSession, position
) -> list[int]:
    """Все продукты позиции плана (#148): одиночная — один, парная — оба.

    Одиночная позиция — ``[position.product_id]``. Парная: позиция со
    снапшотом берёт продукты из снапшота (``inputs[]``, порядок записи
    резолвером — product_a, product_b), пару справочник не переинтерпретирует
    (#142); без снапшота — резолв пары из ``product_pairs`` →
    ``[product_a_id, product_b_id]``. Пустой список — продукт не резолвится.
    """
    if position.product_id is not None:
        return [position.product_id]

    if has_pair_snapshot(position):
        inputs = (pair_snapshot(position.source_payload) or {}).get("inputs") or []
        return [
            int(item["product_id"])
            for item in inputs
            if isinstance(item, dict) and item.get("product_id")
        ]

    resolved = await resolve_pair_by_component_skus(db, paired_component_skus(position))
    if resolved is None:
        return []
    return [resolved.pair.product_a_id, resolved.pair.product_b_id]


async def resolve_effective_product_id(
    db: AsyncSession, position
) -> int | None:
    """Первый из :func:`resolve_effective_product_ids` (исторический контракт)."""
    product_ids = await resolve_effective_product_ids(db, position)
    return product_ids[0] if product_ids else None


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
    db: AsyncSession, resolved: ResolvedPair, *, length_mm: float | None,
    length_candidates_mm: list[float] | None = None,
    manual_override: int | None = None,
) -> PairHangerValue:
    """Разрешить N пары для длины позиции.

    Приоритет: ручной override из payload позиции (``manual_override``) →
    ручное значение из словаря пары для этой длины → совместный авто-расчёт
    (оба артикула в режиме auto) → иначе расчёт невозможен
    (``calc_error=True``). Оверрайд побеждает всегда — до проверки длины
    (как payload-override у одиночных позиций, #127). Длина позиции вне
    пересечения длин A и B (в том числе пустое пересечение, #146) — пара для
    этой длины не существует.

    ``length_candidates_mm`` — предзагруженное пересечение длин A∩B
    (межстрочный кэш батча, #163): избавляет от перезапроса мимо
    внешнего ``pair_n_cache``. Без него поведение прежнее (запрос в БД).
    """
    if manual_override is not None and int(manual_override) > 0:
        return PairHangerValue(int(manual_override), "manual")

    if length_candidates_mm is None:
        length_keys = await _pair_length_keys(db, resolved)
    else:
        length_keys = {_length_key(length) for length in length_candidates_mm}
    if length_mm is None or _length_key(length_mm) not in length_keys:
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
