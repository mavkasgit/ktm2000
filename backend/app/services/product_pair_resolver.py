"""Резолв пары сырьевых артикулов для планирования (#148, ADR-0023).

Единственный владелец поиска пары для плана: импорт, валидация, генерация
и planning rows не читают ``product_pairs`` напрямую — дубликаты поиска
(парная ветка в plan_validation / plan_import_service) упразднены.

Поиск — точное неупорядоченное совпадение двух SKU-компонентов:
уникальность неупорядоченной пары (#141) даёт однозначный ответ даже при
нескольких парах на артикул. Не найдена → вызывающий ставит
``product_pair_not_found``.

N пары — единая механика с одиночными нормами (#127/#142): ручная из
словаря пары по нормальной длине позиции, авто — совместный расчёт движка
(``min(by_area, by_size)``). Пара имеет кандидатов только на пересечении
нормальных длин A и B. Если эффективные сырьевые длины компонентов равны,
это значение используется в auto-формуле; несовпадение запрещает auto только
для этой длины и не затрагивает ручное значение.
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

from collections.abc import Iterable
from dataclasses import dataclass, field
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
class PairComponent:
    """Компонент парного артикула: SKU из строки и продукт справочника (если найден)."""

    sku: str
    product: Product | None

@dataclass(frozen=True)
class PairLengthCandidate:
    """Общая нормальная длина пары и effective raw каждого компонента."""

    length_mm: float
    raw_length_a_mm: float
    raw_length_b_mm: float


@dataclass(frozen=True)
class PairHangerValue:
    """Разрешённое N пары для длины позиции (аналог ``PositionHangerValue``)."""

    quantity_per_hanger: int | None
    source: Literal["manual", "auto"] | None
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


def effective_product_ids_key(position) -> tuple:
    """Ключ кэша «все продукты позиции» — нормализованная идентичность.

    Не сырой payload: три исхода различаются по природе (свой
    ``product_id``, снапшот пары, компоненты SKU), и только последний
    приводит к запросу. Ключ отражает именно вход резолва, поэтому два
    вызова одной позиции и две позиции с одинаковым входом делят один
    результат, а разные входы не делят.
    """
    from app.services.position_route_batch import freeze_identity_value

    if position.product_id is not None:
        return ("single", int(position.product_id))
    snapshot = pair_snapshot(position.source_payload)
    if snapshot is not None:
        return ("snapshot", freeze_identity_value(snapshot))
    return ("pair", pair_component_key(paired_component_skus(position)))


@dataclass(slots=True)
class PairResolutionCache:
    """Кэш резолва пар на один HTTP-запрос (#292).

    Закрывает второй раздатчик N+1: ``_resolve_effective_product_ids`` идёт
    по списку позиций, и на каждой парной позиции без снапшота тянул
    ``SELECT *`` по ``product_pairs`` и ``products``. Здесь справочник
    читается один раз, а позиции, которые не резолвятся в пару вовсе,
    больше не стоят запроса: отрицательный ответ тоже кэшируется.

    Живёт на время одного запроса и переиспользуется вызывающей стороной:
    создаёт его обработчик, передаёт в ``resolve_effective_product_ids``
    параметром ``cache``. Привязан к сессии батча — как и прочие снимки
    этого репозитория.
    """

    _index: dict[frozenset[str], ResolvedPair] | None = None
    _resolved: dict[frozenset[str], ResolvedPair | None] = field(default_factory=dict)
    effective_product_ids: dict[tuple, list[int]] = field(default_factory=dict)

    async def resolve_pair(
        self, db: AsyncSession, normalized: frozenset[str]
    ) -> ResolvedPair | None:
        """Пара по нормализованным SKU компонентов — из кэша или справочника."""
        if normalized in self._resolved:
            return self._resolved[normalized]
        if self._index is None:
            self._index = await _load_pair_index(db)
        resolved = self._index.get(normalized)
        self._resolved[normalized] = resolved
        return resolved


async def _load_pair_index(db: AsyncSession) -> dict[frozenset[str], ResolvedPair]:
    """Справочник пар целиком: нормализованные SKU компонентов → ResolvedPair.

    Два запроса вместо двух на каждую позицию. Порядок обхода строк —
    тот же, что в поштучном поиске, поэтому при нескольких парах с
    одинаковыми SKU побеждает та же, что и раньше.
    """
    pairs = (await db.execute(select(ProductPair))).scalars().all()
    if not pairs:
        return {}
    product_ids = {pid for pair in pairs for pid in (pair.product_a_id, pair.product_b_id)}
    products = (
        await db.execute(select(Product).where(Product.id.in_(product_ids)))
    ).scalars().all()
    skus_by_id = {p.id: p.sku for p in products}
    products_by_id = {p.id: p for p in products}
    index: dict[frozenset[str], ResolvedPair] = {}
    for pair in pairs:
        sku_a = skus_by_id.get(pair.product_a_id)
        sku_b = skus_by_id.get(pair.product_b_id)
        if sku_a is None or sku_b is None:
            continue
        key = frozenset({_normalize_sku(sku_a), _normalize_sku(sku_b)})
        if key in index:
            continue
        index[key] = ResolvedPair(
            pair=pair,
            product_a=products_by_id[pair.product_a_id],
            product_b=products_by_id[pair.product_b_id],
        )
    return index


async def resolve_pair_by_component_skus(
    db: AsyncSession,
    component_skus: list[str],
    *,
    cache: PairResolutionCache | None = None,
) -> ResolvedPair | None:
    """Найти пару по двум SKU-компонентам (точное неупорядоченное совпадение).

    С ``cache`` справочник пар читается один раз на запрос, а позиции без
    пары (в том числе повторные) не стоят ни одного SQL. Без кэша путь
    прежний, поштучный.
    """
    normalized = {_normalize_sku(sku) for sku in component_skus if _normalize_sku(sku)}
    if len(normalized) != 2:
        return None
    if cache is not None:
        return await cache.resolve_pair(db, frozenset(normalized))

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
    db: AsyncSession,
    position,
    *,
    cache: PairResolutionCache | None = None,
) -> list[int]:
    """Все продукты позиции плана (#148): одиночная — один, парная — оба.

    Одиночная позиция — ``[position.product_id]``. Парная: позиция со
    снапшотом берёт продукты из снапшота (``inputs[]``, порядок записи
    резолвером — product_a, product_b), пару справочник не переинтерпретирует
    (#142); без снапшота — резолв пары из ``product_pairs`` →
    ``[product_a_id, product_b_id]``. Пустой список — продукт не резолвится.

    С ``cache`` (один на HTTP-запрос, #292) результат кэшируется по
    нормализованной идентичности позиции: повторная позиция — и позиция
    без пары — не дают SQL. Возвращается копия: кэш общий, а список у
    вызывающего должен остаться его собственным.
    """
    if cache is None:
        return await _resolve_effective_product_ids(db, position)
    key = effective_product_ids_key(position)
    cached = cache.effective_product_ids.get(key)
    if cached is not None:
        return list(cached)
    resolved_ids = await _resolve_effective_product_ids(db, position, cache=cache)
    cache.effective_product_ids[key] = list(resolved_ids)
    return resolved_ids


async def _resolve_effective_product_ids(
    db: AsyncSession,
    position,
    *,
    cache: PairResolutionCache | None = None,
) -> list[int]:
    """Разрешение без кэша — тело, общее для обоих путей."""
    if position.product_id is not None:
        return [position.product_id]

    if has_pair_snapshot(position):
        inputs = (pair_snapshot(position.source_payload) or {}).get("inputs") or []
        return [
            int(item["product_id"])
            for item in inputs
            if isinstance(item, dict) and item.get("product_id")
        ]

    resolved = await resolve_pair_by_component_skus(
        db, paired_component_skus(position), cache=cache
    )
    if resolved is None:
        return []
    return [resolved.pair.product_a_id, resolved.pair.product_b_id]


async def resolve_pair_components_for_sku(
    db: AsyncSession, sku: str
) -> tuple[list[PairComponent], str | None]:
    """Раскрыть составной SKU пары ``A+B`` на компоненты.

    Сначала канонический резолв ``product_pairs`` (неупорядоченное совпадение
    SKU-компонентов, порядок — product_a, product_b), иначе SKU-фолбэк по
    справочнику: компоненты в порядке запроса, ``product=None`` — артикула нет.
    Возвращает ``(компоненты, код деградации)``: ``None`` — пара найдена,
    ``product_pair_not_found`` — строки пары в справочнике нет.
    """
    component_skus = [part.strip() for part in sku.split("+") if part.strip()]
    resolved = await resolve_pair_by_component_skus(db, component_skus)
    if resolved is not None:
        return (
            [
                PairComponent(sku=resolved.product_a.sku, product=resolved.product_a),
                PairComponent(sku=resolved.product_b.sku, product=resolved.product_b),
            ],
            None,
        )

    products = (
        (await db.execute(select(Product).where(Product.sku.in_(component_skus)))).scalars().all()
        if component_skus
        else []
    )
    by_sku = {product.sku: product for product in products}
    return (
        [PairComponent(sku=component_sku, product=by_sku.get(component_sku)) for component_sku in component_skus],
        "product_pair_not_found",
    )


async def pair_length_candidates(
    db: AsyncSession, resolved: ResolvedPair
) -> list[PairLengthCandidate]:
    """Кандидаты пары по пересечению нормальных длин A и B (ADR-0028).

    Идентичность кандидата и ключ ручного N определяет ``length_mm``.
    Сырьевые длины нужны только для auto: неравенство A/B блокирует
    автоматический расчёт этой длины, но не ручной режим.
    """
    rows = (
        await db.execute(
            select(
                ProductLength.product_id,
                ProductLength.length_mm,
                ProductLength.raw_length_mm,
            ).where(
                ProductLength.product_id.in_((resolved.product_a.id, resolved.product_b.id))
            )
        )
    ).all()
    raw_by_product: dict[int, dict[float, float]] = {}
    for pid, normal, raw in rows:
        normal_mm = float(normal)
        effective_raw_mm = float(normal if raw is None else raw)
        raw_by_product.setdefault(pid, {})[normal_mm] = effective_raw_mm
    raw_a = raw_by_product.get(resolved.product_a.id, {})
    raw_b = raw_by_product.get(resolved.product_b.id, {})
    return [
        PairLengthCandidate(
            length_mm=normal_mm,
            raw_length_a_mm=raw_a[normal_mm],
            raw_length_b_mm=raw_b[normal_mm],
        )
        for normal_mm in sorted(raw_a.keys() & raw_b.keys())
    ]


def _length_candidates_from_rows(
    resolved: ResolvedPair,
    raw_by_product: dict[int, dict[float, float]],
) -> list[PairLengthCandidate]:
    """Чистая часть ``pair_length_candidates`` — без обращения к БД."""
    raw_a = raw_by_product.get(resolved.product_a.id, {})
    raw_b = raw_by_product.get(resolved.product_b.id, {})
    return [
        PairLengthCandidate(
            length_mm=normal_mm,
            raw_length_a_mm=raw_a[normal_mm],
            raw_length_b_mm=raw_b[normal_mm],
        )
        for normal_mm in sorted(raw_a.keys() & raw_b.keys())
    ]


async def pair_length_candidates_bulk(
    db: AsyncSession, resolved_pairs: Iterable[ResolvedPair]
) -> dict[int, list[PairLengthCandidate]]:
    """Длины-кандидаты сразу по всем парам батча — один запрос (#293).

    Поштучный ``pair_length_candidates`` стоил одного SELECT на пару, а пар на
    доске столько же, сколько парных позиций. Здесь ``product_lengths``
    читается один раз на батч, а разбор по парам — та же чистая функция, что и
    в одиночном пути, поэтому значения совпадают.
    """
    unique: dict[int, ResolvedPair] = {}
    for resolved in resolved_pairs:
        unique[resolved.pair.id] = resolved
    if not unique:
        return {}

    product_ids: set[int] = set()
    for resolved in unique.values():
        product_ids.add(resolved.product_a.id)
        product_ids.add(resolved.product_b.id)

    rows = (
        await db.execute(
            select(
                ProductLength.product_id,
                ProductLength.length_mm,
                ProductLength.raw_length_mm,
            ).where(ProductLength.product_id.in_(product_ids))
        )
    ).all()
    raw_by_product: dict[int, dict[float, float]] = {}
    for pid, normal, raw in rows:
        normal_mm = float(normal)
        effective_raw_mm = float(normal if raw is None else raw)
        raw_by_product.setdefault(pid, {})[normal_mm] = effective_raw_mm

    return {
        pair_id: _length_candidates_from_rows(resolved, raw_by_product)
        for pair_id, resolved in unique.items()
    }



async def resolve_pair_n(
    db: AsyncSession,
    resolved: ResolvedPair,
    *,
    length_mm: float | None,
    length_candidates: list[PairLengthCandidate] | None = None,
    manual_override: int | None = None,
) -> PairHangerValue:
    """Разрешить N пары для нормальной длины позиции.

    Приоритет: положительный ручной override → положительное ручное значение
    пары по нормальной длине → совместный auto-расчёт. Auto использует общую
    эффективную сырьевую длину только при равенстве сырьевых длин A/B;
    несовпадение блокирует auto лишь для текущей длины.

    ``length_candidates`` — предзагруженное пересечение для межстрочного
    кэша батча.
    """
    if manual_override is not None and int(manual_override) > 0:
        return PairHangerValue(int(manual_override), "manual")

    if length_candidates is None:
        length_candidates = await pair_length_candidates(db, resolved)
    candidates_by_key = {
        _length_key(candidate.length_mm): candidate for candidate in length_candidates
    }
    if length_mm is None or _length_key(length_mm) not in candidates_by_key:
        return PairHangerValue(None, None, calc_error=True)

    stored = resolved.pair.quantity_per_hanger if isinstance(resolved.pair.quantity_per_hanger, dict) else {}
    entry = stored.get(_length_key(length_mm))
    manual = entry.get("manual") if isinstance(entry, dict) else None
    if manual is not None and int(manual) > 0:
        return PairHangerValue(int(manual), "manual")

    a, b = resolved.product_a, resolved.product_b
    if a.hanger_mode == HANGER_MODE_AUTO and b.hanger_mode == HANGER_MODE_AUTO:
        candidate = candidates_by_key[_length_key(length_mm)]
        if candidate.raw_length_a_mm != candidate.raw_length_b_mm:
            return PairHangerValue(None, None, calc_error=True)
        try:
            calc = compute_paired_hanger_quantity(
                perimeter_a_mm=a.perimeter_mm,
                mount_width_a_mm=a.mount_width_mm,
                perimeter_b_mm=b.perimeter_mm,
                mount_width_b_mm=b.mount_width_mm,
                length_mm=candidate.raw_length_a_mm,
            )
        except HangerConfigError:
            return PairHangerValue(None, None, calc_error=True)
        if calc.is_calculable and calc.total is not None:
            if calc.total > 0:
                return PairHangerValue(calc.total, "auto")
            return PairHangerValue(None, None, calc_error=True)

    return PairHangerValue(None, None, calc_error=True)
