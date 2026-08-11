"""Интеграция авторасчёта «количество на подвес» с планированием (#66, спек #59 п. 57).

Две точки вызова: отображение (``PlanPositionOut``) и валидация
(``validate_plan_position``). Расчёт на лету, кэша в позиции нет — позиция
хранит только ручное payload-значение, авто пересчитывается при каждом
сериализуемом чтении.

Контракт вывода (#66):

    quantity_per_hanger: int | null
    quantity_per_hanger_source: "auto" | "manual" | null

Приоритет: ручной override из payload > авто > null. Позиция с конкретной
длиной берёт значение для своей длины (``input_dimensions["length_mm"]``);
без длины / артикул без данных — текущее поведение (payload-значение или
null). ``total <= 0`` (или несовместимые габариты) — расчёт невозможен:
``calc_error``, вызывающий выставляет ``hanger_calc_zero``.

Парные техкарты — вне рамок (#58): позиция без ``product_id`` всегда
фолбэчится на payload-значение.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dimensions import LENGTH_MM
from app.models.product import Product
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
    payload (кэша в позиции нет). Терпимо к legacy-строкам из старых
    импортов.
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


def resolve_position_hanger(
    product: Product | None,
    *,
    length_mm: float | None,
    payload_quantity_per_hanger: int | None,
) -> PositionHangerValue:
    """Разрешить (quantity_per_hanger, source) для позиции плана.

    Приоритет (#66): ручной override из payload > авто > null.

    - Ручной override (payload-скаляр) → source="manual", всегда побеждает;
    - артикул авто (заполнены периметр И габарит) + конкретная длина →
      авто-расчёт этой длины, source="auto"; ``total <= 0`` или несовместимые
      габариты (``mount_width + gap > rod_length``) → ``calc_error=True``
      (значение null, вызывающий ставит ``hanger_calc_zero``);
    - иначе (нет длины / артикул без данных) → null.
    """
    if payload_quantity_per_hanger is not None:
        return PositionHangerValue(payload_quantity_per_hanger, "manual")

    if (
        product is not None
        and product.perimeter_mm
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
    """Batch-резолв значений для списка позиций: один запрос продуктов.

    Возвращает ``{position_id: PositionHangerValue}`` — ровно по одной
    записи на позицию, включая без ``product_id`` (парные — вне рамок).
    """
    product_ids = {p.product_id for p in positions if p.product_id is not None}
    products: dict[int, Product] = {}
    if product_ids:
        rows = (
            await db.execute(select(Product).where(Product.id.in_(product_ids)))
        ).scalars().all()
        products = {p.id: p for p in rows}

    result: dict[int, PositionHangerValue] = {}
    for p in positions:
        product = products.get(p.product_id) if p.product_id is not None else None
        result[p.id] = resolve_position_hanger(
            product,
            length_mm=position_length_mm(p),
            payload_quantity_per_hanger=payload_quantity_per_hanger(p),
        )
    return result
