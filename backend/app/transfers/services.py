"""Write services for the transfer module.

The bodies of ``transfer_send``, ``transfer_receive`` and
``resolve_transfer_discrepancy_link`` are moved verbatim from the
historical ``app.services.shopfloor.operations_transfers``.  No
behaviour change — only the import paths and the conceptual home of
the code.

The shared cache (``app.services.shopfloor.cache``) and helpers
(``app.services.shopfloor.common``) are reused as-is: the
``Movement`` ledger is the universal event log for both the section
task side and the transfer side.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import DefectItem, TransferDiscrepancyDefectItem
from app.models.internal_plan import SectionPlanLine
from app.models.movement import Movement, MovementType
from app.models.transfer import (
    Transfer,
    TransferDiscrepancy,
    TransferDiscrepancyStatus,
    TransferStatus,
)
from app.models.work_task import WorkTask, WorkTaskStatus

from app.services.shopfloor.cache import (
    _refresh_section_plan_line_cache,
    _refresh_task_cache,
)
from app.services.shopfloor.common import (
    _check_idempotency,
    _ensure_positive,
    _get_route_stage,
    _get_task,
    _get_transfer,
    _get_user_snapshot_name,
    _to_decimal,
    _transfer_no,
)


async def transfer_send(
    db: AsyncSession,
    *,
    from_task_id: int,
    to_task_id: int | None = None,
    quantity: Decimal,
    actor_id: int,
    comment: str | None = None,
    source_ref: str | None = None,
    idempotency_key: str | None = None,
    executor_user_id: int | None = None,
    performed_at: datetime | None = None,
    accounted_at: datetime | None = None,
) -> dict:
    """Send ``quantity`` from a completed SectionTask to the next route step.

    The target ``WorkTask`` is resolved by ``SectionPlanLine.sequence ==
    from.sequence + 1``.  When no open target task exists for the next
    step, a new ``WorkTask`` with status ``waiting_previous`` is
    auto-created.

    A ``Transfer(status=sent)`` row and a ``Movement(type=transfer_send)``
    ledger row are written.  Idempotency is keyed on the
    ``idempotency_key`` of the Transfer itself; the send-side movement
    uses a ``:send`` suffix.
    """
    if idempotency_key:
        existing = await _check_idempotency(db, idempotency_key=idempotency_key, entity_type=Transfer)
        if existing is not None:
            return {
                "transfer_id": existing.id,
                "transfer_no": existing.transfer_no,
                "status": existing.status.value,
                "idempotent_replay": True,
            }

    from_task = await _get_task(db, from_task_id)
    from_line = await db.get(SectionPlanLine, from_task.section_plan_line_id)
    if from_line is None:
        raise ValueError("Source task plan line not found")

    # Find next section plan line
    next_line = await db.scalar(
        select(SectionPlanLine).where(
            SectionPlanLine.plan_position_id == from_line.plan_position_id,
            SectionPlanLine.sequence == from_line.sequence + 1,
        )
    )
    if next_line is None:
        raise ValueError("Next route step not found")

    # Find or create target task
    if to_task_id is not None:
        to_task = await _get_task(db, to_task_id)
    else:
        # Auto-create target task
        existing_task = await db.scalar(
            select(WorkTask).where(
                WorkTask.section_plan_line_id == next_line.id,
                WorkTask.status.notin_([WorkTaskStatus.completed, WorkTaskStatus.cancelled]),
            )
        )
        if existing_task:
            to_task = existing_task
        else:
            to_task = WorkTask(
                section_plan_line_id=next_line.id,
                section_id=next_line.section_id,
                product_id=next_line.product_id,
                route_stage_id=next_line.route_stage_id,
                planned_quantity=from_line.planned_quantity,
                status=WorkTaskStatus.waiting_previous,
                due_date=next_line.due_date,
            )
            db.add(to_task)
            await db.flush()
            await _refresh_task_cache(db, to_task.id)

    if from_task.product_id != to_task.product_id:
        raise ValueError("Transfer tasks must have same product")

    to_line = await db.get(SectionPlanLine, to_task.section_plan_line_id)
    if to_line is None or from_line.plan_position_id != to_line.plan_position_id:
        raise ValueError("Transfer tasks must belong to same plan position")

    from_stage = await _get_route_stage(db, from_task.route_stage_id)
    to_stage = await _get_route_stage(db, to_task.route_stage_id)
    if to_stage.sequence <= from_stage.sequence:
        raise ValueError("Transfer target must be next route step")

    # Block same-GHP transfers
    from app.services.shopfloor.common import sections_share_spg
    if await sections_share_spg(db, from_task.section_id, to_task.section_id):
        raise ValueError("Transfers within the same Storage Production Group (GHP) are not allowed")

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

    eff_executor = executor_user_id or actor_id
    actor_name = await _get_user_snapshot_name(db, actor_id)
    executor_name = await _get_user_snapshot_name(db, eff_executor)
    movement = Movement(
        product_id=from_task.product_id,
        task_id=from_task.id,
        section_plan_line_id=from_task.section_plan_line_id,
        transfer_id=transfer.id,
        from_section_id=from_task.section_id,
        to_section_id=to_task.section_id,
        movement_type=MovementType.transfer_send,
        quantity=quantity,
        source_ref=source_ref,
        comment=comment,
        created_by=actor_id,
        idempotency_key=f"{idempotency_key}:send" if idempotency_key else None,
        executor_user_id=eff_executor,
        created_by_user_name=actor_name,
        executor_user_name=executor_name,
        performed_at=performed_at or datetime.now(UTC),
        accounted_at=accounted_at or datetime.now(UTC),
    )
    db.add(movement)

    await _refresh_task_cache(db, from_task.id)
    await _refresh_section_plan_line_cache(db, from_task.section_plan_line_id)
    return {
        "transfer_id": transfer.id,
        "transfer_no": transfer.transfer_no,
        "status": transfer.status.value,
        "to_task_id": to_task.id,
    }


async def transfer_receive(
    db: AsyncSession,
    *,
    transfer_id: int,
    accepted_quantity: Decimal,
    rejected_quantity: Decimal,
    actor_id: int,
    reason: str | None = None,
    comment: str | None = None,
    source_ref: str | None = None,
    idempotency_key: str | None = None,
    executor_user_id: int | None = None,
    performed_at: datetime | None = None,
    accounted_at: datetime | None = None,
) -> dict:
    """Accept (or partially reject) a previously sent Transfer.

    On full accept: status -> ``accepted``, writes
    ``Movement(type=transfer_receive)`` for the accepted quantity, flips
    the target ``WorkTask`` from ``waiting_previous`` to ``ready``.

    On partial: status -> ``partially_accepted``; reject quantity
    creates an open ``TransferDiscrepancy``.

    On full reject: status -> ``rejected``.
    """
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
        eff_executor = executor_user_id or actor_id
        actor_name = await _get_user_snapshot_name(db, actor_id)
        executor_name = await _get_user_snapshot_name(db, eff_executor)
        movement = Movement(
            product_id=transfer.product_id,
            task_id=to_task.id,
            section_plan_line_id=to_task.section_plan_line_id,
            transfer_id=transfer.id,
            from_section_id=transfer.from_section_id,
            to_section_id=transfer.to_section_id,
            movement_type=MovementType.transfer_receive,
            quantity=accepted_quantity,
            source_ref=source_ref,
            reason=reason,
            comment=comment,
            created_by=actor_id,
            idempotency_key=f"{idempotency_key}:receive" if idempotency_key else None,
            executor_user_id=eff_executor,
            created_by_user_name=actor_name,
            executor_user_name=executor_name,
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
    return {
        "transfer_id": transfer.id,
        "status": transfer.status.value,
        "discrepancy_id": discrepancy_id,
    }


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
    """Resolve a transfer discrepancy by linking it to an existing DefectItem.

    No ``Movement`` is written here — the link simply records that the
    discrepancy is accounted for by the same defect that explains the
    reject on the receiving side.
    """
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


async def correct_transfer(
    db: AsyncSession,
    *,
    transfer_id: int,
    new_quantity: Decimal,
    actor_id: int,
    comment: str | None = None,
) -> dict:
    transfer = await _get_transfer(db, transfer_id)
    if transfer.status != TransferStatus.accepted:
        raise ValueError("Only accepted transfers can be corrected")

    new_quantity = _to_decimal(new_quantity)
    _ensure_positive(new_quantity, "quantity")
    
    old_quantity = transfer.sent_quantity
    if new_quantity == old_quantity:
        return {
            "transfer_id": transfer.id,
            "status": transfer.status.value,
            "quantity": str(transfer.sent_quantity),
        }

    from_task = await _get_task(db, transfer.from_task_id)
    to_task = await _get_task(db, transfer.to_task_id)
    
    # 1. Validate source limit
    transferable = from_task.cached_completed_quantity - from_task.cached_transferred_quantity + old_quantity
    if new_quantity > transferable:
        raise ValueError(
            f"Corrected quantity exceeds transferable amount of source task. "
            f"Available to transfer: {transferable}"
        )

    # 2. Validate target limit
    diff = new_quantity - old_quantity
    if diff < 0:
        if to_task.cached_available_quantity + diff < 0:
            raise ValueError(
                f"Target task has already consumed or issued parts. "
                f"Cannot reduce transfer by {abs(diff)} as target task only has {to_task.cached_available_quantity} available stock"
            )

    # 3. Update Transfer
    transfer.sent_quantity = new_quantity
    transfer.accepted_quantity = new_quantity
    if comment:
        transfer.comment = comment

    # 4. Update Movements
    movements_res = await db.execute(
        select(Movement).where(Movement.transfer_id == transfer.id)
    )
    movements = movements_res.scalars().all()
    for m in movements:
        m.quantity = new_quantity
        if comment:
            m.comment = comment

    await db.flush()

    # 5. Refresh cache
    await _refresh_task_cache(db, from_task.id)
    await _refresh_task_cache(db, to_task.id)
    await _refresh_section_plan_line_cache(db, from_task.section_plan_line_id)
    await _refresh_section_plan_line_cache(db, to_task.section_plan_line_id)

    return {
        "transfer_id": transfer.id,
        "status": transfer.status.value,
        "quantity": str(transfer.sent_quantity),
    }


async def cancel_transfer(
    db: AsyncSession,
    *,
    transfer_id: int,
    actor_id: int,
    comment: str | None = None,
) -> dict:
    transfer = await _get_transfer(db, transfer_id)
    if transfer.status == TransferStatus.cancelled:
        return {
            "transfer_id": transfer.id,
            "status": transfer.status.value,
        }
    if transfer.status != TransferStatus.accepted:
        raise ValueError("Only accepted transfers can be cancelled")

    from_task = await _get_task(db, transfer.from_task_id)
    to_task = await _get_task(db, transfer.to_task_id)

    # Validate target available stock before cancellation
    diff = -transfer.sent_quantity
    if to_task.cached_available_quantity + diff < 0:
        raise ValueError(
            f"Target task has already consumed or issued parts. "
            f"Cannot cancel transfer as target task only has {to_task.cached_available_quantity} available stock"
        )

    # Update Transfer
    transfer.status = TransferStatus.cancelled
    transfer.accepted_quantity = Decimal("0")
    if comment:
        transfer.comment = comment
    # Delete movements to restore balances (movements table requires quantity > 0)
    movements_res = await db.execute(
        select(Movement).where(Movement.transfer_id == transfer.id)
    )
    movements = movements_res.scalars().all()
    for m in movements:
        await db.delete(m)

    await db.flush()
    # Refresh cache
    await _refresh_task_cache(db, from_task.id)
    await _refresh_task_cache(db, to_task.id)
    await _refresh_section_plan_line_cache(db, from_task.section_plan_line_id)
    await _refresh_section_plan_line_cache(db, to_task.section_plan_line_id)

    return {
        "transfer_id": transfer.id,
        "status": transfer.status.value,
    }

