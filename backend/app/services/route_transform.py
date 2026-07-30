"""Трансформация габаритов — способность этапа маршрута (ADR-0002).

Ядро универсально для любого завода: этап объявляется трансформирующим
маркером ``RouteStage.transforms_dimensions``. Заводская специфика
(какой участок «пила») задаётся данными — сид помечает операции в
справочнике участка (``SectionOperation.transforms_dimensions``),
бизнес-логика никогда не сравнивает код секции со строкой.
"""
from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.production_plan import PlanPosition
from app.models.route import RouteStage, SectionOperation

# Шаг квантования количеств — совпадает с Numeric(14, 3) в моделях.
_QTY_STEP = Decimal("0.001")


async def resolve_stage_transforms_dimensions(
    db: AsyncSession,
    *,
    section_id: int | None,
    operation_codes: Iterable[str | None] | None = None,
) -> bool:
    """Определить маркер трансформации для создаваемого этапа маршрута.

    Источник правды — справочник операций участка (:class:`SectionOperation`),
    который наполняется сидом. Если коды операций этапа известны — маркер
    ставится при совпадении хотя бы одной трансформирующей операции; если
    операции этапа не заданы явно (динамические маршруты с
    ``operation_code=None``) — этап наследует способность участка.
    """
    if section_id is None:
        return False
    transforming_codes = set(
        (
            await db.execute(
                select(SectionOperation.operation_code).where(
                    SectionOperation.section_id == section_id,
                    SectionOperation.transforms_dimensions.is_(True),
                )
            )
        ).scalars()
    )
    if not transforming_codes:
        return False
    explicit = {code for code in (operation_codes or []) if code}
    if not explicit:
        return True
    return bool(explicit & transforming_codes)


def build_transform_spec(position: PlanPosition, task_quantity: Decimal) -> dict:
    """Собрать вход и спецификацию выходов задания из позиции плана.

    Возвращает поля ``WorkTask`` (``input_quantity``, ``input_dimensions``,
    ``outputs``) для трансформирующего этапа. Позиция без операции
    (нет выходов) → пустой dict: задание без dimensions (edge case ADR-0003).

    При частичном выпуске вход и выходы масштабируются пропорционально
    доле ``task_quantity`` от полного количества позиции (ADR-0002 п. 6:
    порции пропорциональны).
    """
    outputs = [dict(entry) for entry in (position.outputs or [])]
    if not outputs or task_quantity <= 0:
        return {}

    ratio = Decimal(1)
    position_quantity = Decimal(str(position.quantity or 0))
    if position_quantity > 0 and task_quantity != position_quantity:
        ratio = task_quantity / position_quantity

    input_quantity = None
    if position.input_quantity is not None:
        input_quantity = _scale(Decimal(str(position.input_quantity)), ratio)

    if ratio != 1:
        for entry in outputs:
            raw_qty = entry.get("quantity")
            if raw_qty is None:
                continue
            entry["quantity"] = _decimal_to_str(_scale(Decimal(str(raw_qty)), ratio))

    return {
        "input_quantity": input_quantity,
        "input_dimensions": position.input_dimensions,
        "outputs": outputs,
    }


async def transform_fields_for_task(
    db: AsyncSession,
    *,
    route_stage_id: int,
    plan_position_id: int | None,
    task_quantity: Decimal,
) -> dict:
    """Поля входа/выходов для создаваемого задания.

    Пустой dict, если этап не трансформирующий или позиция не несёт
    операцию — задание создаётся как раньше (габарит проносится
    без изменений на нетрансформирующих этапах).
    """
    stage = await db.get(RouteStage, route_stage_id)
    if stage is None or not stage.transforms_dimensions:
        return {}
    if plan_position_id is None:
        return {}
    position = await db.get(PlanPosition, plan_position_id)
    if position is None:
        return {}
    return build_transform_spec(position, task_quantity)


def _scale(value: Decimal, ratio: Decimal) -> Decimal:
    if ratio == 1:
        return value
    return (value * ratio).quantize(_QTY_STEP, rounding=ROUND_HALF_UP)


def _decimal_to_str(value: Decimal) -> str:
    return format(value.normalize(), "f")
