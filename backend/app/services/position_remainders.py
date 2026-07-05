from __future__ import annotations

from decimal import Decimal

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_plan import SectionPlanLine
from app.models.production_plan import PlanPosition, PlanPositionStatus
from app.models.section import Section
from app.models.work_task import WorkTask, WorkTaskStatus
from app.stock.models import QualityState, StockBalance

# Участки-хранилища: остаток «на полке», не на производственном участке.
_STORAGE_SECTION_TYPES = frozenset(
    {"raw_stock", "wip_stock", "finished_stock", "scrap", "quarantine"},
)


async def _physical_stock_by_product_ids(
    db: AsyncSession,
    product_ids: set[int],
) -> dict[int, float]:
    if not product_ids:
        return {}

    rows = await db.execute(
        select(
            StockBalance.product_id,
            func.coalesce(func.sum(StockBalance.balance_qty), 0),
        )
        .join(Section, Section.id == StockBalance.location_id)
        .where(
            StockBalance.product_id.in_(product_ids),
            StockBalance.balance_qty > 0,
            StockBalance.quality_state == QualityState.GOOD,
            Section.type.in_(_STORAGE_SECTION_TYPES),
        )
        .group_by(StockBalance.product_id)
    )
    return {int(product_id): float(total or 0) for product_id, total in rows.all()}


async def _committed_demand_by_product_ids(
    db: AsyncSession,
    product_ids: set[int],
) -> dict[int, float]:
    """Сумма плановых количеств позиций, уже запущенных в работу (есть задачи), но не завершённых."""
    if not product_ids:
        return {}

    open_task_on_position = exists(
        select(1)
        .select_from(SectionPlanLine)
        .join(WorkTask, WorkTask.section_plan_line_id == SectionPlanLine.id)
        .where(
            SectionPlanLine.plan_position_id == PlanPosition.id,
            WorkTask.status.notin_([WorkTaskStatus.completed, WorkTaskStatus.cancelled]),
        )
    )

    position_rows = (
        select(
            PlanPosition.id.label("position_id"),
            PlanPosition.quantity.label("quantity"),
            func.min(SectionPlanLine.product_id).label("product_id"),
        )
        .join(SectionPlanLine, SectionPlanLine.plan_position_id == PlanPosition.id)
        .where(
            SectionPlanLine.product_id.in_(product_ids),
            PlanPosition.status == PlanPositionStatus.released,
            open_task_on_position,
        )
        .group_by(PlanPosition.id, PlanPosition.quantity)
    ).subquery()

    rows = await db.execute(
        select(
            position_rows.c.product_id,
            func.coalesce(func.sum(position_rows.c.quantity), 0),
        ).group_by(position_rows.c.product_id)
    )
    return {int(product_id): float(total or 0) for product_id, total in rows.all()}


async def compute_available_remainder_quantities(
    db: AsyncSession,
    product_ids: set[int],
) -> dict[int, float]:
    """Доступный остаток по продуктам: физический склад − занято запущенными позициями."""
    physical = await _physical_stock_by_product_ids(db, product_ids)
    committed = await _committed_demand_by_product_ids(db, product_ids)
    result: dict[int, float] = {}
    for product_id in product_ids:
        free = physical.get(product_id, 0.0) - committed.get(product_id, 0.0)
        result[product_id] = max(0.0, free)
    return result


async def compute_available_remainder_quantity(
    db: AsyncSession,
    *,
    effective_product_id: int | None,
    route_steps: list[dict],
    position_id: int | None = None,
) -> float:
    """Свободный остаток для индикатора в плане/выполнении.

    Физический остаток (StockBalance, GOOD, только склады-хранилища)
    минус плановое количество позиций, уже запущенных в работу
    (status=released, есть незавершённые задачи).

    ``route_steps`` и ``position_id`` сохранены для совместимости API.
    """
    del route_steps, position_id
    if effective_product_id is None:
        return 0.0

    quantities = await compute_available_remainder_quantities(db, {effective_product_id})
    return quantities.get(effective_product_id, 0.0)