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

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import NO_VALUE

from app.domain.dimensions import LENGTH_MM
from app.models.product import HANGER_MODE_MANUAL, Product, _length_key
from app.services import product_pair_resolver
from app.services.hanger_quantity_calc import (
    HangerConfigError,
    compute_hanger_quantity,
)

QuantityPerHangerSource = Literal["auto", "manual"] | None


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


def _effective_raw_length_mm(product: Product, length_mm: float) -> float:
    """Effective raw для пары «артикул + нормальная длина» (ADR-0028)."""
    loaded_lengths = inspect(product).attrs.lengths.loaded_value
    if loaded_lengths is NO_VALUE:
        return length_mm
    for product_length in loaded_lengths:
        if _length_key(product_length.length_mm) == _length_key(length_mm):
            return product_length.effective_raw_length_mm
    return length_mm


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
                length_mm=_effective_raw_length_mm(product, length_mm),
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

    Позиция-компонент пары (собственный ``product_id``, но артикул входит в
    ``product_pairs``): норма — парная, на подвесе едут оба компонента
    сразу (#312). Артикул вне пары и ручной override из payload — прежняя
    одиночная механика. Склеенные позиции (payload ``paired_profile``,
    планы до #312): override → снапшот ``product_pair`` → резолв пары
    владельцем-модулем (``product_pair_resolver``).

    Всё, что осталось за этими быстрыми путями, резолвится пакетами:
    справочник пар читается один раз на вызов (``PairResolutionCache``),
    длины всех нужных пар — одним SELECT (``pair_length_candidates_bulk``)
    (#293). Возвращает ровно по одной записи на позицию.
    """
    product_ids = {p.product_id for p in positions if p.product_id is not None}
    products: dict[int, Product] = {}
    if product_ids:
        rows = (
            await db.execute(
                select(Product).options(selectinload(Product.lengths)).where(
                    Product.id.in_(product_ids)
                )
            )
        ).scalars().all()
        products = {p.id: p for p in rows}

    result: dict[int, PositionHangerValue] = {}
    # Позиции-компоненты пары: позиция несёт один артикул, но норма
    # «количество на подвес» — парная, ведь на подвесе едут оба
    # компонента сразу (#312). Артикул вне пары считается как раньше.
    pair_component_positions: list[tuple[object, Product]] = []
    # Позиции склеенной пары (payload ``paired_profile``) — прежний путь,
    # он остаётся валидным для планов, импортированных до #312.
    pending: list[tuple[object, list[str]]] = []
    for position in positions:
        if not (position.source_payload or {}).get("paired_profile"):
            product = products.get(position.product_id) if position.product_id is not None else None
            override = payload_quantity_per_hanger(position)
            if product is None or (override is not None and override > 0):
                result[position.id] = resolve_position_hanger(
                    product,
                    length_mm=position_length_mm(position),
                    payload_quantity_per_hanger=override,
                )
                continue
            pair_component_positions.append((position, product))
            continue
        override = payload_quantity_per_hanger(position)
        if override is not None and override > 0:
            result[position.id] = PositionHangerValue(override, "manual")
            continue
        snapshot_value = _snapshot_pair_hanger(position)
        if snapshot_value is not None:
            result[position.id] = snapshot_value
            continue
        pending.append((position, product_pair_resolver.paired_component_skus(position)))

    pair_cache = product_pair_resolver.PairResolutionCache()

    if pair_component_positions:
        pairs_by_position = {
            position.id: await pair_cache.resolve_pair_by_product(db, product.id)
            for position, product in pair_component_positions
        }
        candidates_by_pair = await product_pair_resolver.pair_length_candidates_bulk(
            db, [pair for pair in pairs_by_position.values() if pair is not None]
        )
        for position, product in pair_component_positions:
            resolved = pairs_by_position[position.id]
            if resolved is None:
                # Артикул вне пары — прежняя одиночная механика.
                result[position.id] = resolve_position_hanger(
                    product,
                    length_mm=position_length_mm(position),
                    payload_quantity_per_hanger=None,
                )
                continue
            pair_n = await product_pair_resolver.resolve_pair_n(
                db,
                resolved,
                length_mm=position_length_mm(position),
                length_candidates=candidates_by_pair.get(resolved.pair.id, []),
            )
            if pair_n.calc_error or pair_n.quantity_per_hanger is None:
                # Пара не разрешилась на этой длине — одиночная норма
                # артикула остаётся осмысленным значением, блокировать
                # позицию из-за чужой пары нельзя.
                result[position.id] = resolve_position_hanger(
                    product,
                    length_mm=position_length_mm(position),
                    payload_quantity_per_hanger=None,
                )
            else:
                result[position.id] = PositionHangerValue(
                    pair_n.quantity_per_hanger, pair_n.source
                )

    if not pending:
        return result

    resolved_by_position: dict[int, product_pair_resolver.ResolvedPair | None] = {
        position.id: await product_pair_resolver.resolve_pair_by_component_skus(
            db, component_skus, cache=pair_cache
        )
        for position, component_skus in pending
    }

    found_pairs = [pair for pair in resolved_by_position.values() if pair is not None]
    candidates_by_pair = await product_pair_resolver.pair_length_candidates_bulk(db, found_pairs)

    for position, _ in pending:
        resolved = resolved_by_position[position.id]
        if resolved is None:
            result[position.id] = PositionHangerValue(None, None)
            continue
        pair_n = await product_pair_resolver.resolve_pair_n(
            db,
            resolved,
            length_mm=position_length_mm(position),
            length_candidates=candidates_by_pair.get(resolved.pair.id, []),
        )
        if pair_n.calc_error:
            result[position.id] = PositionHangerValue(None, None)
        else:
            result[position.id] = PositionHangerValue(pair_n.quantity_per_hanger, pair_n.source)
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


