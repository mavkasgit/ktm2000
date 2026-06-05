from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_plan import SectionPlanLine
from app.models.movement import Movement, MovementType
from app.models.work_task import WorkTask, WorkTaskStatus

from .common import _get_task, _to_decimal

async def _task_movement_sums(db: AsyncSession, task_id: int) -> dict[str, Decimal]:
    rows = (
        await db.execute(
            select(
                Movement.movement_type,
                func.coalesce(func.sum(Movement.quantity), 0).label("qty"),
            )
            .where(Movement.task_id == task_id)
            .group_by(Movement.movement_type)
        )
    ).all()
    sums: dict[str, Decimal] = {}
    for movement_type, qty in rows:
        key = movement_type.value if hasattr(movement_type, "value") else str(movement_type)
        sums[key] = _to_decimal(qty or 0)
    return sums

async def _initial_available_quantity(db: AsyncSession, task: WorkTask) -> Decimal:
    """Base availability before incoming transfers.

    For the first route stage, task can start from planned quantity.
    For subsequent stages, availability comes only from received transfers.
    """
    line = await db.get(SectionPlanLine, task.section_plan_line_id)
    if line is not None and line.sequence == 1:
        return task.planned_quantity
    return Decimal("0")

def _compute_available_from_balances(
    *,
    planned_quantity: Decimal,
    received_quantity: Decimal,
    issued_quantity: Decimal,
    is_first_stage: bool,
) -> Decimal:
    base_available = planned_quantity if is_first_stage else Decimal("0")
    available = base_available + received_quantity - issued_quantity
    return available if available > 0 else Decimal("0")

async def _refresh_task_cache(db: AsyncSession, task_id: int) -> WorkTask:
    task = await _get_task(db, task_id)
    sums = await _task_movement_sums(db, task_id)

    issued = sums.get(MovementType.issue_to_work.value, Decimal("0"))
    completed = sums.get(MovementType.complete.value, Decimal("0"))
    transferred = sums.get(MovementType.transfer_send.value, Decimal("0"))
    received = sums.get(MovementType.transfer_receive.value, Decimal("0"))
    rejected = sums.get(MovementType.reject.value, Decimal("0")) + sums.get(MovementType.scrap.value, Decimal("0"))
    returned = sums.get(MovementType.return_to_previous.value, Decimal("0"))
    in_work = issued - completed - rejected - returned
    if in_work < 0:
        in_work = Decimal("0")

    base_available = await _initial_available_quantity(db, task)
    consumed_from_remainders = await db.scalar(
        select(func.coalesce(func.sum(Movement.quantity), 0)).where(
            Movement.task_id == task_id,
            Movement.movement_type == MovementType.issue_to_work,
            Movement.source_ref.like("remainder:%"),
        )
    ) or Decimal("0")
    available = base_available + received + consumed_from_remainders - issued
    if available < 0:
        available = Decimal("0")

    remaining = task.planned_quantity - transferred
    if remaining < 0:
        remaining = Decimal("0")

    task.cached_issued_quantity = issued
    task.cached_completed_quantity = completed
    task.cached_transferred_quantity = transferred
    task.cached_received_quantity = received
    task.cached_rejected_quantity = rejected
    task.cached_in_work_quantity = in_work
    task.cached_available_quantity = available
    task.cached_remaining_quantity = remaining

    # Task is "completed" when the section has worked off everything that was
    # available to it (planned initial + what was received via transfers).
    # The transfer to the next SPG is a SEPARATE process and does NOT gate
    # this status anymore — a WorkTask can be `completed` while still
    # holding transferable quantity (cached_completed - cached_transferred > 0).
    #
    # `final_release` is still consulted: on a final route step, the route
    # terminates with a final_release movement instead of a transfer, so
    # once the final step's quantity is final-released, the task is closed.
    if completed + rejected >= task.planned_quantity:
        task.status = WorkTaskStatus.completed
    elif completed + rejected > 0:
        task.status = WorkTaskStatus.partially_completed
    elif issued > 0:
        task.status = WorkTaskStatus.in_progress
    elif received > 0 or task.status in {WorkTaskStatus.ready, WorkTaskStatus.waiting_previous}:
        pass

    return task

async def _refresh_section_plan_line_cache(db: AsyncSession, section_plan_line_id: int) -> None:
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

