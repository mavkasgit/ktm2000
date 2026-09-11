"""Интеграция авторасчёта «количество на подвес» с планированием (#66, #127).

Две точки вызова: отображение (``PlanPositionOut``) и валидация
(``validate_plan_position``). Расчёт на лету, кэша в позиции нет — позиция
хранит только ручное payload-значение, авто пересчитывается при каждом
сериализуемом чтении.

Контракт вывода (#66):

    quantity_per_hanger: int | null
    quantity_per_hanger_source: "auto" | "manual" | null

Приоритет (#127): ручной override из payload > режим артикула
(``hanger_mode``), а не наличие данных. source соответствует режиму:
manual → ручное значение per-length dict, auto → расчёт из периметра/
габарита. Позиция с конкретной длиной берёт значение для своей длины
(``input_dimensions["length_mm"]``); без длины / без значения — null.
``total <= 0`` (или несовместимые габариты) — расчёт невозможен:
``calc_error``, вызывающий выставляет ``hanger_calc_zero``.

Парная позиция (``product_id`` is None, payload ``paired_profile``):
приоритет ручной override из payload → снапшот ``product_pair`` →
резолв пары (``product_pair_resolver``); позиция без ``product_id`` и без
``paired_profile`` фолбэчится на payload-значение.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dimensions import LENGTH_MM
from app.models.product import HANGER_MODE_MANUAL, Product
from app.services import product_pair_resolver
from app.services.hanger_quantity_calc import (
    HangerConfigError,
    compute_hanger_quantity,
)

QuantityPerHangerSource = Literal["auto", "manual", None]


def _position_input_length_mm(position) -> float | None:
    """Длина входа позиции из ``input_dimensions`` (канонический JSONB, ADR-0001)."""
    dims = position.input_dimensions or {}
    if isinstance(dims, dict):
        length = dims.get(LENGTH_MM)
        if isinstance(length, (int, float)) and length > 0:
            return float(length)
    return None


def _position_single_output_length_mm(position) -> float | None:
    """Длина единственного выхода позиции (``outputs[0].dimensions``)."""
    outputs = position.outputs or []
    if len(outputs) == 1:
        out = outputs[0]
        out_dims = out.get("dimensions") if isinstance(out, dict) else None
        if isinstance(out_dims, dict):
            length = out_dims.get(LENGTH_MM)
            if isinstance(length, (int, float)) and length > 0:
                return float(length)
    return None


def position_length_mm(position) -> float | None:
    """Конкретная длина позиции из габаритов (канонический JSONB, ADR-0001).

    Источник — ``input_dimensions["length_mm"]``; при отсутствии — длина
    единственного выхода (``outputs[0].dimensions["length_mm"]``). ``None`` —
    позиция без конкретной длины (безразмерные штуки или операция с
    несколькими разными выходами).
    """
    length = _position_input_length_mm(position)
    if length is not None:
        return length
    return _position_single_output_length_mm(position)


def position_dimensions_for_task(position) -> dict | None:
    """Габарит задания (``WorkTask.dimensions``) из позиции плана (ADR-0001).

    ``{"length_mm": N}`` в канонической форме при конкретной длине;
    ``None`` — позиция без длины (безразмерные штуки). Источник — длина входа
    позиции (``input_dimensions``); для нетрансформирующей позиции без входа —
    длина единственного выхода (это и есть поток). Трансформирующая позиция
    (объявляет ``input_quantity``, ADR-0002) — только длина входа: подставлять
    выход вместо входа нельзя.
    """
    from app.domain.dimensions import canonicalize_dimensions

    length = _position_input_length_mm(position)
    if length is None and position.input_quantity is None:
        length = _position_single_output_length_mm(position)
    if length is None:
        return None
    return canonicalize_dimensions({"length_mm": length})


async def task_dimensions_for_plan_line(db, plan_position_id: int | None) -> dict | None:
    """Габарит задания по ``plan_position_id`` — для сайтов создания ``WorkTask``.

    Обёртка над :func:`position_dimensions_for_task`: места создания заданий
    имеют только ``SectionPlanLine.plan_position_id``, а не объект позиции.
    """
    from app.models.production_plan import PlanPosition

    if plan_position_id is None:
        return None
    position = await db.get(PlanPosition, plan_position_id)
    if position is None:
        return None
    return position_dimensions_for_task(position)


def payload_quantity_per_hanger(position) -> int | None:
    """Ручное override-значение позиции из source_payload (скаляр).

    Позиция хранит только ручное значение — авто никогда не пишется в
    payload (кэша в позиции нет; импортная N из ``after_data`` сюда не
    копируется). Терпимо к legacy-строкам из старых импортов.
    """
    raw = (position.source_payload or {}).get("quantity_per_hanger")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        return int(raw)
    return None


@dataclass(frozen=True)
class PositionHangerValue:
    """Разрешённое значение «количество на подвес» для позиции плана."""

    quantity_per_hanger: int | None
    source: QuantityPerHangerSource
    calc_error: bool = False


def _manual_value_for_length(product: Product, length_mm: float) -> int | None:
    """Ручное значение нормы для длины: канонический #127-доступ модели.

    Bare-норма (legacy-скаляр) длина-независима, per-length-словарь строг по
    ключу длины; ключа нет → None (fallback на основную норму не делаем).
    """
    return product.quantity_per_hanger_for_length(length_mm)


def resolve_position_hanger(
    product: Product | None,
    *,
    length_mm: float | None,
    payload_quantity_per_hanger: int | None,
) -> PositionHangerValue:
    """Разрешить (quantity_per_hanger, source) для позиции плана.

    Приоритет (#127): ручной override из payload > режим артикула
    (``hanger_mode``). source соответствует режиму, а не наличию данных.

    - Ручной override (payload-скаляр > 0) → source="manual", всегда побеждает;
      неположительный (0/отрицательный) override'ом не считается — падаем
      на режим артикула (то же правило у пары: ``resolve_pair_n``);
    - режим manual + конкретная длина → ручное значение этой длины,
      source="manual" (авто-расчёт не запускается даже при заполненных
      периметре/габарите);
    - режим auto + конкретная длина + заполнены периметр И габарит →
      авто-расчёт этой длины, source="auto"; ``total <= 0`` или несовместимые
      габариты (``mount_width + gap > rod_length``) → ``calc_error=True``
      (значение null, вызывающий ставит ``hanger_calc_zero``);
    - иначе (нет длины / нет значения выбранного режима) → null.
    """
    if payload_quantity_per_hanger is not None and payload_quantity_per_hanger > 0:
        return PositionHangerValue(payload_quantity_per_hanger, "manual")

    if product is None:
        return PositionHangerValue(None, None)

    if product.hanger_mode == HANGER_MODE_MANUAL:
        if length_mm is None:
            return PositionHangerValue(None, None)
        manual = _manual_value_for_length(product, length_mm)
        if manual is not None and manual > 0:
            return PositionHangerValue(manual, "manual")
        return PositionHangerValue(None, None)

    if (
        product.perimeter_mm
        and product.mount_width_mm
        and length_mm is not None
    ):
        try:
            result = compute_hanger_quantity(
                perimeter_mm=product.perimeter_mm,
                mount_width_mm=product.mount_width_mm,
                length_mm=length_mm,
            )
        except HangerConfigError:
            return PositionHangerValue(None, None, calc_error=True)
        if result.is_calculable and result.total is not None:
            if result.total > 0:
                return PositionHangerValue(result.total, "auto")
            return PositionHangerValue(None, None, calc_error=True)

    return PositionHangerValue(None, None)


async def resolve_positions_hanger(
    db: AsyncSession,
    positions,
) -> dict[int, PositionHangerValue]:
    """Batch-резолв значений для списка позиций.

    Одиночные позиции: один запрос продуктов на весь вызов. Парные
    (payload ``paired_profile``): приоритет override из payload → снапшот
    ``product_pair`` → резолв пары владельцем-модулем
    (``product_pair_resolver``); пара по компонентам и её длины-кандидаты
    резолвятся не более одного раза на вызов (кэш по нормализованному
    кортежу компонентов / по id пары). Возвращает ровно по одной записи
    на позицию.
    """
    product_ids = {p.product_id for p in positions if p.product_id is not None}
    products: dict[int, Product] = {}
    if product_ids:
        rows = (
            await db.execute(select(Product).where(Product.id.in_(product_ids)))
        ).scalars().all()
        products = {p.id: p for p in rows}

    pair_cache: dict[tuple[str, ...], product_pair_resolver.ResolvedPair | None] = {}
    candidates_cache: dict[int, list[float]] = {}
    result: dict[int, PositionHangerValue] = {}
    for p in positions:
        if (p.source_payload or {}).get("paired_profile"):
            result[p.id] = await _resolve_paired_position_hanger(
                db, p, pair_cache=pair_cache, candidates_cache=candidates_cache
            )
            continue
        product = products.get(p.product_id) if p.product_id is not None else None
        result[p.id] = resolve_position_hanger(
            product,
            length_mm=position_length_mm(p),
            payload_quantity_per_hanger=payload_quantity_per_hanger(p),
        )
    return result


def _snapshot_pair_hanger(position) -> PositionHangerValue | None:
    """N и source из снапшота ``product_pair`` позиции (``resolved=True``)."""
    snapshot = product_pair_resolver.pair_snapshot(position.source_payload)
    if snapshot is None:
        return None
    raw = snapshot.get("quantity_per_hanger")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    source: QuantityPerHangerSource = (
        snapshot.get("source") if snapshot.get("source") in ("auto", "manual") else None
    )
    return PositionHangerValue(value, source)


async def _resolve_paired_position_hanger(
    db: AsyncSession,
    position,
    *,
    pair_cache: dict[tuple[str, ...], product_pair_resolver.ResolvedPair | None] | None = None,
    candidates_cache: dict[int, list[float]] | None = None,
) -> PositionHangerValue:
    """N и source парной позиции: override → снапшот → резолв пары.

    Неположительный override (0/отрицательный) override'ом не считается — то
    же правило, что у ``resolve_pair_n`` и ручных норм одиночных (``manual > 0``).
    Кэши (необязательные) ограничены одним вызовом батча: ``pair_cache`` — по
    нормализованному кортежу компонентов, ``candidates_cache`` — длины пары по
    её id.
    """
    override = payload_quantity_per_hanger(position)
    if override is not None and override > 0:
        return PositionHangerValue(override, "manual")

    snapshot_value = _snapshot_pair_hanger(position)
    if snapshot_value is not None:
        return snapshot_value

    component_skus = product_pair_resolver.paired_component_skus(position)
    key = product_pair_resolver.pair_component_key(component_skus)
    if pair_cache is not None and key in pair_cache:
        resolved = pair_cache[key]
    else:
        resolved = await product_pair_resolver.resolve_pair_by_component_skus(db, component_skus)
        if pair_cache is not None:
            pair_cache[key] = resolved
    if resolved is None:
        return PositionHangerValue(None, None)

    length_candidates = None
    if candidates_cache is not None:
        pair_id = resolved.pair.id
        if pair_id not in candidates_cache:
            candidates_cache[pair_id] = await product_pair_resolver.pair_length_candidates_mm(db, resolved)
        length_candidates = candidates_cache[pair_id]
    pair_n = await product_pair_resolver.resolve_pair_n(
        db, resolved, length_mm=position_length_mm(position),
        length_candidates_mm=length_candidates,
    )
    if pair_n.calc_error:
        return PositionHangerValue(None, None)
    return PositionHangerValue(pair_n.quantity_per_hanger, pair_n.source)
