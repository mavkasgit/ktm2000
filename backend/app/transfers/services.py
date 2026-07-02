"""Write services for the transfer module.

Under the explicit-transfer model, ``transfer_send`` is the single
write path: it creates the ``Transfer`` row, the ``transfer_send``
Movement, AND the ``transfer_receive`` Movement (auto-accept), and
flips the destination ``WorkTask`` from ``waiting_previous`` to
``ready``. There is no separate accept step on the UI side; the
material is considered moved as soon as the operator confirms
``Send`` on ``/transfers``.

The shared cache (``app.services.shopfloor.cache``) and helpers
(``app.services.shopfloor.common``) are reused as-is: the
``Movement`` ledger is the universal event log for both the section
task side and the transfer side.

Legacy functions ``transfer_receive`` and
``resolve_transfer_discrepancy_link`` are kept as no-ops so old call
sites in ``app.api.routes.demo``, ``app.api.routes.production_planning``
and a few tests don't break. They will be removed in a follow-up.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_plan import SectionPlanLine
from app.models.movement import Movement, MovementType
from app.models.transfer import Transfer, TransferStatus
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
    _get_task_for_update,
    _get_transfer,
    _get_user_snapshot_name,
    _to_decimal,
    _transfer_no,
)


async def _get_task_transferable(db: AsyncSession, task: WorkTask) -> Decimal:
    from app.models.section import Section
    sec = await db.get(Section, task.section_id)
    if sec and sec.kind in {"raw_stock", "wip_stock", "finished_stock"}:
        return task.cached_available_quantity

    from sqlalchemy import func
    remainders_qty = Decimal("0")
    has_auto_complete = await db.scalar(
        select(func.count(Movement.id)).where(
            Movement.task_id == task.id,
            Movement.movement_type == MovementType.complete,
            Movement.source_ref == "auto_release_remainder"
        )
    ) > 0
    if not has_auto_complete:
        from app.models.spg_remainder import SpgRemainder
        from app.models.internal_plan import SectionPlanLine
        line = await db.get(SectionPlanLine, task.section_plan_line_id)
        if line:
            remainders = (await db.execute(
                select(SpgRemainder).where(SpgRemainder.reserved_for_plan_position_id == line.plan_position_id)
            )).scalars().all()
            for rem in remainders:
                stages_json = rem.completed_stages_json or []
                max_seq = max((s.get("sequence", 0) for s in stages_json), default=0)
                if max_seq == line.sequence:
                    remainders_qty += rem.remainder_quantity

    return task.cached_completed_quantity + remainders_qty - task.cached_transferred_quantity


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
    post_factum: bool = False,
    allow_over_plan: bool = False,
    physical_handover_at: datetime | None = None,
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

    When ``post_factum=True``, the cross-GHP ``quantity <= transferable``
    guard is skipped: the receiving section may have already started
    working on the parts, and the formal transfer is being recorded
    after the physical handover.  The Transfer and resulting Movement
    rows are tagged with ``is_post_factum=True`` for audit/history; the
    ``performed_at`` is taken from ``physical_handover_at`` (or
    ``performed_at``) so the ledger reflects when the work physically
    moved between sections.
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

    from_task = await _get_task_for_update(db, from_task_id)
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
                # If more than planned is being transferred, expand the task's plan
                # so the receiving section can issue and complete the full quantity.
                planned_quantity=max(from_line.planned_quantity, quantity),
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

    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")
    if not post_factum and not allow_over_plan:
        transferable = await _get_task_transferable(db, from_task)
        if quantity > transferable:
            raise ValueError("Transfer quantity exceeds transferable amount")

    now = datetime.now(UTC)
    eff_performed = physical_handover_at or performed_at or now
    eff_accounted = accounted_at or now

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
        sent_at=eff_accounted,
        comment=comment,
        idempotency_key=idempotency_key,
        is_post_factum=post_factum,
        physical_handover_at=physical_handover_at,
    )
    db.add(transfer)
    await db.flush()

    eff_executor = executor_user_id or actor_id
    actor_name = await _get_user_snapshot_name(db, actor_id)
    executor_name = await _get_user_snapshot_name(db, eff_executor)
    send_movement = Movement(
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
        performed_at=eff_performed,
        accounted_at=eff_accounted,
        is_post_factum=post_factum,
    )
    db.add(send_movement)

    # Auto-accept: since the operator confirms the transfer on the
    # /transfers page, the material is considered immediately received
    # on the destination. The destination task transitions
    # ``waiting_previous -> ready`` and ``cached_received_quantity`` is
    # bumped. Reject/partial accept are no longer part of the model —
    # see ``docs/superpowers/plans/2026-07-01-explicit-transfers-mandatory.md``.
    transfer.status = TransferStatus.accepted
    transfer.accepted_quantity = quantity
    transfer.accepted_by = actor_id
    transfer.accepted_at = eff_accounted
    if to_task.status == WorkTaskStatus.waiting_previous:
        to_task.status = WorkTaskStatus.ready
        await db.flush()
    receive_movement = Movement(
        product_id=transfer.product_id,
        task_id=to_task.id,
        section_plan_line_id=to_task.section_plan_line_id,
        transfer_id=transfer.id,
        from_section_id=transfer.from_section_id,
        to_section_id=transfer.to_section_id,
        movement_type=MovementType.transfer_receive,
        quantity=quantity,
        source_ref=source_ref,
        comment=comment,
        created_by=actor_id,
        idempotency_key=f"{idempotency_key}:receive" if idempotency_key else None,
        executor_user_id=eff_executor,
        created_by_user_name=actor_name,
        executor_user_name=executor_name,
        performed_at=eff_performed,
        accounted_at=eff_accounted,
        is_post_factum=post_factum,
    )
    db.add(receive_movement)

    # If the source section is a stock section, consume the matching
    # SpgRemainder FIFO. This used to live in the legacy
    # ``transfer_receive`` step; under the auto-accept model it is
    # part of ``transfer_send`` so the source stock balance is updated
    # atomically with the destination receipt.
    from app.models.section import Section
    from_section = await db.get(Section, transfer.from_section_id)
    if from_section and from_section.kind in {"raw_stock", "wip_stock", "finished_stock"}:
        from app.models.spg import SpgSection
        from_spg_id = await db.scalar(
            select(SpgSection.spg_id).where(SpgSection.section_id == transfer.from_section_id)
        )
        if from_spg_id is not None:
            from sqlalchemy import case
            from app.models.spg_remainder import SpgRemainder
            remainders = (await db.execute(
                select(SpgRemainder)
                .where(
                    SpgRemainder.spg_id == from_spg_id,
                    SpgRemainder.product_id == transfer.product_id,
                    SpgRemainder.remainder_quantity > 0,
                    SpgRemainder.consumed_at.is_(None),
                    (SpgRemainder.reserved_for_plan_position_id == from_line.plan_position_id)
                    | SpgRemainder.reserved_for_plan_position_id.is_(None),
                )
                .order_by(
                    case(
                        (SpgRemainder.reserved_for_plan_position_id == from_line.plan_position_id, 0),
                        else_=1,
                    ),
                    SpgRemainder.created_at.asc(),
                    SpgRemainder.id.asc(),
                )
            )).scalars().all()

            qty_to_consume = quantity
            for rem in remainders:
                if qty_to_consume <= 0:
                    break
                consume_qty = min(qty_to_consume, rem.remainder_quantity)
                rem.remainder_quantity -= consume_qty
                if rem.remainder_quantity == 0:
                    rem.consumed_at = datetime.now(UTC)
                    rem.consumed_by_task_id = to_task.id
                qty_to_consume -= consume_qty

    await _refresh_task_cache(db, from_task.id)
    refreshed_to_task = await _refresh_task_cache(db, to_task.id)
    await _refresh_section_plan_line_cache(db, from_task.section_plan_line_id)
    await _refresh_section_plan_line_cache(db, to_task.section_plan_line_id)

    # If cumulative received quantity now exceeds the task's planned quantity
    # (i.e., over-plan material was transferred), expand planned_quantity so
    # operators can issue and complete the full received amount at this stage.
    # SectionPlanLine.planned_quantity is intentionally NOT changed — the plan
    # itself stays the same; only the task-level target is adjusted.
    if refreshed_to_task.cached_received_quantity > refreshed_to_task.planned_quantity:
        refreshed_to_task.planned_quantity = refreshed_to_task.cached_received_quantity
        await db.flush()
        await _refresh_task_cache(db, refreshed_to_task.id)
        await _refresh_section_plan_line_cache(db, refreshed_to_task.section_plan_line_id)

    # Запись лога аудита (передача)
    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction, AuditEntityType
    from app.models.section import Section
    from app.models.product import Product
    
    from_section = await db.get(Section, from_task.section_id)
    to_section = await db.get(Section, to_task.section_id)
    product = await db.get(Product, from_task.product_id)
    
    await log_action(
        db,
        status="success",
        title="Отправка передачи",
        message=f"Передача #{transfer.transfer_no} отправлена из участка \"{from_section.name if from_section else ''}\" в участок \"{to_section.name if to_section else ''}\" (арт. {product.sku if product else ''}). Количество: {quantity} шт.",
        user_id=actor_id,
        section_id=from_task.section_id,
        section_name=from_section.name if from_section else None,
        section_code=from_section.code if from_section else None,
        task_ids=[from_task.id, to_task.id],
        product_sku=product.sku if product else None,
        qty_text=str(quantity),
        comment=comment,
        action=AuditAction.SEND,
        entity_type=AuditEntityType.TRANSFER,
        entity_id=transfer.id,
        changes={"before": None, "after": {"status": "sent", "quantity": str(quantity)}},
    )

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
    accepted_quantity: Decimal | None = None,  # noqa: ARG001 — legacy arg
    rejected_quantity: Decimal | None = None,  # noqa: ARG001 — legacy arg
    actor_id: int | None = None,  # noqa: ARG001 — legacy arg
    reason: str | None = None,  # noqa: ARG001 — legacy arg
    comment: str | None = None,  # noqa: ARG001 — legacy arg
    source_ref: str | None = None,  # noqa: ARG001 — legacy arg
    idempotency_key: str | None = None,  # noqa: ARG001 — legacy arg
    executor_user_id: int | None = None,  # noqa: ARG001 — legacy arg
    performed_at: datetime | None = None,  # noqa: ARG001 — legacy arg
    accounted_at: datetime | None = None,  # noqa: ARG001 — legacy arg
) -> dict:
    """Legacy no-op kept for backwards compatibility with old call sites.

    Under the new explicit-transfer model, ``transfer_send`` itself
    auto-accepts the transfer (status flips to ``accepted`` and the
    ``transfer_receive`` Movement is written inline). A separate manual
    accept step is no longer part of the UI contract. Calling
    ``transfer_receive`` is a no-op that returns the current state of
    the transfer for the rare legacy path that still reaches this
    function.

    See ``docs/superpowers/plans/2026-07-01-explicit-transfers-mandatory.md``
    for the model description.
    """
    transfer = await _get_transfer(db, transfer_id)
    return {
        "transfer_id": transfer.id,
        "status": transfer.status.value,
        "discrepancy_id": None,
    }


async def resolve_transfer_discrepancy_link(
    db: AsyncSession,
    *,
    transfer_id: int,
    discrepancy_id: int,  # noqa: ARG001 — legacy arg
    defect_item_id: int,  # noqa: ARG001 — legacy arg
    quantity: Decimal,  # noqa: ARG001 — legacy arg
    actor_id: int,  # noqa: ARG001 — legacy arg
    comment: str | None = None,  # noqa: ARG001 — legacy arg
) -> dict:
    """Legacy no-op kept for backwards compatibility with old call sites.

    Discrepancy linking is no longer part of the model — transfers are
    either accepted in full on send or cancelled. Calling this function
    returns a ``resolved``-looking result with zero quantities. New code
    must not call it.
    """
    return {
        "discrepancy_id": None,
        "status": "resolved",
        "resolved_quantity": "0",
        "unresolved_quantity": "0",
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
    transferable = await _get_task_transferable(db, from_task) + old_quantity
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

    # Запись лога аудита (корректировка передачи)
    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction, AuditEntityType
    from app.models.section import Section
    from app.models.product import Product
    
    from_section = await db.get(Section, transfer.from_section_id)
    to_section = await db.get(Section, transfer.to_section_id)
    product = await db.get(Product, transfer.product_id)
    
    await log_action(
        db,
        status="success",
        title="Корректировка передачи",
        message=f"Передача #{transfer.transfer_no} скорректирована. Количество изменено с {old_quantity} на {new_quantity} шт.",
        user_id=actor_id,
        section_id=transfer.from_section_id,
        section_name=from_section.name if from_section else None,
        section_code=from_section.code if from_section else None,
        task_ids=[transfer.from_task_id, transfer.to_task_id],
        product_sku=product.sku if product else None,
        qty_text=f"{old_quantity} -> {new_quantity}",
        comment=comment,
        action=AuditAction.CORRECT,
        entity_type=AuditEntityType.TRANSFER,
        entity_id=transfer.id,
        changes={"before": {"quantity": str(old_quantity)}, "after": {"quantity": str(new_quantity)}},
    )

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

    # Validate target in-work quantity before cancellation
    in_work = to_task.cached_issued_quantity - to_task.cached_completed_quantity - to_task.cached_rejected_quantity
    if in_work < transfer.sent_quantity:
        raise ValueError(
            f"Target task has already completed or rejected parts. "
            f"Cannot cancel transfer as target task only has {in_work} in work"
        )

    # Update Transfer
    transfer.status = TransferStatus.cancelled
    transfer.accepted_quantity = Decimal("0")
    if comment:
        transfer.comment = comment

    # Restore SpgRemainder in the source GHP if from_section is a stock section
    from app.models.section import Section
    from_section = await db.get(Section, transfer.from_section_id)
    if from_section and from_section.kind in {"raw_stock", "wip_stock", "finished_stock"}:
        from app.models.spg import SpgSection
        from_spg_id = await db.scalar(
            select(SpgSection.spg_id).where(SpgSection.section_id == transfer.from_section_id)
        )
        if from_spg_id is not None:
            from app.models.spg_remainder import SpgRemainder
            consumed_rems = (await db.execute(
                select(SpgRemainder)
                .where(
                    SpgRemainder.spg_id == from_spg_id,
                    SpgRemainder.product_id == transfer.product_id,
                    SpgRemainder.consumed_by_task_id == to_task.id,
                )
                .order_by(SpgRemainder.consumed_at.desc(), SpgRemainder.id.desc())
            )).scalars().all()
            
            qty_to_restore = transfer.sent_quantity  # restore full sent amount
            for rem in consumed_rems:
                if qty_to_restore <= 0:
                    break
                restorable = rem.original_issued - rem.remainder_quantity
                restore_qty = min(qty_to_restore, restorable)
                rem.remainder_quantity += restore_qty
                rem.consumed_at = None
                rem.consumed_by_task_id = None
                qty_to_restore -= restore_qty
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

    # Запись лога аудита (отмена передачи)
    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction, AuditEntityType
    from app.models.section import Section
    from app.models.product import Product
    
    from_section = await db.get(Section, transfer.from_section_id)
    to_section = await db.get(Section, transfer.to_section_id)
    product = await db.get(Product, transfer.product_id)
    
    await log_action(
        db,
        status="success",
        title="Отмена передачи",
        message=f"Передача #{transfer.transfer_no} успешно отменена.",
        user_id=actor_id,
        section_id=transfer.from_section_id,
        section_name=from_section.name if from_section else None,
        section_code=from_section.code if from_section else None,
        task_ids=[transfer.from_task_id, transfer.to_task_id],
        product_sku=product.sku if product else None,
        qty_text="0",
        comment=comment,
        action=AuditAction.CANCEL,
        entity_type=AuditEntityType.TRANSFER,
        entity_id=transfer.id,
        changes={"before": {"status": "accepted"}, "after": {"status": "cancelled"}},
    )

    return {
        "transfer_id": transfer.id,
        "status": transfer.status.value,
    }


async def auto_create_transfer_after_complete(
    db: AsyncSession,
    *,
    from_task: WorkTask,
    good_quantity: Decimal,
    actor_id: int,
    idempotency_key: str | None = None,
    comment: str | None = None,
) -> dict | None:
    """Create an automatic cross-GHP Transfer for the completed ``good_quantity``.

    Called by ``complete_task`` after a successful completion.  No-op when:
    * there is no next route step (final stage);
    * the next section is in the same GHP (intra-GHP transfers are
      forbidden by ``transfer_send`` and the inventory is already wired
      via ``auto_consume_available_remainders``).

    Uses ``post_factum=True`` because the physical handover between
    sections has already happened on the shopfloor.
    Returns ``None`` when the helper decides to skip; otherwise returns
    the result of ``transfer_send``.
    """
    from app.models.internal_plan import SectionPlanLine
    from app.services.shopfloor.common import sections_share_spg

    from_line = await db.get(SectionPlanLine, from_task.section_plan_line_id)
    if from_line is None:
        return None

    next_line = await db.scalar(
        select(SectionPlanLine).where(
            SectionPlanLine.plan_position_id == from_line.plan_position_id,
            SectionPlanLine.sequence == from_line.sequence + 1,
        )
    )
    if next_line is None:
        return None  # финальный шаг — перемещать некуда

    if good_quantity <= 0:
        return None

    if await sections_share_spg(db, from_task.section_id, next_line.section_id):
        return None  # та же ГХП — перемещение не нужно

    next_task = await db.scalar(
        select(WorkTask).where(
            WorkTask.section_plan_line_id == next_line.id,
            WorkTask.status.notin_([WorkTaskStatus.completed, WorkTaskStatus.cancelled]),
        )
    )
    if next_task is None:
        return None  # нет живой задачи на следующем шаге

    key = f"{idempotency_key}:auto-transfer-complete" if idempotency_key else None
    return await transfer_send(
        db,
        from_task_id=from_task.id,
        to_task_id=next_task.id,
        quantity=good_quantity,
        actor_id=actor_id,
        comment=comment or "Авто-перемещение после завершения",
        idempotency_key=key,
        post_factum=True,
    )


# NOTE: auto_create_transfer_from_stock_to_production был удалён.
# Под новой моделью (Send = auto-accept, никаких auto-flows на issue) —
# оператор сам явно отправляет передачу со склада через /transfers.
# Если хелпер понадобится снова — он делал send+receive, что теперь
# сводится к одному transfer_send (он сам auto-accept'ит).
