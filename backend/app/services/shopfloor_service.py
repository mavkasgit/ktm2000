from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
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
from app.models.rework_task import ReworkTask, ReworkTaskStatus
from app.models.route import RouteStep
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
) -> dict:
    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")
    task = await _get_task(db, task_id)
    if task.status not in {WorkTaskStatus.ready, WorkTaskStatus.in_progress, WorkTaskStatus.partially_completed}:
        raise ValueError("Task must be ready/in_progress/partially_completed")

    available = task.planned_quantity + task.cached_received_quantity - task.cached_issued_quantity
    if quantity > available:
        raise ValueError("Issue quantity exceeds available quantity")

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
) -> dict:
    task = await _get_task(db, task_id)
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
) -> dict:
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
) -> dict:
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
