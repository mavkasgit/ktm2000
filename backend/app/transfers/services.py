"""Write services for the transfer module.

Under the explicit-transfer model, ``transfer_send`` is the single
write path: it creates the ``Transfer`` row and two
``StockTransaction`` entries (``TRANSFER_SEND`` on the source task,
``TRANSFER_RECEIVE`` on the destination task) via
``StockCommandService.record()``. No ``Movement`` rows are created —
``StockTransaction`` is the single source of truth.

The destination ``WorkTask`` flips from ``waiting_previous`` to
``ready``; ``TRANSFER_RECEIVE`` автоматически попадает в
``issued_quantity`` (колонка «Выдано») — единственный канал выдачи
после миграции на Transfer.

``StockProjectionManager.refresh_task_projection`` updates
``WorkTask.cached_transferred_quantity`` and
``cached_received_quantity`` from ``StockTransaction`` ledger. The
shared cache (``app.services.shopfloor.cache``) continues to refresh
non-transfer ``cached_*`` columns from the ``Movement`` table for
legacy operations until Этап 3.

Cancel creates compensating ``StockTransaction`` rows (append-only).
Correct updates quantity in-place on active ``StockTransaction`` rows
(controlled mutable exception — see ``_resync_transfer_stock_tx_quantity``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_plan import SectionPlanLine
from app.models.section import Section
from app.models.transfer import Transfer, TransferStatus
from app.models.work_task import WorkTask, WorkTaskStatus

from app.services.shopfloor.cache import (
    _refresh_section_plan_line_cache,
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
    enrich_comment_with_route_operations,
)

# ─── Ledger helpers (Этап 2) ─────────────────────────────────────────────────
# Transfer пишет две StockTransaction (TRANSFER_SEND + TRANSFER_RECEIVE) через
# StockCommandService.record(). Обе проводки имеют геометрию
# ``from=from_section → to=to_section``: каждая двигает баланс обеих локаций
# на quantity. Отмена — компенсационные транзакции (append-only).
# Коррекция — in-place изменение quantity активных транзакций.
from app.domain.dimensions import canonicalize_dimensions
from app.stock.models import Reason, StockTransaction
from app.stock.services import (
    StockCommand,
    StockCommandService,
    dimensions_match_clause,
)
from app.stock.ledger import net_transferred
from app.transfers import budget

_stock_command_service = StockCommandService()


async def compute_stock_section_transferable(
    db: AsyncSession,
    *,
    task: WorkTask,
    section: Section,
    planned_qty: Decimal,
    dimensions: dict | None = None,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Остаток к передаче со склада по паре (строка плана, размер).

    Возвращает ``(transferable, plan_remaining, physical_stock, already_transferred)``.
    Нельзя передать больше плана позиции и больше физического остатка на складе.
    ``already_transferred`` учитывается по размеру (не по строке целиком):
    несколько передач одного размера разрешены, сумма ограничена через
    ``transferable``.
    """
    from app.stock.models import QualityState, StockBalance

    # Размер группы: если явный не передан — берём из задания (канонический
    # габарит плана). None = безразмерная legacy-группа.
    dims = dimensions if dimensions is not None else task.dimensions

    already_transferred = await net_transferred(
        db,
        section_plan_line_id=task.section_plan_line_id,
        dims=dims,
    )

    plan_remaining = max(Decimal("0"), _to_decimal(planned_qty) - already_transferred)

    physical_stock_q = select(func.coalesce(func.sum(StockBalance.balance_qty), 0)).where(
        StockBalance.location_id == section.id,
        StockBalance.product_id == task.product_id,
        StockBalance.balance_qty > 0,
        StockBalance.quality_state == QualityState.GOOD,
    )
    # Задание несёт габарит (ADR-0001): остаток считается только по строке
    # баланса этой размерности. Без длины — legacy-поведение (все группы).
    if dims is not None:
        physical_stock_q = physical_stock_q.where(
            dimensions_match_clause(StockBalance.dimensions, dims)
        )
    physical_stock = (await db.scalar(physical_stock_q)) or Decimal("0")

    transferable = budget.remaining_stock(plan_remaining, physical_stock)
    return transferable, plan_remaining, physical_stock, already_transferred


async def _get_task_transferable(
    db: AsyncSession,
    task: WorkTask,
    *,
    dimensions: dict | None = None,
) -> Decimal:
    from app.models.section import Section
    from app.services.route_storage_classifier import is_stock_section
    from app.stock.services import StockProjectionManager

    sec = await db.get(Section, task.section_id)
    if is_stock_section(sec):
        line = await db.get(SectionPlanLine, task.section_plan_line_id)
        planned_qty = task.planned_quantity
        if line is not None and line.planned_quantity:
            planned_qty = line.planned_quantity
        transferable, _, _, _ = await compute_stock_section_transferable(
            db,
            task=task,
            section=sec,
            planned_qty=planned_qty,
            dimensions=dimensions,
        )
        return transferable

    # Трансформирующий этап (ADR-0002): задание несёт спецификацию выходов
    # (WorkTask.outputs). Передавать можно не больше количества выхода этого
    # размера минус уже переданное — инвариант D2. Размер, которого нет в
    # спецификации (например, входной), передавать нельзя.
    # Тикет #91: transferable выхода = min(выход, произведено по размеру) −
    # уже переданное по этому размеру. Частичная порция не позволяет
    # передать больше, чем фактически раскроено (готовой баланс тоже
    # ограничивает, но кап здесь — бизнес-правило).
    # Т6: write guard сведён к read-path гидрации (queries.py) — produced по
    # строкам выхода считается через build_outputs_progress, чтобы write и
    # read не расходились. Кап min(output_quantity, produced_by_group) живёт
    # внутри build_outputs_progress; здесь остаётся только
    # remaining_transform(produced_for_dims, transferred).
    if task.outputs:
        from app.domain.dimensions import canonicalize_dimensions, dimensions_equal
        from app.services.shopfloor.operations_transform import (
            build_outputs_progress,
            get_transform_progress,
        )

        dims = canonicalize_dimensions(dimensions)
        progress = await get_transform_progress(db, task.id)
        produced_rows = build_outputs_progress(
            task.outputs, progress.produced_by_group
        )
        produced_for_dims = Decimal("0")
        for entry, produced_entry in zip(task.outputs, produced_rows):
            if dimensions_equal(entry.get("dimensions"), dims):
                produced_for_dims += produced_entry["produced_quantity"]
        transferred = await net_transferred(db, task_id=task.id, dims=dims)
        return budget.remaining_transform(produced_for_dims, transferred)

    pm = StockProjectionManager()
    cache = await pm.get_task_cache(db, task.id)
    transferred_by_size = await net_transferred(
        db, task_id=task.id, dims=dimensions
    )
    # T6: received no longer contributes to plain transfer budget.
    return budget.remaining_plain(cache["completed_quantity"], transferred_by_size)


async def _record_transfer_send_stock_tx(
    db: AsyncSession,
    *,
    transfer: Transfer,
    from_task: WorkTask,
    to_task: WorkTask,
    quantity: Decimal,
    dimensions: dict | None,
    actor_id: int,
    executor_user_id: int | None,
    actor_name: str | None,
    executor_name: str | None,
    source_ref: str | None,
    comment: str | None,
    idempotency_key: str | None,
    performed_at: datetime | None,
    accounted_at: datetime | None,
    is_post_factum: bool,
) -> StockTransaction:
    """Запись TRANSFER_SEND в StockTransaction ledger.

    Создаёт ``StockTransaction`` с геометрией
    ``from=from_section → to=to_section``, reason ``TRANSFER_SEND``,
    ``task_id=from_task``. Физическое движение остатков выполняет только
    эта проводка; ``TRANSFER_RECEIVE`` на приёмной задаче — учётная
    (без ``from``/``to``), чтобы не дублировать списание/приход.

    Идемпотентность по суффиксу ``:stock-send``. Возвращает созданную
    транзакцию (или существующую при идемпотентном повторе).
    """
    return await _stock_command_service.record(
        db,
        StockCommand(
            product_id=transfer.product_id,
            quantity=quantity,
            reason=Reason.TRANSFER_SEND,
            from_location_id=transfer.from_section_id,
            to_location_id=transfer.to_section_id,
            dimensions=dimensions,
            task_id=from_task.id,
            transfer_id=transfer.id,
            section_plan_line_id=from_task.section_plan_line_id,
            created_by=actor_id,
            executor_user_id=executor_user_id,
            created_by_user_name=actor_name,
            executor_user_name=executor_name,
            source_ref=source_ref,
            comment=comment,
            idempotency_key=f"{idempotency_key}:stock-send" if idempotency_key else None,
            performed_at=performed_at,
            accounted_at=accounted_at,
            is_post_factum=is_post_factum,
        ),
    )


async def _compensate_transfer_stock_tx(
    db: AsyncSession,
    *,
    transfer: Transfer,
    actor_id: int,
    comment: str | None,
) -> None:
    """Компенсация всех активных StockTransaction transfer'а (append-only).

    Для каждой непогашенной транзакции (``compensates_tx_id IS NULL``) с
    reason ``TRANSFER_SEND`` / ``TRANSFER_RECEIVE`` создаётся встречная
    запись с перевёрнутыми локациями и ``compensates_tx_id`` → исходная.
    Суммарный баланс по transfer возвращается к нулю (инвариант S6 для
    cancelled transfer'ов исключён, S1 баланс сходится).

    Идемпотентность: если компенсация уже была записана (повторный
    cancel — no-op по status guard в ``cancel_transfer``), дубликаты не
    создаются благодаря суффиксу ``:stock-cancel``.
    """
    res = await db.execute(
        select(StockTransaction)
        .where(
            StockTransaction.transfer_id == transfer.id,
            StockTransaction.compensates_tx_id.is_(None),
            StockTransaction.reason.in_(
                [Reason.TRANSFER_SEND, Reason.TRANSFER_RECEIVE]
            ),
        )
        .order_by(StockTransaction.id.asc())
    )
    originals = res.scalars().all()
    for orig in originals:
        # Переворот локаций: исходящая сторона становится входящей.
        comp_from = orig.to_location_id  # была приёмной → теперь источник
        comp_to = orig.from_location_id  # была источником → теперь приёмная
        await _stock_command_service.record(
            db,
            StockCommand(
                product_id=orig.product_id,
                quantity=orig.quantity,
                reason=orig.reason,
                from_location_id=comp_from,
                to_location_id=comp_to,
                # Компенсация гасит остаток той же габаритной группы.
                dimensions=orig.dimensions,
                task_id=orig.task_id,
                transfer_id=transfer.id,
                section_plan_line_id=orig.section_plan_line_id,
                compensates_tx_id=orig.id,
                created_by=actor_id,
                comment=f"cancel transfer #{transfer.transfer_no}: {comment or ''}".strip(),
                # Безусловный ключ: protects даже если у исходной tx не было
                # idempotency_key (auto-transfers могут не иметь своего).
                # Status-guard в cancel_transfer короткозамыкает повторный
                # cancel, но при будущих partial-cancel это убережёт от дублей.
                idempotency_key=f"transfer-cancel:{transfer.id}:tx:{orig.id}",
                is_post_factum=orig.is_post_factum,
            ),
        )


async def _resync_transfer_stock_tx_quantity(
    db: AsyncSession,
    *,
    transfer: Transfer,
    new_quantity: Decimal,
) -> None:
    """Синхронизация quantity активных StockTransaction transfer'а.

    ``correct_transfer`` меняет ``sent_quantity`` у Transfer и quantity у
    активных StockTransaction (непогашенных, без ``compensates_tx_id``)
    in-place. После чего баланс пересчитывается через ``refresh_balance``.

    Это контролируемое mutable-исключение из append-only принципа — оно
    касается только коррекции количества, но не отмены (cancel идёт через
    компенсации). См. PLAN_stock_ledger.md → принцип 4.
    """
    res = await db.execute(
        select(StockTransaction)
        .where(
            StockTransaction.transfer_id == transfer.id,
            StockTransaction.compensates_tx_id.is_(None),
            StockTransaction.reason.in_(
                [Reason.TRANSFER_SEND, Reason.TRANSFER_RECEIVE]
            ),
        )
    )
    originals = res.scalars().all()
    for orig in originals:
        orig.quantity = new_quantity
    await db.flush()
    # Пересчёт затронутых балансов: для каждой tx — её from и to локации.
    for orig in originals:
        await _stock_command_service._projection_manager.refresh_balance(db, orig)


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
    dimensions: dict | None = None,
) -> dict:
    """Send ``quantity`` from a completed SectionTask to the next route step.

    The target ``WorkTask`` is resolved by ``SectionPlanLine.sequence ==
    from.sequence + 1``.  When no open target task exists for the next
    step, a new ``WorkTask`` with status ``waiting_previous`` is
    auto-created.

    Two ``StockTransaction`` rows (``TRANSFER_SEND`` on the source,
    ``TRANSFER_RECEIVE`` on the destination) are written via
    ``StockCommandService.record()`` — the single source of truth for
    the ledger.  The auto-accept collapses the historical
    «receive → issue to work» two-step into a single operator action:
    as soon as the material is on the receiving section, it is
    considered issued and ready to be completed.  Stock-to-production
    uses the same path via a stock-section fake_task.

    Idempotency is keyed on the ``idempotency_key`` of the Transfer
    itself; the send-side and receive-side StockTransaction entries use
    ``:stock-send`` / ``:stock-receive`` suffixes respectively.

    When ``post_factum=True``, the cross-GHP ``quantity <= transferable``
    guard is skipped: the receiving section may have already started
    working on the parts, and the formal transfer is being recorded
    after the physical handover.  The Transfer and resulting
    StockTransaction rows are tagged with ``is_post_factum=True`` for
    audit/history; the ``performed_at`` is taken from
    ``physical_handover_at`` (or ``performed_at``) so the ledger
    reflects when the work physically moved between sections.
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

    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")
    # Габарит (ADR-0001): одна каноническая форма для обеих проводок и для
    # auto-created to_task (task и ledger не расходятся). При пустом payload —
    # fallback на габарит исходного задания (тикет #89): ready-строка и план
    # несут длину, передавать «вслепую» нельзя. Валидация до создания Task/Transfer.
    dimensions = canonicalize_dimensions(
        dimensions if dimensions is not None else from_task.dimensions
    )

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
            # Трансформирующий этап несёт вход/выходы позиции (ADR-0002)
            from app.services.route_transform import transform_fields_for_task

            lazy_planned_quantity = max(from_line.planned_quantity, quantity)
            transform_fields = await transform_fields_for_task(
                db,
                route_stage_id=next_line.route_stage_id,
                plan_position_id=next_line.plan_position_id,
                task_quantity=lazy_planned_quantity,
            )
            to_task = WorkTask(
                section_plan_line_id=next_line.id,
                section_id=next_line.section_id,
                product_id=next_line.product_id,
                route_stage_id=next_line.route_stage_id,
                # If more than planned is being transferred, expand the task's plan
                # so the receiving section can issue and complete the full quantity.
                planned_quantity=lazy_planned_quantity,
                status=WorkTaskStatus.waiting_previous,
                due_date=next_line.due_date,
                dimensions=dimensions,
                **transform_fields,
            )
            db.add(to_task)
            await db.flush()
            # Cache refreshed automatically via StockProjectionManager

    if from_task.product_id != to_task.product_id:
        raise ValueError("Transfer tasks must have same product")

    to_line = await db.get(SectionPlanLine, to_task.section_plan_line_id)
    if to_line is None or from_line.plan_position_id != to_line.plan_position_id:
        raise ValueError("Transfer tasks must belong to same plan position")

    from_stage = await _get_route_stage(db, from_task.route_stage_id)
    to_stage = await _get_route_stage(db, to_task.route_stage_id)
    if to_stage.sequence <= from_stage.sequence:
        raise ValueError("Transfer target must be next route step")

    if not post_factum and not allow_over_plan:
        transferable = await _get_task_transferable(db, from_task, dimensions=dimensions)
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
        dimensions=dimensions,
    )
    db.add(transfer)
    await db.flush()

    eff_executor = executor_user_id or actor_id
    actor_name = await _get_user_snapshot_name(db, actor_id)
    executor_name = await _get_user_snapshot_name(db, eff_executor)

    # Auto-accept: since the operator confirms the transfer on the
    # /transfers page, the material is considered immediately received
    # on the destination. The destination task transitions
    # ``waiting_previous -> ready``. Reject/partial accept are no longer
    # part of the model — see
    # ``docs/superpowers/plans/2026-07-01-explicit-transfers-mandatory.md``.
    transfer.status = TransferStatus.accepted
    transfer.accepted_quantity = quantity
    transfer.accepted_by = actor_id
    transfer.accepted_at = eff_accounted
    if to_task.status == WorkTaskStatus.waiting_previous:
        to_task.status = WorkTaskStatus.ready
        await db.flush()

    # ─── StockTransaction ledger (Этап 2) ─────────────────────────────────
    # Пишем две транзакции — TRANSFER_SEND (на исходной задаче) и
    # TRANSFER_RECEIVE (на приёмной). StockCommandService.record()
    # вызывает StockProjectionManager, который обновляет баланс и
    # cached_transferred_quantity / cached_received_quantity.
    send_tx = await _record_transfer_send_stock_tx(
        db,
        transfer=transfer,
        from_task=from_task,
        to_task=to_task,
        quantity=quantity,
        dimensions=dimensions,
        actor_id=actor_id,
        executor_user_id=eff_executor,
        actor_name=actor_name,
        executor_name=executor_name,
        source_ref=source_ref,
        comment=comment,
        idempotency_key=idempotency_key,
        performed_at=eff_performed,
        accounted_at=eff_accounted,
        is_post_factum=post_factum,
    )
    # TRANSFER_RECEIVE на приёмную задачу (только task-level; без локаций)
    receive_comment = await enrich_comment_with_route_operations(
        db,
        comment,
        route_id=from_line.route_id,
        through_sequence=from_stage.sequence,
    )
    receive_tx = await _stock_command_service.record(
        db,
        StockCommand(
            product_id=transfer.product_id,
            quantity=quantity,
            reason=Reason.TRANSFER_RECEIVE,
            from_location_id=None,
            to_location_id=None,
            dimensions=dimensions,
            task_id=to_task.id,
            transfer_id=transfer.id,
            section_plan_line_id=to_task.section_plan_line_id,
            created_by=actor_id,
            executor_user_id=eff_executor,
            created_by_user_name=actor_name,
            executor_user_name=executor_name,
            source_ref=source_ref,
            comment=receive_comment,
            idempotency_key=f"{idempotency_key}:stock-receive" if idempotency_key else None,
            performed_at=eff_performed,
            accounted_at=eff_accounted,
            is_post_factum=post_factum,
        ),
    )

    # Stock section FIFO consumption was removed — SpgRemainder table no longer exists.
    # Stock balance is updated atomically via StockCommandService.record() above.

    # Auto-issue on receive: no more cached_* columns (Этап 4).
    # StockTransaction ledger is the source of truth for issued quantity.
    await db.flush()

    await _refresh_section_plan_line_cache(db, from_task.section_plan_line_id)
    await _refresh_section_plan_line_cache(db, to_task.section_plan_line_id)

    from app.services.shopfloor.task_status import sync_work_task_status

    from_task_after = await db.get(WorkTask, from_task.id)
    to_task_after = await db.get(WorkTask, to_task.id)
    if from_task_after:
        await sync_work_task_status(db, from_task_after)
    if to_task_after:
        await sync_work_task_status(db, to_task_after)

    # If cumulative received quantity now exceeds the task's planned quantity
    # (i.e., over-plan material was transferred), expand planned_quantity so
    # operators can issue and complete the full received amount at this stage.
    from app.stock.services import StockProjectionManager
    pm = StockProjectionManager()
    to_cache = await pm.get_task_cache(db, to_task.id)
    to_task_after = await db.get(WorkTask, to_task.id)
    if to_task_after and to_cache["received_quantity"] > to_task_after.planned_quantity:
        to_task_after.planned_quantity = to_cache["received_quantity"]
        await db.flush()
        await _refresh_section_plan_line_cache(db, to_task_after.section_plan_line_id)

    # Запись лога аудита (передача)
    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction, AuditEntityType
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
    transferable = (
        await _get_task_transferable(db, from_task, dimensions=transfer.dimensions)
        + old_quantity
    )
    if new_quantity > transferable:
        raise ValueError(
            f"Corrected quantity exceeds transferable amount of source task. "
            f"Available to transfer: {transferable}"
        )

    # 2. Validate target limit. With auto-issue on receive, the
    # destination's ``cached_available_quantity`` is 0 by design (received
    # is fully issued on the same transaction). The right guard for a
    # reduce is therefore the in-work balance: how much of the
    # previously-issued quantity has not yet been completed or
    # rejected. If the operator already completed or rejected more
    # than the new sent quantity, reducing the transfer would create
    # a phantom drain.
    from app.stock.services import StockProjectionManager
    pm = StockProjectionManager()
    to_cache = await pm.get_task_cache(db, to_task.id)
    diff = new_quantity - old_quantity
    if diff < 0:
        in_work = (
            to_cache["issued_quantity"]
            - to_cache["completed_quantity"]
            - to_cache["rejected_quantity"]
        )
        if in_work + diff < 0:
            raise ValueError(
                f"Target task has already completed or rejected parts. "
                f"Cannot reduce transfer by {abs(diff)} as target task only has {in_work} in work"
            )

    # 3. Update Transfer
    transfer.sent_quantity = new_quantity
    transfer.accepted_quantity = new_quantity
    if comment:
        transfer.comment = comment

    # Movement-строк больше нет (Этап 2) — quantity синхронизируется
    # только в StockTransaction ниже.
    await db.flush()

    # ─── StockTransaction quantity resync (in-place, controlled) ────────
    # Активные StockTransaction синхронизируются in-place с новым quantity.
    # Контролируемое исключение из append-only; cancel идёт через
    # компенсации, а не через этот путь.
    await _resync_transfer_stock_tx_quantity(
        db, transfer=transfer, new_quantity=new_quantity
    )

    # 5. Refresh cache (projections updated via StockTransaction)
    active_txs = (await db.execute(
        select(StockTransaction)
        .where(
            StockTransaction.transfer_id == transfer.id,
            StockTransaction.compensates_tx_id.is_(None),
        )
        .limit(1)
    )).scalars().all()
    for atx in active_txs:
        await _stock_command_service._projection_manager.refresh_task_projection(db, atx)
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

    # Validate target in-work quantity before cancellation.
    # Target has received material via transfer_receive which is effectively
    # material available for work (on-section balance). Use received_quantity
    # as the guard since issued_quantity is no longer auto-incremented
    # after cached_* columns were removed (Этап 4).
    from app.stock.services import StockProjectionManager
    pm = StockProjectionManager()
    to_cache = await pm.get_task_cache(db, to_task.id)
    in_work = (
        to_cache["issued_quantity"]
        - to_cache["completed_quantity"]
        - to_cache["rejected_quantity"]
    )
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

    # SpgRemainder restoration removed — table no longer exists.
    await db.flush()

    # ─── StockTransaction compensation (append-only) ─────────────────────
    # Создаём встречные компенсационные записи с перевёрнутыми локациями
    # и compensates_tx_id → исходная. Баланс возвращается к нулю.
    # Компенсация вызывает stock_changed → refresh_task_projection (net = 0).
    await _compensate_transfer_stock_tx(
        db, transfer=transfer, actor_id=actor_id, comment=comment
    )
    # Refresh projections (net = 0 после компенсации — обновлено через StockTransaction)
    comp_txs = (await db.execute(
        select(StockTransaction)
        .where(
            StockTransaction.transfer_id == transfer.id,
            StockTransaction.reason.in_([Reason.TRANSFER_SEND, Reason.TRANSFER_RECEIVE]),
        )
        .limit(2)
    )).scalars().all()
    for ctx in comp_txs:
        await _stock_command_service._projection_manager.refresh_task_projection(db, ctx)
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
    """Create automatic cross-GHP Transfers for the completed ``good_quantity``.

    Walks the route forward from the completed task's SectionPlanLine.
    For each cross-GHP boundary a ``transfer_send`` is emitted as a
    regular (non post-factum) transfer: it is created atomically at
    completion time with current timestamps.  When a transit stage sits
    between two production stages in different GHPs, a chain of transfers
    is created (production → transit → next production).

    Трансформирующее задание (резка, тикет #91): создаётся по передаче
    **на каждый выход** спецификации — со своим размером и количеством
    (произведённое по размеру, не больше выхода), а не одна передача на
    задачу. Возвращает результат **первой** ``transfer_send`` (или ``None``,
    когда хелпер решает пропустить).
    """
    from app.models.internal_plan import SectionPlanLine
    from app.models.route import RouteStage
    from app.services.shopfloor.common import sections_share_spg

    from_line = await db.get(SectionPlanLine, from_task.section_plan_line_id)
    if from_line is None:
        return None

    if good_quantity <= 0:
        return None

    # Пары (количество, размер) для передачи. Резка — по выходу на каждый
    # размер: количество = произведённое по размеру (не больше выхода) минус
    # уже переданное по этому размеру (инвариант D2). Произведённое и
    # переданное распределяются по строкам одного размера последовательно
    # (как в ready-строках) — иначе два выхода одного размера дважды
    # использовали бы один бюджет. Обычный этап — одна передача на
    # good_quantity с габаритом задания.
    if from_task.outputs:
        from app.domain.dimensions import canonicalize_dimensions
        from app.services.shopfloor.operations_transform import (
            build_outputs_progress,
            distribute_output_quantities,
            get_transform_progress,
        )
        from app.stock.services import _dimensions_hash_key

        progress = await get_transform_progress(db, from_task.id)
        produced_rows = build_outputs_progress(
            from_task.outputs, progress.produced_by_group
        )
        transferred_by_dim: dict[str | None, Decimal] = {}
        for entry in from_task.outputs:
            dims = canonicalize_dimensions(entry.get("dimensions"))
            key = _dimensions_hash_key(dims)
            if key not in transferred_by_dim:
                transferred_by_dim[key] = await net_transferred(
                    db, task_id=from_task.id, dims=dims
                )
        transferred_rows = distribute_output_quantities(
            from_task.outputs, transferred_by_dim
        )

        pairs: list[tuple[Decimal, dict | None]] = []
        for entry, produced_entry, transferred in zip(
            from_task.outputs, produced_rows, transferred_rows
        ):
            raw_qty = entry.get("quantity")
            if raw_qty is None:
                continue
            planned = Decimal(str(raw_qty))
            if planned <= 0:
                continue
            dims = canonicalize_dimensions(entry.get("dimensions"))
            qty = max(Decimal("0"), produced_entry["produced_quantity"] - transferred)
            if qty > 0:
                pairs.append((qty, dims))
    else:
        pairs = [(_to_decimal(good_quantity), None)]

    if not pairs:
        return None

    first_result = None
    current_task = from_task

    while True:
        current_line = await db.get(SectionPlanLine, current_task.section_plan_line_id)
        if current_line is None:
            break

        next_line = await db.scalar(
            select(SectionPlanLine).where(
                SectionPlanLine.plan_position_id == current_line.plan_position_id,
                SectionPlanLine.sequence == current_line.sequence + 1,
            )
        )
        if next_line is None:
            break

        current_stage = await db.get(RouteStage, current_line.route_stage_id)
        if current_stage is None:
            break

        current_section_id = (
            current_stage.storage_section_id
            if current_stage.is_transit
            else current_line.section_id
        )

        if await sections_share_spg(db, current_section_id, next_line.section_id):
            break

        next_stage = await db.get(RouteStage, next_line.route_stage_id)
        if next_stage is None:
            break

        next_task = await db.scalar(
            select(WorkTask).where(
                WorkTask.section_plan_line_id == next_line.id,
                WorkTask.status.notin_([WorkTaskStatus.completed, WorkTaskStatus.cancelled]),
            )
        )
        if next_task is None and not next_stage.is_transit:
            break

        step_idx = next_line.sequence - from_line.sequence
        for pair_idx, (qty, dims) in enumerate(pairs):
            key = (
                f"{idempotency_key}:auto-transfer-complete:{step_idx}:{pair_idx}"
                if idempotency_key
                else None
            )

            result = await transfer_send(
                db,
                from_task_id=current_task.id,
                to_task_id=next_task.id if next_task else None,
                quantity=qty,
                actor_id=actor_id,
                comment=comment or "Авто-перемещение после завершения",
                idempotency_key=key,
                dimensions=dims,
            )

            if first_result is None:
                first_result = result

        if not next_stage.is_transit:
            break

        if next_task is not None:
            current_task = next_task
        else:
            created_task = await db.scalar(
                select(WorkTask).where(
                    WorkTask.section_plan_line_id == next_line.id,
                    WorkTask.status.notin_([WorkTaskStatus.completed, WorkTaskStatus.cancelled]),
                )
            )
            if created_task is None:
                break
            current_task = created_task

    return first_result


# NOTE: auto_create_transfer_from_stock_to_production был удалён.
# Под новой моделью (Send = auto-accept, никаких auto-flows на issue) —
# оператор сам явно отправляет передачу со склада через /transfers.
# Если хелпер понадобится снова — он делал send+receive, что теперь
# сводится к одному transfer_send (он сам auto-accept'ит).
