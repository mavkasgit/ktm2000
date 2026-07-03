from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_plan import SectionPlanLine
from app.models.work_task import WorkTask

from .common import _to_decimal


def _compute_available_from_balances(
    *,
    planned_quantity: Decimal,
    received_quantity: Decimal,
    issued_quantity: Decimal,
    is_first_stage: bool,
) -> Decimal:
    """Compute available quantity from cached balances (pure, no DB)."""
    base_available = planned_quantity if is_first_stage else Decimal("0")
    available = base_available + received_quantity - issued_quantity
    return available if available > 0 else Decimal("0")


async def _refresh_section_plan_line_cache(db: AsyncSession, section_plan_line_id: int) -> None:
    """Refresh SectionPlanLine cached aggregates from WorkTask cached_* columns.

    Cached values are maintained by StockProjectionManager.refresh_task_projection
    (which reads from StockTransaction ledger). This function simply aggregates
    those per-task values up to the plan-line level.
    """
    line = await db.get(SectionPlanLine, section_plan_line_id)
    if line is None:
        return

    sums = (
        await db.execute(
            select(
                func.coalesce(func.sum(WorkTask.cached_available_quantity), 0),
                func.coalesce(func.sum(WorkTask.cached_issued_quantity), 0),
                func.coalesce(func.sum(WorkTask.cached_completed_quantity), 0),
                func.coalesce(func.sum(WorkTask.cached_transferred_quantity), 0),
                func.coalesce(func.sum(WorkTask.cached_received_quantity), 0),
                func.coalesce(func.sum(WorkTask.cached_rejected_quantity), 0),
                func.coalesce(func.sum(WorkTask.cached_remaining_quantity), 0),
            ).where(WorkTask.section_plan_line_id == section_plan_line_id)
        )
    ).one()

    line.cached_available_quantity = _to_decimal(sums[0] or 0)
    line.cached_issued_quantity = _to_decimal(sums[1] or 0)
    line.cached_completed_quantity = _to_decimal(sums[2] or 0)
    line.cached_transferred_quantity = _to_decimal(sums[3] or 0)
    line.cached_received_quantity = _to_decimal(sums[4] or 0)
    line.cached_rejected_quantity = _to_decimal(sums[5] or 0)
    line.cached_remaining_quantity = _to_decimal(sums[6] or 0)
