from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import Defect, DefectItem, DefectStatus
from app.models.internal_plan import SectionPlanLine
from app.models.movement import Movement, MovementType
from app.models.production_plan import PlanPosition, PlanPositionStatus
from app.models.work_task import WorkTask, WorkTaskStatus

from .cache import _refresh_section_plan_line_cache, _refresh_task_cache
from .common import _check_idempotency, _ensure_positive, _get_route_step, _get_task, _to_decimal

async def issue_to_work(
    db: AsyncSession,
    *,
    task_id: int,
    quantity: Decimal,
    actor_id: int,
    comment: str | None = None,
    source_ref: str | None = None,
    idempotency_key: str | None = None,
    executor_user_id: int | None = None,
    performed_at: datetime | None = None,
    accounted_at: datetime | None = None,
) -> dict:
    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")

    existing = await _check_idempotency(db, idempotency_key=idempotency_key, entity_type=Movement)
    if existing is not None:
        task = await _get_task(db, task_id)
        return {"movement_id": existing.id, "task_id": task.id, "status": task.status.value, "idempotent_replay": True}

    task = await _get_task(db, task_id)
    if task.status not in {WorkTaskStatus.ready, WorkTaskStatus.in_progress, WorkTaskStatus.partially_completed}:
        raise ValueError("Task must be ready/in_progress/partially_completed")

    task = await _refresh_task_cache(db, task.id)
    available = task.cached_available_quantity
    if quantity > available:
        raise ValueError("Issue quantity exceeds available quantity")

    now = datetime.now(UTC)
    movement = Movement(
        product_id=task.product_id,
        task_id=task.id,
        section_plan_line_id=task.section_plan_line_id,
        from_section_id=task.section_id,
        to_section_id=task.section_id,
        movement_type=MovementType.issue_to_work,
        quantity=quantity,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        comment=comment,
        created_by=actor_id,
        executor_user_id=executor_user_id or actor_id,
        performed_at=performed_at or now,
        accounted_at=accounted_at or now,
    )
    db.add(movement)
    task.status = WorkTaskStatus.in_progress
    await db.flush()
    await _refresh_task_cache(db, task.id)
    await _refresh_section_plan_line_cache(db, task.section_plan_line_id)
    return {"movement_id": movement.id, "task_id": task.id, "status": task.status.value}

async def complete_task(
    db: AsyncSession,
    *,
    task_id: int,
    good_quantity: Decimal,
    defect_quantity: Decimal,
    actor_id: int,
    defect_reason: str | None = None,
    comment: str | None = None,
    source_ref: str | None = None,
    idempotency_key: str | None = None,
    executor_user_id: int | None = None,
    performed_at: datetime | None = None,
    accounted_at: datetime | None = None,
) -> dict:
    task = await _get_task(db, task_id)

    if idempotency_key:
        existing = await _check_idempotency(db, idempotency_key=idempotency_key, entity_type=Movement)
        if existing is not None:
            # Find associated defect from the same completion operation
            reject_movement_key = f"{idempotency_key}:reject"
            defect = await db.scalar(
                select(Defect).where(Defect.idempotency_key == reject_movement_key)
            )
            return {
                "task_id": task.id,
                "movement_ids": [existing.id],
                "defect_id": defect.id if defect else None,
                "status": task.status.value,
                "idempotent_replay": True,
            }

    if task.status not in {WorkTaskStatus.in_progress, WorkTaskStatus.partially_completed, WorkTaskStatus.ready}:
        raise ValueError("Task must be in progress")

    good_quantity = _to_decimal(good_quantity)
    defect_quantity = _to_decimal(defect_quantity)
    if good_quantity < 0 or defect_quantity < 0:
        raise ValueError("Quantities must be >= 0")
    total = good_quantity + defect_quantity
    _ensure_positive(total, "good_quantity + defect_quantity")

    in_work = task.cached_issued_quantity - task.cached_completed_quantity - task.cached_rejected_quantity
    if total > in_work:
        raise ValueError("Complete quantity exceeds quantity in work")

    now = datetime.now(UTC)
    eff_performed = performed_at or now
    eff_accounted = accounted_at or now
    eff_executor = executor_user_id or actor_id

    movement_ids: list[int] = []
    defect_id: int | None = None
    if good_quantity > 0:
        good_movement = Movement(
            product_id=task.product_id,
            task_id=task.id,
            section_plan_line_id=task.section_plan_line_id,
            from_section_id=task.section_id,
            to_section_id=task.section_id,
            movement_type=MovementType.complete,
            quantity=good_quantity,
            source_ref=source_ref,
            comment=comment,
            created_by=actor_id,
            idempotency_key=idempotency_key,
            executor_user_id=eff_executor,
            performed_at=eff_performed,
            accounted_at=eff_accounted,
        )
        db.add(good_movement)
        await db.flush()
        movement_ids.append(good_movement.id)

    if defect_quantity > 0:
        reject_movement = Movement(
            product_id=task.product_id,
            task_id=task.id,
            section_plan_line_id=task.section_plan_line_id,
            from_section_id=task.section_id,
            to_section_id=task.section_id,
            movement_type=MovementType.reject,
            quantity=defect_quantity,
            source_ref=source_ref,
            reason=defect_reason,
            comment=comment,
            created_by=actor_id,
            idempotency_key=f"{idempotency_key}:reject" if idempotency_key else None,
            executor_user_id=eff_executor,
            performed_at=eff_performed,
            accounted_at=eff_accounted,
        )
        db.add(reject_movement)
        await db.flush()
        movement_ids.append(reject_movement.id)

        defect = Defect(
            product_id=task.product_id,
            section_id=task.section_id,
            task_id=task.id,
            movement_id=reject_movement.id,
            status=DefectStatus.decision_required,
            comment=comment,
            created_by=actor_id,
            idempotency_key=f"{idempotency_key}:defect" if idempotency_key else None,
        )
        db.add(defect)
        await db.flush()
        defect_id = defect.id

        defect_item = DefectItem(
            defect_id=defect.id,
            defect_type_id=None,
            defect_type_code_snapshot=defect_reason,
            defect_type_name_snapshot=defect_reason,
            quantity=defect_quantity,
            description=comment,
            created_by=actor_id,
        )
        db.add(defect_item)

    await _refresh_task_cache(db, task.id)
    await _refresh_section_plan_line_cache(db, task.section_plan_line_id)
    return {"task_id": task.id, "movement_ids": movement_ids, "defect_id": defect_id, "status": task.status.value}

async def final_release(
    db: AsyncSession,
    *,
    task_id: int,
    quantity: Decimal,
    actor_id: int,
    comment: str | None = None,
    idempotency_key: str | None = None,
    executor_user_id: int | None = None,
    performed_at: datetime | None = None,
    accounted_at: datetime | None = None,
) -> dict:
    if idempotency_key:
        existing = await _check_idempotency(db, idempotency_key=idempotency_key, entity_type=Movement)
        if existing is not None:
            return {"movement_id": existing.id, "task_id": task_id, "idempotent_replay": True}

    task = await _get_task(db, task_id)
    step = await _get_route_step(db, task.route_step_id)
    if not step.is_final:
        raise ValueError("Final release allowed only for final route step")

    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")
    final_released = await db.scalar(
        select(func.coalesce(func.sum(Movement.quantity), 0)).where(
            Movement.task_id == task.id, Movement.movement_type == MovementType.final_release
        )
    )
    releasable = task.cached_completed_quantity - _to_decimal(final_released or 0)
    if quantity > releasable:
        raise ValueError("Final release exceeds releasable quantity")

    movement = Movement(
        product_id=task.product_id,
        task_id=task.id,
        section_plan_line_id=task.section_plan_line_id,
        from_section_id=task.section_id,
        to_section_id=task.section_id,
        movement_type=MovementType.final_release,
        quantity=quantity,
        comment=comment,
        created_by=actor_id,
        idempotency_key=idempotency_key,
        executor_user_id=executor_user_id or actor_id,
        performed_at=performed_at or datetime.now(UTC),
        accounted_at=accounted_at or datetime.now(UTC),
    )
    db.add(movement)
    await _refresh_task_cache(db, task.id)
    await _refresh_section_plan_line_cache(db, task.section_plan_line_id)
    return {"movement_id": movement.id, "task_id": task.id}

async def prepare_section_task(
    db: AsyncSession,
    *,
    plan_position_id: int,
    section_id: int,
    quantity: Decimal,
    actor_id: int,
    idempotency_key: str | None = None,
) -> dict:
    """Create or return an existing WorkTask for a given section from a released plan position."""
    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")

    # Check plan position exists and is released
    pos = await db.get(PlanPosition, plan_position_id)
    if pos is None:
        raise ValueError("Plan position not found")
    if pos.status != PlanPositionStatus.released:
        raise ValueError("Plan position must be released")

    # Find the section plan line for this position + section
    line = await db.scalar(
        select(SectionPlanLine).where(
            SectionPlanLine.plan_position_id == plan_position_id,
            SectionPlanLine.section_id == section_id,
        )
    )
    if line is None:
        raise ValueError("No route step found for this section in the plan position")

    # Check for existing open task
    existing_task = await db.scalar(
        select(WorkTask).where(
            WorkTask.section_plan_line_id == line.id,
            WorkTask.status.notin_([WorkTaskStatus.completed, WorkTaskStatus.cancelled]),
        )
    )
    if existing_task is not None:
        return {
            "task_id": existing_task.id,
            "status": existing_task.status.value,
            "idempotent_replay": True,
        }

    # Create new task
    task = WorkTask(
        section_plan_line_id=line.id,
        section_id=section_id,
        product_id=line.product_id,
        route_step_id=line.route_step_id,
        planned_quantity=quantity,
        status=WorkTaskStatus.ready,
        due_date=line.due_date,
    )
    db.add(task)
    await db.flush()
    await _refresh_task_cache(db, task.id)
    await _refresh_section_plan_line_cache(db, task.section_plan_line_id)
    return {"task_id": task.id, "status": task.status.value}

