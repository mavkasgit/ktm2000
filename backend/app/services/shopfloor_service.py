from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment, AttachmentLink
from app.models.defect import (
    Defect,
    DefectDecision,
    DefectDecisionType,
    DefectItem,
    DefectStatus,
    DefectType,
    TransferDiscrepancyDefectItem,
)
from app.models.entity_comment import EntityComment, EntityType
from app.models.internal_plan import SectionPlanLine
from app.models.movement import Movement, MovementType
from app.models.production_plan import PlanPosition, PlanPositionStatus
from app.models.rework_task import ReworkTask, ReworkTaskStatus
from app.models.route import RouteStep
from app.models.section import Section
from app.models.transfer import Transfer, TransferDiscrepancy, TransferDiscrepancyStatus, TransferStatus
from app.models.work_task import WorkTask, WorkTaskStatus


def _to_decimal(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value))


def _ensure_positive(value: Decimal, field_name: str) -> None:
    if value <= 0:
        raise ValueError(f"{field_name} must be > 0")


async def _get_task(db: AsyncSession, task_id: int) -> WorkTask:
    task = await db.get(WorkTask, task_id)
    if task is None:
        raise ValueError("Task not found")
    return task


async def _get_transfer(db: AsyncSession, transfer_id: int) -> Transfer:
    transfer = await db.get(Transfer, transfer_id)
    if transfer is None:
        raise ValueError("Transfer not found")
    return transfer


async def _get_defect(db: AsyncSession, defect_id: int) -> Defect:
    defect = await db.get(Defect, defect_id)
    if defect is None:
        raise ValueError("Defect not found")
    return defect


async def _check_idempotency(
    db: AsyncSession,
    *,
    idempotency_key: str | None,
    entity_type: type,
) -> object | None:
    """Return existing entity if idempotency_key was already used, else None."""
    if not idempotency_key:
        return None
    return await db.scalar(
        select(entity_type).where(entity_type.idempotency_key == idempotency_key)
    )


async def _get_route_step(db: AsyncSession, route_step_id: int) -> RouteStep:
    step = await db.get(RouteStep, route_step_id)
    if step is None:
        raise ValueError("Route step not found")
    return step


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

    available = task.planned_quantity + received - issued
    if available < 0:
        available = Decimal("0")

    remaining = task.planned_quantity - completed - rejected
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


def _transfer_no() -> str:
    return f"TR-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"


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

    available = task.planned_quantity + task.cached_received_quantity - task.cached_issued_quantity
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


async def transfer_send(
    db: AsyncSession,
    *,
    from_task_id: int,
    to_task_id: int,
    quantity: Decimal,
    actor_id: int,
    comment: str | None = None,
    idempotency_key: str | None = None,
    executor_user_id: int | None = None,
    performed_at: datetime | None = None,
    accounted_at: datetime | None = None,
) -> dict:
    if idempotency_key:
        existing = await _check_idempotency(db, idempotency_key=idempotency_key, entity_type=Transfer)
        if existing is not None:
            return {"transfer_id": existing.id, "transfer_no": existing.transfer_no, "status": existing.status.value, "idempotent_replay": True}

    from_task = await _get_task(db, from_task_id)
    to_task = await _get_task(db, to_task_id)
    if from_task.product_id != to_task.product_id:
        raise ValueError("Transfer tasks must have same product")

    from_line = await db.get(SectionPlanLine, from_task.section_plan_line_id)
    to_line = await db.get(SectionPlanLine, to_task.section_plan_line_id)
    if from_line is None or to_line is None or from_line.plan_position_id != to_line.plan_position_id:
        raise ValueError("Transfer tasks must belong to same plan position")

    from_step = await _get_route_step(db, from_task.route_step_id)
    to_step = await _get_route_step(db, to_task.route_step_id)
    if to_step.sequence <= from_step.sequence:
        raise ValueError("Transfer target must be next route step")

    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")
    transferable = from_task.cached_completed_quantity - from_task.cached_transferred_quantity
    if quantity > transferable:
        raise ValueError("Transfer quantity exceeds transferable amount")

    transfer = Transfer(
        transfer_no=_transfer_no(),
        from_task_id=from_task.id,
        to_task_id=to_task.id,
        from_section_id=from_task.section_id,
        to_section_id=to_task.section_id,
        product_id=from_task.product_id,
        sent_quantity=quantity,
        status=TransferStatus.sent,
        sent_by=actor_id,
        sent_at=datetime.now(UTC),
        comment=comment,
        idempotency_key=idempotency_key,
    )
    db.add(transfer)
    await db.flush()

    movement = Movement(
        product_id=from_task.product_id,
        task_id=from_task.id,
        section_plan_line_id=from_task.section_plan_line_id,
        transfer_id=transfer.id,
        from_section_id=from_task.section_id,
        to_section_id=to_task.section_id,
        movement_type=MovementType.transfer_send,
        quantity=quantity,
        comment=comment,
        created_by=actor_id,
        idempotency_key=f"{idempotency_key}:send" if idempotency_key else None,
        executor_user_id=executor_user_id or actor_id,
        performed_at=performed_at or datetime.now(UTC),
        accounted_at=accounted_at or datetime.now(UTC),
    )
    db.add(movement)

    await _refresh_task_cache(db, from_task.id)
    await _refresh_section_plan_line_cache(db, from_task.section_plan_line_id)
    return {"transfer_id": transfer.id, "transfer_no": transfer.transfer_no, "status": transfer.status.value}


async def transfer_receive(
    db: AsyncSession,
    *,
    transfer_id: int,
    accepted_quantity: Decimal,
    rejected_quantity: Decimal,
    actor_id: int,
    reason: str | None = None,
    comment: str | None = None,
    idempotency_key: str | None = None,
    executor_user_id: int | None = None,
    performed_at: datetime | None = None,
    accounted_at: datetime | None = None,
) -> dict:
    transfer = await _get_transfer(db, transfer_id)
    if transfer.status not in {TransferStatus.sent, TransferStatus.partially_accepted}:
        raise ValueError("Transfer must be sent")

    accepted_quantity = _to_decimal(accepted_quantity)
    rejected_quantity = _to_decimal(rejected_quantity)
    if accepted_quantity < 0 or rejected_quantity < 0:
        raise ValueError("accepted/rejected must be >= 0")
    if accepted_quantity + rejected_quantity <= 0:
        raise ValueError("accepted + rejected must be > 0")
    if accepted_quantity + rejected_quantity > transfer.sent_quantity:
        raise ValueError("accepted + rejected exceeds sent quantity")

    transfer.accepted_quantity = accepted_quantity
    transfer.rejected_quantity = rejected_quantity
    transfer.accepted_by = actor_id
    transfer.accepted_at = datetime.now(UTC)
    transfer.comment = comment or transfer.comment
    if accepted_quantity == transfer.sent_quantity:
        transfer.status = TransferStatus.accepted
    elif accepted_quantity > 0:
        transfer.status = TransferStatus.partially_accepted
    else:
        transfer.status = TransferStatus.rejected

    to_task = await _get_task(db, transfer.to_task_id)
    if accepted_quantity > 0:
        movement = Movement(
            product_id=transfer.product_id,
            task_id=to_task.id,
            section_plan_line_id=to_task.section_plan_line_id,
            transfer_id=transfer.id,
            from_section_id=transfer.from_section_id,
            to_section_id=transfer.to_section_id,
            movement_type=MovementType.transfer_receive,
            quantity=accepted_quantity,
            reason=reason,
            comment=comment,
            created_by=actor_id,
            idempotency_key=f"{idempotency_key}:receive" if idempotency_key else None,
            executor_user_id=executor_user_id or actor_id,
            performed_at=performed_at or datetime.now(UTC),
            accounted_at=accounted_at or datetime.now(UTC),
        )
        db.add(movement)

    discrepancy_id: int | None = None
    if rejected_quantity > 0:
        discrepancy = TransferDiscrepancy(
            transfer_id=transfer.id,
            discrepancy_quantity=rejected_quantity,
            resolved_quantity=Decimal("0"),
            unresolved_quantity=rejected_quantity,
            status=TransferDiscrepancyStatus.open,
            reason=reason,
            comment=comment,
            created_by=actor_id,
        )
        db.add(discrepancy)
        await db.flush()
        discrepancy_id = discrepancy.id

    if accepted_quantity > 0 and to_task.status == WorkTaskStatus.waiting_previous:
        to_task.status = WorkTaskStatus.ready

    await _refresh_task_cache(db, to_task.id)
    await _refresh_section_plan_line_cache(db, to_task.section_plan_line_id)
    return {"transfer_id": transfer.id, "status": transfer.status.value, "discrepancy_id": discrepancy_id}


async def resolve_transfer_discrepancy_link(
    db: AsyncSession,
    *,
    transfer_id: int,
    discrepancy_id: int,
    defect_item_id: int,
    quantity: Decimal,
    actor_id: int,
    comment: str | None = None,
) -> dict:
    transfer = await _get_transfer(db, transfer_id)
    discrepancy = await db.get(TransferDiscrepancy, discrepancy_id)
    if discrepancy is None or discrepancy.transfer_id != transfer.id:
        raise ValueError("Transfer discrepancy not found")
    defect_item = await db.get(DefectItem, defect_item_id)
    if defect_item is None:
        raise ValueError("Defect item not found")

    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")
    if quantity > discrepancy.unresolved_quantity:
        raise ValueError("Resolve quantity exceeds unresolved discrepancy")

    link = TransferDiscrepancyDefectItem(
        transfer_discrepancy_id=discrepancy.id,
        defect_item_id=defect_item.id,
        quantity=quantity,
        comment=comment,
        created_by=actor_id,
    )
    db.add(link)

    discrepancy.resolved_quantity = discrepancy.resolved_quantity + quantity
    discrepancy.unresolved_quantity = discrepancy.unresolved_quantity - quantity
    if discrepancy.unresolved_quantity == 0:
        discrepancy.status = TransferDiscrepancyStatus.resolved
        discrepancy.resolved_at = datetime.now(UTC)
    else:
        discrepancy.status = TransferDiscrepancyStatus.partially_resolved

    return {
        "discrepancy_id": discrepancy.id,
        "status": discrepancy.status.value,
        "resolved_quantity": str(discrepancy.resolved_quantity),
        "unresolved_quantity": str(discrepancy.unresolved_quantity),
    }


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


async def create_defect(
    db: AsyncSession,
    *,
    task_id: int,
    quantity: Decimal,
    actor_id: int,
    reason: str | None = None,
    comment: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    if idempotency_key:
        existing = await _check_idempotency(db, idempotency_key=idempotency_key, entity_type=Defect)
        if existing is not None:
            return {"defect_id": existing.id, "item_id": None, "idempotent_replay": True}

    task = await _get_task(db, task_id)
    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")

    defect = Defect(
        product_id=task.product_id,
        section_id=task.section_id,
        task_id=task.id,
        status=DefectStatus.decision_required,
        comment=comment,
        created_by=actor_id,
        idempotency_key=idempotency_key,
    )
    db.add(defect)
    await db.flush()
    item = DefectItem(
        defect_id=defect.id,
        quantity=quantity,
        defect_type_code_snapshot=reason,
        defect_type_name_snapshot=reason,
        description=comment,
        created_by=actor_id,
    )
    db.add(item)
    return {"defect_id": defect.id, "item_id": item.id}


async def add_defect_item(
    db: AsyncSession,
    *,
    defect_id: int,
    quantity: Decimal,
    actor_id: int,
    defect_type_id: int | None = None,
    subtype_code: str | None = None,
    reason_code: str | None = None,
    description: str | None = None,
) -> dict:
    defect = await _get_defect(db, defect_id)
    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")
    defect_type = await db.get(DefectType, defect_type_id) if defect_type_id else None

    item = DefectItem(
        defect_id=defect.id,
        defect_type_id=defect_type_id,
        defect_type_code_snapshot=defect_type.code if defect_type else None,
        defect_type_name_snapshot=defect_type.name if defect_type else None,
        subtype_code=subtype_code,
        reason_code=reason_code,
        quantity=quantity,
        description=description,
        created_by=actor_id,
    )
    db.add(item)
    await db.flush()
    return {"defect_item_id": item.id}


async def defect_decide(
    db: AsyncSession,
    *,
    defect_id: int,
    decision_type: DefectDecisionType,
    quantity: Decimal,
    actor_id: int,
    target_section_id: int | None = None,
    reason: str | None = None,
    comment: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    defect = await _get_defect(db, defect_id)
    task = await _get_task(db, defect.task_id)

    if idempotency_key:
        existing = await _check_idempotency(db, idempotency_key=idempotency_key, entity_type=DefectDecision)
        if existing is not None:
            # Find associated rework task if decision type was rework
            rework = await db.scalar(
                select(ReworkTask).where(ReworkTask.defect_id == defect.id).order_by(ReworkTask.id)
            )
            return {
                "defect_id": defect.id,
                "decision_id": existing.id,
                "defect_status": defect.status.value,
                "rework_task_id": rework.id if rework else None,
                "idempotent_replay": True,
            }

    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")

    decision = DefectDecision(
        defect_id=defect.id,
        decision_type=decision_type,
        quantity=quantity,
        target_section_id=target_section_id,
        reason=reason,
        comment=comment,
        idempotency_key=idempotency_key,
        decided_by=actor_id,
    )
    db.add(decision)
    await db.flush()

    rework_task_id: int | None = None
    if decision_type == DefectDecisionType.scrap:
        movement = Movement(
            product_id=task.product_id,
            task_id=task.id,
            section_plan_line_id=task.section_plan_line_id,
            from_section_id=task.section_id,
            to_section_id=task.section_id,
            movement_type=MovementType.scrap,
            quantity=quantity,
            reason=reason,
            comment=comment,
            created_by=actor_id,
        )
        db.add(movement)
        defect.status = DefectStatus.scrapped
    elif decision_type in {DefectDecisionType.rework_current, DefectDecisionType.return_previous}:
        rework = ReworkTask(
            defect_id=defect.id,
            source_task_id=task.id,
            section_id=target_section_id or task.section_id,
            product_id=task.product_id,
            quantity=quantity,
            status=ReworkTaskStatus.open,
            created_by=actor_id,
        )
        db.add(rework)
        await db.flush()
        rework_task_id = rework.id
        defect.status = DefectStatus.rework_task_created
    elif decision_type == DefectDecisionType.accept_with_deviation:
        defect.status = DefectStatus.accepted_with_deviation
    else:
        defect.status = DefectStatus.decision_required

    await _refresh_task_cache(db, task.id)
    await _refresh_section_plan_line_cache(db, task.section_plan_line_id)
    return {"defect_id": defect.id, "decision_id": decision.id, "defect_status": defect.status.value, "rework_task_id": rework_task_id}


async def rework_create(
    db: AsyncSession,
    *,
    defect_id: int,
    source_task_id: int,
    section_id: int,
    quantity: Decimal,
    actor_id: int,
    idempotency_key: str | None = None,
) -> dict:
    defect = await _get_defect(db, defect_id)
    source_task = await _get_task(db, source_task_id)

    if idempotency_key:
        existing = await _check_idempotency(db, idempotency_key=idempotency_key, entity_type=ReworkTask)
        if existing is not None:
            return {"rework_task_id": existing.id, "idempotent_replay": True}

    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")
    rework = ReworkTask(
        defect_id=defect.id,
        source_task_id=source_task.id,
        section_id=section_id,
        product_id=source_task.product_id,
        quantity=quantity,
        status=ReworkTaskStatus.open,
        created_by=actor_id,
        idempotency_key=idempotency_key,
    )
    db.add(rework)
    await db.flush()
    defect.status = DefectStatus.rework_task_created
    return {"rework_task_id": rework.id}


async def create_comment(
    db: AsyncSession,
    *,
    entity_type: EntityType,
    entity_id: int,
    body: str,
    actor_id: int,
    comment_type: str = "note",
    is_internal: bool = False,
    idempotency_key: str | None = None,
) -> dict:
    if not body.strip():
        raise ValueError("Comment body must not be empty")
    comment = EntityComment(
        entity_type=entity_type,
        entity_id=entity_id,
        comment_type=comment_type,
        body=body,
        is_internal=is_internal,
        idempotency_key=idempotency_key,
        author_id=actor_id,
    )
    db.add(comment)
    await db.flush()
    return {"comment_id": comment.id}


async def create_attachment(
    db: AsyncSession,
    *,
    original_filename: str,
    stored_path: str,
    size_bytes: int,
    actor_id: int,
    content_type: str | None = None,
    file_sha256: str | None = None,
    metadata_json: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    if not original_filename.strip():
        raise ValueError("original_filename is required")
    if size_bytes <= 0:
        raise ValueError("size_bytes must be > 0")
    attachment = Attachment(
        original_filename=original_filename,
        stored_path=stored_path,
        content_type=content_type,
        size_bytes=size_bytes,
        file_sha256=file_sha256,
        metadata_json=metadata_json or {},
        idempotency_key=idempotency_key,
        created_by=actor_id,
    )
    db.add(attachment)
    await db.flush()
    return {"attachment_id": attachment.id}


async def link_attachment(
    db: AsyncSession,
    *,
    attachment_id: int,
    entity_type: EntityType,
    entity_id: int,
    actor_id: int,
    caption: str | None = None,
) -> dict:
    attachment = await db.get(Attachment, attachment_id)
    if attachment is None:
        raise ValueError("Attachment not found")
    link = AttachmentLink(
        attachment_id=attachment.id,
        entity_type=entity_type,
        entity_id=entity_id,
        caption=caption,
        created_by=actor_id,
    )
    db.add(link)
    await db.flush()
    return {"attachment_link_id": link.id}


async def get_task_details(db: AsyncSession, task_id: int) -> dict:
    task = await _get_task(db, task_id)
    step = await db.get(RouteStep, task.route_step_id)
    movements = (
        await db.execute(select(Movement).where(Movement.task_id == task.id).order_by(Movement.created_at, Movement.id))
    ).scalars().all()
    return {
        "id": task.id,
        "status": task.status.value,
        "planned_quantity": str(task.planned_quantity),
        "cache": {
            "available_quantity": str(task.cached_available_quantity),
            "issued_quantity": str(task.cached_issued_quantity),
            "in_work_quantity": str(task.cached_in_work_quantity),
            "completed_quantity": str(task.cached_completed_quantity),
            "transferred_quantity": str(task.cached_transferred_quantity),
            "received_quantity": str(task.cached_received_quantity),
            "rejected_quantity": str(task.cached_rejected_quantity),
            "remaining_quantity": str(task.cached_remaining_quantity),
        },
        "route_step": {
            "id": step.id if step else None,
            "sequence": step.sequence if step else None,
            "operation_code": step.operation_code if step else None,
            "operation_name": step.operation_name if step else None,
            "is_final": step.is_final if step else None,
        },
        "movements": [
            {
                "id": m.id,
                "movement_type": m.movement_type.value,
                "quantity": str(m.quantity),
                "from_section_id": m.from_section_id,
                "to_section_id": m.to_section_id,
                "transfer_id": m.transfer_id,
                "reason": m.reason,
                "comment": m.comment,
                "created_by": m.created_by,
                "executor_user_id": m.executor_user_id,
                "performed_at": m.performed_at.isoformat() if m.performed_at else None,
                "accounted_at": m.accounted_at.isoformat() if m.accounted_at else None,
                "created_at": m.created_at.isoformat(),
            }
            for m in movements
        ],
    }


async def get_transfer_details(db: AsyncSession, transfer_id: int) -> dict:
    transfer = await _get_transfer(db, transfer_id)
    discrepancies = (
        await db.execute(
            select(TransferDiscrepancy).where(TransferDiscrepancy.transfer_id == transfer.id).order_by(TransferDiscrepancy.id)
        )
    ).scalars().all()
    result_discrepancies = []
    for d in discrepancies:
        links = (
            await db.execute(
                select(TransferDiscrepancyDefectItem, DefectItem)
                .join(DefectItem, DefectItem.id == TransferDiscrepancyDefectItem.defect_item_id)
                .where(TransferDiscrepancyDefectItem.transfer_discrepancy_id == d.id)
            )
        ).all()
        result_discrepancies.append(
            {
                "id": d.id,
                "discrepancy_quantity": str(d.discrepancy_quantity),
                "resolved_quantity": str(d.resolved_quantity),
                "unresolved_quantity": str(d.unresolved_quantity),
                "status": d.status.value,
                "reason": d.reason,
                "comment": d.comment,
                "links": [
                    {
                        "id": link.id,
                        "defect_item_id": item.id,
                        "defect_id": item.defect_id,
                        "quantity": str(link.quantity),
                    }
                    for link, item in links
                ],
            }
        )
    return {
        "id": transfer.id,
        "transfer_no": transfer.transfer_no,
        "status": transfer.status.value,
        "from_task_id": transfer.from_task_id,
        "to_task_id": transfer.to_task_id,
        "sent_quantity": str(transfer.sent_quantity),
        "accepted_quantity": str(transfer.accepted_quantity) if transfer.accepted_quantity is not None else None,
        "rejected_quantity": str(transfer.rejected_quantity) if transfer.rejected_quantity is not None else None,
        "discrepancies": result_discrepancies,
    }


async def get_defect_details(db: AsyncSession, defect_id: int) -> dict:
    defect = await _get_defect(db, defect_id)
    items = (
        await db.execute(select(DefectItem).where(DefectItem.defect_id == defect.id).order_by(DefectItem.id))
    ).scalars().all()
    decisions = (
        await db.execute(select(DefectDecision).where(DefectDecision.defect_id == defect.id).order_by(DefectDecision.id))
    ).scalars().all()
    comments = (
        await db.execute(
            select(EntityComment)
            .where(EntityComment.entity_type == EntityType.defect, EntityComment.entity_id == defect.id)
            .order_by(EntityComment.id)
        )
    ).scalars().all()
    attachments = (
        await db.execute(
            select(AttachmentLink, Attachment)
            .join(Attachment, Attachment.id == AttachmentLink.attachment_id)
            .where(AttachmentLink.entity_type == EntityType.defect, AttachmentLink.entity_id == defect.id)
            .order_by(AttachmentLink.id)
        )
    ).all()
    return {
        "id": defect.id,
        "status": defect.status.value,
        "product_id": defect.product_id,
        "section_id": defect.section_id,
        "task_id": defect.task_id,
        "responsible_section_id": defect.responsible_section_id,
        "comment": defect.comment,
        "items": [
            {
                "id": item.id,
                "defect_type_id": item.defect_type_id,
                "defect_type_code_snapshot": item.defect_type_code_snapshot,
                "defect_type_name_snapshot": item.defect_type_name_snapshot,
                "subtype_code": item.subtype_code,
                "reason_code": item.reason_code,
                "quantity": str(item.quantity),
                "description": item.description,
            }
            for item in items
        ],
        "decisions": [
            {
                "id": decision.id,
                "decision_type": decision.decision_type.value,
                "quantity": str(decision.quantity),
                "target_section_id": decision.target_section_id,
                "reason": decision.reason,
                "comment": decision.comment,
                "decided_by": decision.decided_by,
                "decided_at": decision.decided_at.isoformat(),
            }
            for decision in decisions
        ],
        "comments": [
            {
                "id": comment.id,
                "body": comment.body,
                "comment_type": comment.comment_type,
                "is_internal": comment.is_internal,
                "author_id": comment.author_id,
                "created_at": comment.created_at.isoformat(),
            }
            for comment in comments
        ],
        "attachments": [
            {
                "attachment_link_id": link.id,
                "attachment_id": attachment.id,
                "original_filename": attachment.original_filename,
                "stored_path": attachment.stored_path,
                "caption": link.caption,
            }
            for link, attachment in attachments
        ],
    }


async def get_route_stage_aggregates_for_plan_position(db: AsyncSession, plan_position_id: int) -> dict:
    lines = (
        await db.execute(
            select(SectionPlanLine, RouteStep)
            .join(RouteStep, RouteStep.id == SectionPlanLine.route_step_id)
            .where(SectionPlanLine.plan_position_id == plan_position_id)
            .order_by(SectionPlanLine.sequence)
        )
    ).all()
    if not lines:
        return {"plan_position_id": plan_position_id, "stages": []}

    return {
        "plan_position_id": plan_position_id,
        "stages": [
            {
                "section_plan_line_id": line.id,
                "route_step_id": line.route_step_id,
                "sequence": line.sequence,
                "operation_code": step.operation_code,
                "operation_name": step.operation_name,
                "is_final": step.is_final,
                "planned_quantity": str(line.planned_quantity),
                "available_quantity": str(line.cached_available_quantity),
                "issued_quantity": str(line.cached_issued_quantity),
                "completed_quantity": str(line.cached_completed_quantity),
                "transferred_quantity": str(line.cached_transferred_quantity),
                "received_quantity": str(line.cached_received_quantity),
                "rejected_quantity": str(line.cached_rejected_quantity),
                "remaining_quantity": str(line.cached_remaining_quantity),
            }
            for line, step in lines
        ],
    }


async def get_rework_details(db: AsyncSession, rework_task_id: int) -> dict:
    rework = await db.get(ReworkTask, rework_task_id)
    if rework is None:
        raise ValueError("Rework task not found")

    decisions = (
        await db.execute(
            select(DefectDecision).where(
                DefectDecision.defect_id == rework.defect_id
            ).order_by(DefectDecision.id)
        )
    ).scalars().all()

    return {
        "id": rework.id,
        "defect_id": rework.defect_id,
        "source_task_id": rework.source_task_id,
        "section_id": rework.section_id,
        "product_id": rework.product_id,
        "quantity": str(rework.quantity),
        "status": rework.status.value,
        "created_at": rework.created_at.isoformat(),
        "closed_at": rework.closed_at.isoformat() if rework.closed_at else None,
        "defect_decisions": [
            {
                "id": d.id,
                "decision_type": d.decision_type.value,
                "quantity": str(d.quantity),
                "decided_at": d.decided_at.isoformat(),
            }
            for d in decisions
        ],
    }


async def list_entity_comments(
    db: AsyncSession,
    entity_type: EntityType,
    entity_id: int,
) -> list[dict]:
    comments = (
        await db.execute(
            select(EntityComment)
            .where(EntityComment.entity_type == entity_type, EntityComment.entity_id == entity_id)
            .order_by(EntityComment.created_at, EntityComment.id)
        )
    ).scalars().all()
    return [
        {
            "id": c.id,
            "comment_type": c.comment_type,
            "body": c.body,
            "is_internal": c.is_internal,
            "author_id": c.author_id,
            "created_at": c.created_at.isoformat(),
        }
        for c in comments
    ]


async def list_entity_attachments(
    db: AsyncSession,
    entity_type: EntityType,
    entity_id: int,
) -> list[dict]:
    links = (
        await db.execute(
            select(AttachmentLink, Attachment)
            .join(Attachment, Attachment.id == AttachmentLink.attachment_id)
            .where(AttachmentLink.entity_type == entity_type, AttachmentLink.entity_id == entity_id)
            .order_by(AttachmentLink.created_at, AttachmentLink.id)
        )
    ).all()
    return [
        {
            "attachment_link_id": link.id,
            "attachment_id": attachment.id,
            "original_filename": attachment.original_filename,
            "stored_path": attachment.stored_path,
            "content_type": attachment.content_type,
            "size_bytes": attachment.size_bytes,
            "caption": link.caption,
            "created_at": link.created_at.isoformat(),
        }
        for link, attachment in links
    ]


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
    return {"task_id": task.id, "status": task.status.value}


async def get_section_board(
    db: AsyncSession,
    *,
    section_id: int,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    status: str | None = None,
) -> dict:
    """Return the section board: tasks + previous stage progress."""
    query = select(
        WorkTask,
        SectionPlanLine,
        RouteStep,
    ).join(
        SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id,
    ).join(
        RouteStep, WorkTask.route_step_id == RouteStep.id,
    ).where(
        WorkTask.section_id == section_id,
    )

    if status:
        query = query.where(WorkTask.status == status)
    if date_from:
        query = query.where(WorkTask.created_at >= date_from)
    if date_to:
        query = query.where(WorkTask.created_at <= date_to)

    query = query.order_by(SectionPlanLine.sequence, WorkTask.id)

    rows = (await db.execute(query)).all()

    tasks_data = []
    for task, line, step in rows:
        # Find previous route step
        prev_step = await db.scalar(
            select(RouteStep).where(
                RouteStep.route_id == line.route_id,
                RouteStep.sequence == step.sequence - 1,
            )
        )

        prev_stage_info = None
        if prev_step:
            prev_line = await db.scalar(
                select(SectionPlanLine).where(
                    SectionPlanLine.plan_position_id == line.plan_position_id,
                    SectionPlanLine.route_step_id == prev_step.id,
                )
            )
            if prev_line:
                prev_stage_info = {
                    "section_plan_line_id": prev_line.id,
                    "completed_quantity": str(prev_line.cached_completed_quantity),
                    "transferred_quantity": str(prev_line.cached_transferred_quantity),
                    "received_quantity": str(prev_line.cached_received_quantity),
                }

        next_task_id: int | None = None
        next_task_status: str | None = None
        next_operation_name: str | None = None
        next_line = await db.scalar(
            select(SectionPlanLine).where(
                SectionPlanLine.plan_position_id == line.plan_position_id,
                SectionPlanLine.sequence == line.sequence + 1,
            )
        )
        if next_line:
            next_task = await db.scalar(
                select(WorkTask)
                .where(WorkTask.section_plan_line_id == next_line.id)
                .order_by(WorkTask.id.desc())
            )
            if next_task:
                next_task_id = next_task.id
                next_task_status = next_task.status.value
            next_step = await db.get(RouteStep, next_line.route_step_id)
            if next_step:
                next_operation_name = next_step.operation_name

        tasks_data.append({
            "id": task.id,
            "product_id": task.product_id,
            "section_plan_line_id": line.id,
            "plan_position_id": line.plan_position_id,
            "route_step_id": step.id,
            "sequence": step.sequence,
            "operation_code": step.operation_code,
            "operation_name": step.operation_name,
            "planned_quantity": str(task.planned_quantity),
            "status": task.status.value,
            "cache": {
                "available_quantity": str(task.cached_available_quantity),
                "issued_quantity": str(task.cached_issued_quantity),
                "in_work_quantity": str(task.cached_in_work_quantity),
                "completed_quantity": str(task.cached_completed_quantity),
                "transferred_quantity": str(task.cached_transferred_quantity),
                "received_quantity": str(task.cached_received_quantity),
                "rejected_quantity": str(task.cached_rejected_quantity),
                "remaining_quantity": str(task.cached_remaining_quantity),
            },
            "previous_stage": prev_stage_info,
            "next_task_id": next_task_id,
            "next_task_status": next_task_status,
            "next_operation_name": next_operation_name,
        })

    return {"section_id": section_id, "tasks": tasks_data}


async def get_sections_summary(db: AsyncSession) -> dict:
    """Return section counters for quick top-level switching tiles."""
    status_counts = (
        await db.execute(
            select(
                WorkTask.section_id.label("section_id"),
                func.count(WorkTask.id).label("total_tasks"),
                func.sum(case((WorkTask.status == WorkTaskStatus.ready, 1), else_=0)).label("ready_count"),
                func.sum(
                    case(
                        (
                            WorkTask.status.in_([WorkTaskStatus.in_progress, WorkTaskStatus.partially_completed]),
                            1,
                        ),
                        else_=0,
                    )
                ).label("in_progress_count"),
                func.sum(case((WorkTask.status == WorkTaskStatus.waiting_previous, 1), else_=0)).label("waiting_count"),
            )
            .group_by(WorkTask.section_id)
        )
    ).all()

    incoming_counts = (
        await db.execute(
            select(
                Transfer.to_section_id.label("section_id"),
                func.count(Transfer.id).label("incoming_transfers_count"),
            )
            .where(Transfer.status.in_([TransferStatus.sent, TransferStatus.partially_accepted]))
            .group_by(Transfer.to_section_id)
        )
    ).all()

    by_section: dict[int, dict] = {}
    for row in status_counts:
        by_section[row.section_id] = {
            "total_tasks": int(row.total_tasks or 0),
            "ready_count": int(row.ready_count or 0),
            "in_progress_count": int(row.in_progress_count or 0),
            "waiting_count": int(row.waiting_count or 0),
            "incoming_transfers_count": 0,
        }

    for row in incoming_counts:
        entry = by_section.setdefault(
            row.section_id,
            {
                "total_tasks": 0,
                "ready_count": 0,
                "in_progress_count": 0,
                "waiting_count": 0,
                "incoming_transfers_count": 0,
            },
        )
        entry["incoming_transfers_count"] = int(row.incoming_transfers_count or 0)

    sections = (
        await db.execute(
            select(Section).where(Section.is_active == True).order_by(Section.sort_order, Section.id)
        )
    ).scalars().all()

    return {
        "sections": [
            {
                "section_id": section.id,
                "section_code": section.code,
                "section_name": section.name,
                "kind": section.kind,
                "sort_order": section.sort_order,
                "icon": section.icon,
                "icon_color": section.icon_color,
                "total_tasks": by_section.get(section.id, {}).get("total_tasks", 0),
                "ready_count": by_section.get(section.id, {}).get("ready_count", 0),
                "in_progress_count": by_section.get(section.id, {}).get("in_progress_count", 0),
                "waiting_count": by_section.get(section.id, {}).get("waiting_count", 0),
                "incoming_transfers_count": by_section.get(section.id, {}).get("incoming_transfers_count", 0),
            }
            for section in sections
        ]
    }


async def get_section_incoming_transfers(
    db: AsyncSession,
    *,
    section_id: int,
) -> dict:
    """Return incoming open transfers for a section."""
    from_section = aliased(Section)
    to_section = aliased(Section)
    from_task = aliased(WorkTask)
    to_task = aliased(WorkTask)
    from_step = aliased(RouteStep)
    to_step = aliased(RouteStep)

    rows = (
        await db.execute(
            select(
                Transfer,
                from_section,
                to_section,
                from_task,
                to_task,
                from_step,
                to_step,
            )
            .join(from_section, from_section.id == Transfer.from_section_id)
            .join(to_section, to_section.id == Transfer.to_section_id)
            .join(from_task, from_task.id == Transfer.from_task_id)
            .join(to_task, to_task.id == Transfer.to_task_id)
            .join(from_step, from_step.id == from_task.route_step_id)
            .join(to_step, to_step.id == to_task.route_step_id)
            .where(
                Transfer.to_section_id == section_id,
                Transfer.status.in_([TransferStatus.sent, TransferStatus.partially_accepted]),
            )
            .order_by(Transfer.sent_at.desc().nullslast(), Transfer.id.desc())
        )
    ).all()

    transfers = []
    for transfer, from_sec, to_sec, src_task, dst_task, src_step, dst_step in rows:
        sent = _to_decimal(transfer.sent_quantity or 0)
        accepted = _to_decimal(transfer.accepted_quantity or 0)
        rejected = _to_decimal(transfer.rejected_quantity or 0)
        remaining = sent - accepted - rejected
        if remaining < 0:
            remaining = Decimal("0")

        transfers.append(
            {
                "transfer_id": transfer.id,
                "transfer_no": transfer.transfer_no,
                "status": transfer.status.value,
                "from_task_id": transfer.from_task_id,
                "to_task_id": transfer.to_task_id,
                "from_section_id": transfer.from_section_id,
                "from_section_code": from_sec.code,
                "from_section_name": from_sec.name,
                "to_section_id": transfer.to_section_id,
                "to_section_code": to_sec.code,
                "to_section_name": to_sec.name,
                "from_operation_name": src_step.operation_name,
                "to_operation_name": dst_step.operation_name,
                "sent_quantity": str(sent),
                "accepted_quantity": str(accepted),
                "rejected_quantity": str(rejected),
                "remaining_quantity": str(remaining),
                "comment": transfer.comment,
                "sent_at": transfer.sent_at.isoformat() if transfer.sent_at else None,
                "created_at": transfer.created_at.isoformat() if transfer.created_at else None,
                "from_task_status": src_task.status.value,
                "to_task_status": dst_task.status.value,
            }
        )

    return {
        "section_id": section_id,
        "incoming_transfers": transfers,
    }


async def get_section_daily_stats(
    db: AsyncSession,
    *,
    section_id: int,
    date_from: datetime,
    date_to: datetime,
) -> dict:
    """Return daily statistics for a section, aggregated by performed_at date."""
    from sqlalchemy import cast, Date as SQLADate

    # Aggregate by date and movement type
    rows = (
        await db.execute(
            select(
                cast(Movement.performed_at, SQLADate).label("stat_date"),
                Movement.movement_type,
                func.count(Movement.id).label("op_count"),
                func.coalesce(func.sum(Movement.quantity), 0).label("total_qty"),
                func.avg(
                    func.extract("epoch", Movement.accounted_at) - func.extract("epoch", Movement.performed_at)
                ).label("avg_delay_seconds"),
            )
            .where(
                Movement.to_section_id == section_id,
                Movement.performed_at.isnot(None),
                Movement.performed_at >= date_from,
                Movement.performed_at <= date_to,
            )
            .group_by(
                cast(Movement.performed_at, SQLADate),
                Movement.movement_type,
            )
            .order_by(cast(Movement.performed_at, SQLADate))
        )
    ).all()

    daily_map: dict[str, dict] = {}
    for stat_date, mv_type, op_count, total_qty, avg_delay in rows:
        day_key = str(stat_date)
        if day_key not in daily_map:
            daily_map[day_key] = {
                "date": day_key,
                "good_quantity": "0",
                "rejected_quantity": "0",
                "op_count": 0,
                "avg_accounting_delay_seconds": "0",
            }

        type_key = mv_type.value if hasattr(mv_type, "value") else str(mv_type)
        daily_map[day_key]["op_count"] += op_count

        if type_key == MovementType.complete.value:
            daily_map[day_key]["good_quantity"] = str(_to_decimal(total_qty))
        elif type_key in (MovementType.reject.value, MovementType.scrap.value):
            daily_map[day_key]["rejected_quantity"] = str(_to_decimal(total_qty))

        if avg_delay is not None:
            daily_map[day_key]["avg_accounting_delay_seconds"] = str(round(float(avg_delay), 1))

    return {"section_id": section_id, "daily_stats": list(daily_map.values())}
