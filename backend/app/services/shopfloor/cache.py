from __future__ import annotations

from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_plan import SectionPlanLine
from app.models.work_task import WorkTask
from app.stock.models import Reason, StockTransaction

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
    """Refresh SectionPlanLine cached aggregates from StockTransaction ledger.

    Aggregates per-task StockTransaction sums up to the plan-line level.
    """
    line = await db.get(SectionPlanLine, section_plan_line_id)
    if line is None:
        return

    # Найти все task_ids для этой plan line
    task_ids = (
        await db.execute(
            select(WorkTask.id).where(WorkTask.section_plan_line_id == section_plan_line_id)
        )
    ).scalars().all()

    if not task_ids:
        # Обнулить все cached_* на line
        line.cached_available_quantity = Decimal("0")
        line.cached_issued_quantity = Decimal("0")
        line.cached_completed_quantity = Decimal("0")
        line.cached_transferred_quantity = Decimal("0")
        line.cached_received_quantity = Decimal("0")
        line.cached_rejected_quantity = Decimal("0")
        line.cached_remaining_quantity = Decimal("0")
        return

    # Прямой SELECT из StockTransaction: sum(quantity) GROUP BY reason для всех task_ids
    tx_rows = await db.execute(
        select(
            StockTransaction.reason,
            func.sum(StockTransaction.quantity).label("qty"),
        )
        .where(StockTransaction.task_id.in_(task_ids))
        .group_by(StockTransaction.reason)
    )
    sums: dict[str, Decimal] = {}
    for reason_val, qty in tx_rows:
        sums[reason_val] = qty or Decimal("0")

    # Net для transfer_send/receive с компенсациями
    net_rows = await db.execute(
        select(
            StockTransaction.reason,
            func.sum(
                case(
                    (StockTransaction.compensates_tx_id.is_(None), StockTransaction.quantity),
                    else_=-StockTransaction.quantity,
                )
            ).label("net"),
        )
        .where(
            StockTransaction.task_id.in_(task_ids),
            StockTransaction.reason.in_([Reason.transfer_send, Reason.transfer_receive]),
        )
        .group_by(StockTransaction.reason)
    )
    net_sums: dict[str, Decimal] = {}
    for reason_val, net in net_rows:
        net_sums[reason_val] = net or Decimal("0")

    def _s(reason: Reason) -> Decimal:
        return sums.get(reason.value) or Decimal("0")

    issued = _s(Reason.issue_to_work)
    completed = _s(Reason.complete)
    scrapped = _s(Reason.scrap)
    transferred = net_sums.get(Reason.transfer_send.value) or Decimal("0")
    received = net_sums.get(Reason.transfer_receive.value) or Decimal("0")
    rejected = scrapped

    # available: для первой стадии = planned, иначе 0
    is_first_stage = (line.sequence == 1)
    base_available = line.planned_quantity if is_first_stage else Decimal("0")
    returned = _s(Reason.return_to_stock)
    available = base_available + received + returned - issued
    if available < Decimal("0"):
        available = Decimal("0")

    remaining = line.planned_quantity - transferred
    if remaining < Decimal("0"):
        remaining = Decimal("0")

    line.cached_available_quantity = available
    line.cached_issued_quantity = issued
    line.cached_completed_quantity = completed
    line.cached_transferred_quantity = transferred
    line.cached_received_quantity = received
    line.cached_rejected_quantity = rejected
    line.cached_remaining_quantity = remaining
