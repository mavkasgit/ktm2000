from __future__ import annotations

from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_plan import SectionPlanLine
from app.models.work_task import WorkTask
from app.stock.models import Reason, StockTransaction

from app.stock.task_cache import (
    compute_remaining,
    compute_task_available,
    effective_issued_quantity,
)

from .common import _to_decimal


def _compute_available_from_balances(
    *,
    planned_quantity: Decimal,
    received_quantity: Decimal,
    issued_quantity: Decimal,
    returned_quantity: Decimal = Decimal("0"),
    is_first_stage: bool,
) -> Decimal:
    """Compute available quantity from cached balances (pure, no DB)."""
    return compute_task_available(
        planned_quantity=planned_quantity,
        received_quantity=received_quantity,
        issued_quantity=issued_quantity,
        returned_quantity=returned_quantity,
        is_first_stage=is_first_stage,
    )


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
            StockTransaction.reason.in_([Reason.TRANSFER_SEND, Reason.TRANSFER_RECEIVE]),
        )
        .group_by(StockTransaction.reason)
    )
    net_sums: dict[str, Decimal] = {}
    for reason_val, net in net_rows:
        net_sums[reason_val] = net or Decimal("0")

    def _s(reason: Reason) -> Decimal:
        return sums.get(reason.value) or Decimal("0")

    completed = _s(Reason.COMPLETE)
    scrapped = _s(Reason.SCRAP)
    transferred = net_sums.get(Reason.TRANSFER_SEND.value) or Decimal("0")
    received = net_sums.get(Reason.TRANSFER_RECEIVE.value) or Decimal("0")
    rejected = scrapped
    issued = effective_issued_quantity(received=received)

    is_first_stage = (line.sequence == 1)
    returned = _s(Reason.RETURN_TO_STOCK)
    available = compute_task_available(
        planned_quantity=line.planned_quantity,
        received_quantity=received,
        issued_quantity=issued,
        returned_quantity=returned,
        is_first_stage=is_first_stage,
    )
    remaining = compute_remaining(
        planned_quantity=line.planned_quantity,
        transferred_quantity=transferred,
    )

    line.cached_available_quantity = available
    line.cached_issued_quantity = issued
    line.cached_completed_quantity = completed
    line.cached_transferred_quantity = transferred
    line.cached_received_quantity = received
    line.cached_rejected_quantity = rejected
    line.cached_remaining_quantity = remaining
