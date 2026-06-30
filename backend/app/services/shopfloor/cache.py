from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_plan import SectionPlanLine
from app.models.movement import Movement, MovementType
from app.models.work_task import WorkTask, WorkTaskStatus
from app.models.defect import Defect, DefectDecision, DefectDecisionType

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
    For subsequent stages, if the previous stage is in the same SPG/GHP,
    availability comes from the completed quantity of the previous stage's task.
    Otherwise, availability comes only from received transfers.
    """
    line = await db.get(SectionPlanLine, task.section_plan_line_id)
    if line is None:
        return Decimal("0")
    if line.sequence == 1:
        return task.planned_quantity

    # Find previous stage plan line
    prev_line = await db.scalar(
        select(SectionPlanLine).where(
            SectionPlanLine.plan_position_id == line.plan_position_id,
            SectionPlanLine.sequence == line.sequence - 1,
        )
    )
    if prev_line is not None:
        from .common import sections_share_spg
        if await sections_share_spg(db, line.section_id, prev_line.section_id):
            # Find the previous task
            prev_task = await db.scalar(
                select(WorkTask).where(
                    WorkTask.section_plan_line_id == prev_line.id,
                    WorkTask.status.notin_([WorkTaskStatus.cancelled]),
                )
            )
            if prev_task is not None:
                return prev_task.cached_completed_quantity

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

async def _refresh_task_cache(db: AsyncSession, task_id: int, visited: set[int] | None = None) -> WorkTask:
    if visited is None:
        visited = set()
    if task_id in visited:
        return await _get_task(db, task_id)
    visited.add(task_id)

    task = await _get_task(db, task_id)
    sums = await _task_movement_sums(db, task_id)

    # Решения по дефектам этой задачи, чтобы вычесть одобренные/вторично списанные детали
    decisions_query = (
        select(
            DefectDecision.decision_type,
            func.coalesce(func.sum(DefectDecision.quantity), 0)
        )
        .join(Defect, Defect.id == DefectDecision.defect_id)
        .where(Defect.task_id == task_id)
        .group_by(DefectDecision.decision_type)
    )
    decision_rows = (await db.execute(decisions_query)).all()
    decisions = {r[0]: _to_decimal(r[1] or 0) for r in decision_rows}

    scrap_decisions = decisions.get(DefectDecisionType.scrap, Decimal("0"))
    accept_deviation_decisions = decisions.get(DefectDecisionType.accept_with_deviation, Decimal("0"))

    issued = sums.get(MovementType.issue_to_work.value, Decimal("0"))
    completed = sums.get(MovementType.complete.value, Decimal("0"))
    transferred = sums.get(MovementType.transfer_send.value, Decimal("0"))
    received = sums.get(MovementType.transfer_receive.value, Decimal("0"))

    rejected = (
        sums.get(MovementType.reject.value, Decimal("0"))
        + sums.get(MovementType.scrap.value, Decimal("0"))
        - scrap_decisions
        - accept_deviation_decisions
    )
    if rejected < 0:
        rejected = Decimal("0")
    returned = sums.get(MovementType.return_to_previous.value, Decimal("0"))
    in_work = issued - completed - rejected - returned
    if in_work < 0:
        in_work = Decimal("0")

    prev_completed = Decimal("0")
    line = await db.get(SectionPlanLine, task.section_plan_line_id)
    if line is not None and line.sequence > 1:
        prev_line = await db.scalar(
            select(SectionPlanLine).where(
                SectionPlanLine.plan_position_id == line.plan_position_id,
                SectionPlanLine.sequence == line.sequence - 1,
            )
        )
        if prev_line is not None:
            from .common import sections_share_spg
            if await sections_share_spg(db, prev_line.section_id, line.section_id):
                prev_completed = await db.scalar(
                    select(func.coalesce(func.sum(Movement.quantity), 0))
                    .join(WorkTask, Movement.task_id == WorkTask.id)
                    .where(
                        WorkTask.section_plan_line_id == prev_line.id,
                        Movement.movement_type == MovementType.complete.value
                    )
                ) or Decimal("0")

    base_available = await _initial_available_quantity(db, task)
    consumed_from_remainders = await db.scalar(
        select(func.coalesce(func.sum(Movement.quantity), 0)).where(
            Movement.task_id == task_id,
            Movement.movement_type == MovementType.issue_to_work,
            Movement.source_ref.like("remainder:%"),
        )
    ) or Decimal("0")
    available = base_available + received + consumed_from_remainders + prev_completed - issued
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
    elif available > 0 and task.status == WorkTaskStatus.waiting_previous:
        task.status = WorkTaskStatus.ready

    # Cascade refresh to the next task if it is in the same GHP
    line = await db.get(SectionPlanLine, task.section_plan_line_id)
    if line is not None:
        next_line = await db.scalar(
            select(SectionPlanLine).where(
                SectionPlanLine.plan_position_id == line.plan_position_id,
                SectionPlanLine.sequence == line.sequence + 1,
            )
        )
        if next_line is not None:
            from .common import sections_share_spg
            if await sections_share_spg(db, line.section_id, next_line.section_id):
                next_task = await db.scalar(
                    select(WorkTask).where(
                        WorkTask.section_plan_line_id == next_line.id,
                        WorkTask.status.notin_([WorkTaskStatus.cancelled]),
                    )
                )
                if next_task is not None:
                    await _refresh_task_cache(db, next_task.id, visited)
                    await _refresh_section_plan_line_cache(db, next_line.id)

    await db.flush()
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

