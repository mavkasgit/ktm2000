from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import Defect, DefectItem, DefectStatus
from app.models.internal_plan import SectionPlanLine
from app.models.movement import Movement, MovementType
from app.models.production_plan import PlanPosition, PlanPositionStatus
from app.models.spg_remainder import SpgRemainder
from app.models.work_task import WorkTask, WorkTaskStatus

from .cache import _refresh_section_plan_line_cache, _refresh_task_cache
from .common import _check_idempotency, _ensure_positive, _get_route_stage, _get_task, _get_user_snapshot_name, _to_decimal

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
    transfer_id: int | None = None,
) -> dict:
    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")

    existing = await _check_idempotency(db, idempotency_key=idempotency_key, entity_type=Movement)
    if existing is not None:
        task = await _get_task(db, task_id)
        return {"movement_id": existing.id, "task_id": task.id, "status": task.status.value, "idempotent_replay": True}

    task = await _get_task(db, task_id)
    if task.status not in {WorkTaskStatus.ready, WorkTaskStatus.in_progress, WorkTaskStatus.partially_completed, WorkTaskStatus.waiting_previous}:
        raise ValueError("Task must be ready/in_progress/partially_completed")

    task = await _refresh_task_cache(db, task.id)
    # Allow over-plan issuing: no longer restrict by cached_available_quantity

    now = datetime.now(UTC)
    eff_executor = executor_user_id or actor_id
    actor_name = await _get_user_snapshot_name(db, actor_id)
    executor_name = await _get_user_snapshot_name(db, eff_executor)

    movement = Movement(
        product_id=task.product_id,
        task_id=task.id,
        section_plan_line_id=task.section_plan_line_id,
        transfer_id=transfer_id,
        from_section_id=task.section_id,
        to_section_id=task.section_id,
        movement_type=MovementType.issue_to_work,
        quantity=quantity,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        comment=comment,
        created_by=actor_id,
        executor_user_id=eff_executor,
        created_by_user_name=actor_name,
        executor_user_name=executor_name,
        performed_at=performed_at or now,
        accounted_at=accounted_at or now,
    )
    db.add(movement)
    await db.flush()

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
    """Complete (good + defect) quantity on a SectionTask.

    The completion is bounded by `cached_in_work_quantity` — i.e. by what
    the section has issued into work, which itself is bounded by what was
    available in the SPG (`cached_available_quantity`, the sum of the
    initial planned amount for the first stage and any quantity received
    via transfers from the previous SPG).

    Transfer of the completed quantity to the next SPG is a SEPARATE
    process handled by the transfers module; this function does NOT
    initiate or depend on it.
    """
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

    if task.status not in {WorkTaskStatus.in_progress, WorkTaskStatus.partially_completed, WorkTaskStatus.ready, WorkTaskStatus.waiting_previous}:
        raise ValueError("Task must be in progress")

    good_quantity = _to_decimal(good_quantity)
    defect_quantity = _to_decimal(defect_quantity)
    if good_quantity < 0 or defect_quantity < 0:
        raise ValueError("Quantities must be >= 0")
    total = good_quantity + defect_quantity
    _ensure_positive(total, "good_quantity + defect_quantity")

    in_work = task.cached_issued_quantity - task.cached_completed_quantity - task.cached_rejected_quantity
    if total > in_work:
        # Auto-issue the missing quantity for tasks that are still in 'ready'
        # or 'waiting_previous' state with nothing issued yet. This makes the bulk-complete workflow
        # work even when the take-to-work auto-consume did not produce any
        # SPG remainders (e.g. raw stock was never received into SPG).
        if task.status in {WorkTaskStatus.ready, WorkTaskStatus.waiting_previous} and in_work == 0:
            short = total - in_work
            auto_issue_key = (
                f"{idempotency_key}:auto-issue" if idempotency_key else None
            )
            await issue_to_work(
                db,
                task_id=task.id,
                quantity=short,
                actor_id=actor_id,
                comment="Auto-issue from complete (no in-work)",
                source_ref=source_ref,
                idempotency_key=auto_issue_key,
                executor_user_id=executor_user_id,
                performed_at=performed_at,
                accounted_at=accounted_at,
            )
            await db.refresh(task)
            in_work = task.cached_issued_quantity - task.cached_completed_quantity - task.cached_rejected_quantity
        if total > in_work:
            raise ValueError("Complete quantity exceeds quantity in work")

    now = datetime.now(UTC)
    eff_performed = performed_at or now
    eff_accounted = accounted_at or now
    eff_executor = executor_user_id or actor_id
    actor_name = await _get_user_snapshot_name(db, actor_id)
    executor_name = await _get_user_snapshot_name(db, eff_executor)

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
            created_by_user_name=actor_name,
            executor_user_name=executor_name,
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
            created_by_user_name=actor_name,
            executor_user_name=executor_name,
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

    # Cascade auto-issue to next task if it is in the same GHP
    line = await db.get(SectionPlanLine, task.section_plan_line_id)
    if line is not None and good_quantity > 0:
        next_line = await db.scalar(
            select(SectionPlanLine).where(
                SectionPlanLine.plan_position_id == line.plan_position_id,
                SectionPlanLine.sequence == line.sequence + 1,
            )
        )
        if next_line is not None:
            from app.services.shopfloor.common import sections_share_spg
            if await sections_share_spg(db, line.section_id, next_line.section_id):
                # Find or auto-create target task
                next_task = await db.scalar(
                    select(WorkTask).where(
                        WorkTask.section_plan_line_id == next_line.id,
                        WorkTask.status.notin_([WorkTaskStatus.completed, WorkTaskStatus.cancelled]),
                    )
                )
                if not next_task:
                    next_task = WorkTask(
                        section_plan_line_id=next_line.id,
                        section_id=next_line.section_id,
                        product_id=next_line.product_id,
                        route_stage_id=next_line.route_stage_id,
                        planned_quantity=line.planned_quantity,
                        status=WorkTaskStatus.ready,
                        due_date=next_line.due_date,
                    )
                    db.add(next_task)
                    await db.flush()

                if next_task.status == WorkTaskStatus.waiting_previous:
                    next_task.status = WorkTaskStatus.ready
                    await db.flush()

                # Auto-issue the completed quantity to work for next task
                await issue_to_work(
                    db,
                    task_id=next_task.id,
                    quantity=good_quantity,
                    actor_id=actor_id,
                    comment=f"Auto-issued from previous task {task.id} inside same GHP",
                    executor_user_id=executor_user_id,
                    performed_at=performed_at,
                    accounted_at=accounted_at,
                )
                # Consume any other compatible remainders
                await auto_consume_available_remainders(db, next_task, actor_id=actor_id)

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
    stage = await _get_route_stage(db, task.route_stage_id)
    if not stage.is_final:
        raise ValueError("Final release allowed only for final route stage")

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

    eff_executor = executor_user_id or actor_id
    actor_name = await _get_user_snapshot_name(db, actor_id)
    executor_name = await _get_user_snapshot_name(db, eff_executor)
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
        executor_user_id=eff_executor,
        created_by_user_name=actor_name,
        executor_user_name=executor_name,
        performed_at=performed_at or datetime.now(UTC),
        accounted_at=accounted_at or datetime.now(UTC),
    )
    db.add(movement)

    # Create warehouse remainder for finished goods in SPG
    from app.models.spg import SpgSection
    spg_section = await db.scalar(
        select(SpgSection).where(SpgSection.section_id == task.section_id)
    )
    remainder = None
    if spg_section is not None:
        spg_id = spg_section.spg_id

        line = await db.get(SectionPlanLine, task.section_plan_line_id)
        completed_stages = []
        if line is not None:
            from app.models.route import RouteStage
            stages = (await db.execute(
                select(RouteStage)
                .where(RouteStage.route_id == line.route_id)
                .where(RouteStage.sequence <= line.sequence)
                .order_by(RouteStage.sequence)
            )).scalars().all()
            for s in stages:
                completed_stages.append({
                    "section_id": s.section_id,
                    "operation_code": s.operations[0].operation_code if s.operations else None,
                    "operation_name": ", ".join(op.operation_name for op in s.operations) if s.operations else "",
                    "sequence": s.sequence,
                })

        remainder = SpgRemainder(
            product_id=task.product_id,
            spg_id=spg_id,
            route_stage_id=task.route_stage_id,
            section_plan_line_id=task.section_plan_line_id,
            origin_task_id=task.id,
            remainder_quantity=quantity,
            original_issued=quantity,
            completed_stages_json=completed_stages,
            source="final_release",
            created_by=actor_id,
            created_by_user_name=actor_name,
            created_at=performed_at or datetime.now(UTC),
        )
        db.add(remainder)

    await _refresh_task_cache(db, task.id)
    await _refresh_section_plan_line_cache(db, task.section_plan_line_id)

    # Запись лога аудита (финальный выпуск)
    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction, AuditEntityType
    from app.models.section import Section
    from app.models.product import Product
    
    section = await db.get(Section, task.section_id)
    product = await db.get(Product, task.product_id)
    
    await log_action(
        db,
        status="success",
        title="Финальный выпуск",
        message=f"Выполнен финальный выпуск готовой продукции на участке \"{section.name if section else ''}\" (арт. {product.sku if product else ''}). Количество: {quantity} шт.",
        user_id=actor_id,
        section_id=task.section_id,
        section_name=section.name if section else None,
        section_code=section.code if section else None,
        task_ids=[task.id],
        product_sku=product.sku if product else None,
        qty_text=str(quantity),
        comment=comment,
        action=AuditAction.RELEASE,
        entity_type=AuditEntityType.WORK_TASK,
        entity_id=task.id,
        changes={"before": None, "after": {"status": "released", "quantity": str(quantity)}},
    )

    return {"movement_id": movement.id, "remainder_id": remainder.id if remainder else None, "task_id": task.id}

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
        route_stage_id=line.route_stage_id,
        planned_quantity=quantity,
        status=WorkTaskStatus.ready,
        due_date=line.due_date,
    )
    db.add(task)
    await db.flush()
    await auto_consume_available_remainders(db, task, actor_id=actor_id)
    await _refresh_task_cache(db, task.id)
    await _refresh_section_plan_line_cache(db, task.section_plan_line_id)
    return {"task_id": task.id, "status": task.status.value}


async def return_remainder_to_stock(
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
    """Manually return excess quantity from a task to warehouse stock."""
    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")

    existing = await _check_idempotency(db, idempotency_key=idempotency_key, entity_type=Movement)
    if existing is not None:
        task = await _get_task(db, task_id)
        return {"movement_id": existing.id, "task_id": task.id, "idempotent_replay": True}

    task = await _get_task(db, task_id)
    task = await _refresh_task_cache(db, task.id)

    # Calculate available for return: issued - completed - transferred
    available_for_return = task.cached_issued_quantity - task.cached_completed_quantity - task.cached_transferred_quantity
    if available_for_return <= 0:
        raise ValueError("No excess quantity available for return")
    if quantity > available_for_return:
        raise ValueError(f"Return quantity ({quantity}) exceeds available for return ({available_for_return})")

    now = datetime.now(UTC)
    eff_performed = performed_at or now
    eff_accounted = accounted_at or now
    eff_executor = executor_user_id or actor_id

    # Build completed stages info
    line = await db.get(SectionPlanLine, task.section_plan_line_id)
    completed_stages = []
    if line is not None:
        from app.models.route import RouteStage
        stages = await db.execute(
            select(RouteStage)
            .where(RouteStage.route_id == line.route_id)
            .where(RouteStage.sequence <= line.sequence)
            .order_by(RouteStage.sequence)
        )
        for stage in stages.scalars().all():
            completed_stages.append({
                "section_id": stage.section_id,
                "operation_code": stage.operations[0].operation_code if stage.operations else None,
                "operation_name": ", ".join(op.operation_name for op in stage.operations) if stage.operations else "",
                "sequence": stage.sequence,
            })

    # Create remainder record in SPG
    from app.models.spg import SpgSection
    spg_section = await db.scalar(
        select(SpgSection).where(SpgSection.section_id == task.section_id)
    )
    if spg_section is None:
        raise ValueError("Section is not bound to any SPG")
    spg_id = spg_section.spg_id

    actor_name = await _get_user_snapshot_name(db, actor_id)
    executor_name = await _get_user_snapshot_name(db, eff_executor)
    remainder = SpgRemainder(
        product_id=task.product_id,
        spg_id=spg_id,
        route_stage_id=task.route_stage_id,
        section_plan_line_id=task.section_plan_line_id,
        origin_task_id=task.id,
        remainder_quantity=quantity,
        original_issued=quantity,
        completed_stages_json=completed_stages,
        created_by=actor_id,
        created_by_user_name=actor_name,
        created_at=eff_performed,
    )
    db.add(remainder)

    # Create return movement
    movement = Movement(
        product_id=task.product_id,
        task_id=task.id,
        section_plan_line_id=task.section_plan_line_id,
        from_section_id=task.section_id,
        to_section_id=task.section_id,
        movement_type=MovementType.return_to_stock,
        quantity=quantity,
        comment=comment,
        created_by=actor_id,
        idempotency_key=idempotency_key,
        executor_user_id=eff_executor,
        created_by_user_name=actor_name,
        executor_user_name=executor_name,
        performed_at=eff_performed,
        accounted_at=eff_accounted,
    )
    db.add(movement)
    await db.flush()
    await _refresh_task_cache(db, task.id)
    await _refresh_section_plan_line_cache(db, task.section_plan_line_id)
    await trigger_auto_consume_for_spg_tasks(db, spg_id=spg_id, product_id=task.product_id, actor_id=actor_id)
    return {"movement_id": movement.id, "remainder_id": remainder.id, "task_id": task.id}


async def consume_remainder(
    db: AsyncSession,
    *,
    remainder_id: int,
    task_id: int,
    quantity: Decimal,
    actor_id: int,
    comment: str | None = None,
    idempotency_key: str | None = None,
    executor_user_id: int | None = None,
    performed_at: datetime | None = None,
    accounted_at: datetime | None = None,
) -> dict:
    """Use a warehouse remainder for issuing to work on a task."""
    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")

    existing = await _check_idempotency(db, idempotency_key=idempotency_key, entity_type=Movement)
    if existing is not None:
        task = await _get_task(db, task_id)
        return {"movement_id": existing.id, "task_id": task.id, "idempotent_replay": True}

    remainder = await db.get(SpgRemainder, remainder_id)
    if remainder is None:
        raise ValueError("Remainder not found")
    if remainder.consumed_at is not None:
        raise ValueError("Remainder already consumed")

    task = await _get_task(db, task_id)
    if task.status not in {WorkTaskStatus.ready, WorkTaskStatus.in_progress, WorkTaskStatus.partially_completed, WorkTaskStatus.waiting_previous}:
        raise ValueError("Task must be ready/in_progress/partially_completed")

    now = datetime.now(UTC)
    eff_performed = performed_at or now
    eff_accounted = accounted_at or now
    eff_executor = executor_user_id or actor_id

    # Create issue movement
    actor_name = await _get_user_snapshot_name(db, actor_id)
    executor_name = await _get_user_snapshot_name(db, eff_executor)
    movement = Movement(
        product_id=task.product_id,
        task_id=task.id,
        section_plan_line_id=task.section_plan_line_id,
        from_section_id=task.section_id,
        to_section_id=task.section_id,
        movement_type=MovementType.issue_to_work,
        quantity=quantity,
        source_ref=f"remainder:{remainder_id}",
        comment=comment,
        created_by=actor_id,
        idempotency_key=idempotency_key,
        executor_user_id=eff_executor,
        created_by_user_name=actor_name,
        executor_user_name=executor_name,
        performed_at=eff_performed,
        accounted_at=eff_accounted,
    )
    db.add(movement)

    # Update remainder (allow negative when consuming more than available)
    remainder.remainder_quantity -= quantity
    if remainder.remainder_quantity == 0:
        remainder.consumed_at = now
        remainder.consumed_by_task_id = task.id

    task.status = WorkTaskStatus.in_progress
    await db.flush()
    await _refresh_task_cache(db, task.id)
    await _refresh_section_plan_line_cache(db, task.section_plan_line_id)
    return {"movement_id": movement.id, "remainder_id": remainder.id, "task_id": task.id}


async def get_section_spg_id(db: AsyncSession, section_id: int) -> int | None:
    from app.models.spg import SpgSection
    return await db.scalar(select(SpgSection.spg_id).where(SpgSection.section_id == section_id))


async def auto_consume_available_remainders(db: AsyncSession, task: WorkTask, actor_id: int) -> Decimal:
    """Find and consume compatible remainders for this task, issuing them to work."""
    if task.status not in {WorkTaskStatus.ready, WorkTaskStatus.in_progress, WorkTaskStatus.partially_completed}:
        return Decimal("0")

    line = await db.get(SectionPlanLine, task.section_plan_line_id)
    if not line:
        return Decimal("0")

    spg_id = await get_section_spg_id(db, task.section_id)
    if not spg_id:
        return Decimal("0")

    # Get all active remainders for this product and SPG, ordered FIFO
    active_remainders = (
        await db.execute(
            select(SpgRemainder)
            .where(
                SpgRemainder.product_id == task.product_id,
                SpgRemainder.spg_id == spg_id,
                SpgRemainder.remainder_quantity > 0,
                SpgRemainder.consumed_at.is_(None),
            )
            .order_by(SpgRemainder.created_at.asc(), SpgRemainder.id.asc())
        )
    ).scalars().all()

    # We also need the full route stages for this plan position to determine sequence ordering
    from app.models.route import RouteStage
    route_stages = (
        await db.execute(
            select(RouteStage)
            .where(RouteStage.route_id == line.route_id)
            .order_by(RouteStage.sequence.asc())
        )
    ).scalars().all()
    route_sequences = [s.sequence for s in route_stages]

    total_consumed = Decimal("0")

    for rem in active_remainders:
        # Check compatibility:
        # 1. If reserved, it must be for this plan position
        if rem.reserved_for_plan_position_id is not None:
            if rem.reserved_for_plan_position_id != line.plan_position_id:
                continue

        # 2. Sequence compatibility:
        # We find max_seq of completed stages
        stages_json = rem.completed_stages_json or []
        if stages_json:
            max_seq = max((s.get("sequence", 0) for s in stages_json), default=0)
            # The remainder belongs to this task's stage if line.sequence is the first stage in the route after max_seq
            next_stages_in_route = [seq for seq in route_sequences if seq > max_seq]
            if not next_stages_in_route:
                continue
            expected_seq = next_stages_in_route[0]
        else:
            # For manual remainders (empty stages_json), they are compatible with the first stage of this SPG in the route
            from app.models.spg import SpgSection
            spg_section_ids = await db.scalars(
                select(SpgSection.section_id).where(SpgSection.spg_id == spg_id)
            )
            spg_section_ids = list(spg_section_ids)
            
            spg_stages_in_route = (
                await db.execute(
                    select(RouteStage.sequence)
                    .where(
                        RouteStage.route_id == line.route_id,
                        RouteStage.section_id.in_(spg_section_ids),
                    )
                    .order_by(RouteStage.sequence.asc())
                )
            ).scalars().all()
            if not spg_stages_in_route:
                continue
            expected_seq = spg_stages_in_route[0]

        if line.sequence != expected_seq:
            continue

        # If we got here, this remainder is compatible and should be consumed for this task!
        qty_to_consume = rem.remainder_quantity
        if qty_to_consume > 0:
            await consume_remainder(
                db,
                remainder_id=rem.id,
                task_id=task.id,
                quantity=qty_to_consume,
                actor_id=actor_id,
                comment=f"Auto-consumed remainder {rem.id} on task ready/in_progress",
            )
            total_consumed += qty_to_consume

    return total_consumed


async def trigger_auto_consume_for_spg_tasks(db: AsyncSession, spg_id: int, product_id: int, actor_id: int) -> None:
    """Find all active tasks in this SPG for this product and trigger remainder auto-consumption on them."""
    from app.models.spg import SpgSection
    section_ids = await db.scalars(
        select(SpgSection.section_id).where(SpgSection.spg_id == spg_id)
    )
    section_ids = list(section_ids)
    if not section_ids:
        return

    tasks = (
        await db.execute(
            select(WorkTask)
            .where(
                WorkTask.product_id == product_id,
                WorkTask.section_id.in_(section_ids),
                WorkTask.status.in_([WorkTaskStatus.ready, WorkTaskStatus.in_progress, WorkTaskStatus.partially_completed]),
            )
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .order_by(SectionPlanLine.sequence.asc(), WorkTask.id.asc())
        )
    ).scalars().all()

    for task in tasks:
        await auto_consume_available_remainders(db, task, actor_id=actor_id)



