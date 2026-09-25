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

Cancel/correct идут через домен отката (тикет #124, ADR-0019):
``cancel_transfer`` → ``ReversalService.reverse``, ``correct_transfer``
→ ``ReversalService.amend`` исходного ``transfer_send``. Зеркальные
проводки строит только ``MirrorLedgerMixin`` за реестром
``ReversalService`` — здесь ручных построений нет.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.idempotency import raise_idempotency_conflict_on_violation
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
    _require_mutable_task,
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
from app.services.action_journal_service import action_journal_service
from app.stock.models import QualityState, Reason, StockTransaction
from app.stock.services import (
    StockCommand,
    StockCommandService,
    dimensions_match_clause,
)
from app.services.shopfloor.output_rows import (
    UsedSource,
    build_task_output_rows,
)
from app.transfers.transferable import task_transferable

_stock_command_service = StockCommandService()


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
    action_id: int | None,
    is_post_factum: bool,
    quality_state: QualityState = QualityState.GOOD,
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
            quality_state=quality_state,
            task_id=from_task.id,
            transfer_id=transfer.id,
            section_plan_line_id=from_task.section_plan_line_id,
            action_id=action_id,
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


async def _find_transfer_send_action(
    db: AsyncSession, transfer_id: int,
) -> "Action | None":
    """Актуальный активный ``transfer_send`` Action для Transfer.

    У живого Transfer запись одна; ``order_by(id desc)`` — защита на
    случай будущих повторных отправок по тому же ref_id (берём последнюю
    ACTIVE). ``None`` = записи нет (legacy-данные до журнала) или она уже
    отменена/amend'нута.
    """
    from app.models.action_journal import Action, ActionStatus

    return (
        await db.execute(
            select(Action)
            .where(
                Action.action_type == "transfer_send",
                Action.ref_id == transfer_id,
                Action.status == ActionStatus.ACTIVE,
            )
            .order_by(Action.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


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
    action: "Action | None" = None,
    quality_state: QualityState = QualityState.GOOD,
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
    from_task = await _get_task(db, from_task_id)
    await _require_mutable_task(db, from_task)
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
    await _require_mutable_task(db, from_task)
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
                dimensions_match_clause(WorkTask.dimensions, dimensions),
            )
        )
        if existing_task:
            to_task = existing_task
        else:
            # Трансформирующий этап несёт вход/выходы позиции (ADR-0002)
            from app.services.route_transform import transform_fields_for_task

            # Each output dimension is an independent receiving task. A
            # pre-created task from the plan can represent only one dimension;
            # never reuse it for a different output.
            lazy_planned_quantity = quantity
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
        # Лимит источника — публичный шов глубокого модуля transferable (#131):
        # тот же интерфейс, что читают гидраторы ready-page.
        transferable = await task_transferable(db, from_task, dimensions=dimensions)
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
    try:
        await db.flush()
    except IntegrityError as exc:
        # Гонка идемпотентности (ADR-0022, тикет #135): конкурент провёл
        # transfer_send с тем же ключом между нашим replay-SELECT и flush.
        # Отклоняем подачу целиком (409): задача/ledger/кэши в этой же
        # внешней транзакции откатываются вместе с ней; повтор с тем же
        # ключом попадает в replay-ветку выше.
        raise_idempotency_conflict_on_violation(
            exc, index_name="uq_transfers_idempotency_key",
            entity="transfer", idempotency_key=idempotency_key,
        )

    eff_executor = executor_user_id or actor_id
    actor_name = await _get_user_snapshot_name(db, actor_id)
    executor_name = await _get_user_snapshot_name(db, eff_executor)

    # Журнал действий (ADR-0019, #113): одна операция = одна запись Action;
    # обе проводки ledger ссылаются на неё через action_id. При amend
    # (#115) запись уже создана ReversalService — реюзируем её, чтобы
    # компенсации старого действия и новая пара проводок делили один
    # action_id; иначе создаём новую запись журнала.
    if action is None:
        action = await action_journal_service.log(
            db,
            action_type="transfer_send",
            ref_id=transfer.id,
            actor=actor_name,
        )

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
        action_id=action.id,
        quality_state=quality_state,
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
            quality_state=quality_state,
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
            action_id=action.id,
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
    """Коррекция количества передачи через ``ReversalService.amend`` (тикет #124).

    ADR-0019: ledger append-only. Старый ``Transfer`` получает статус
    ``amended`` (без мутации ``sent_quantity``); новая пара SEND/RECEIVE
    создаётся под новым ``Transfer`` через ``StockCompensator.apply_forward``
    (``transfer_send``). Доменные guard'ы (source/target лимиты)
    остаются в caller.

    API-контракт (breaking, тикет #124): возвращает ``new_transfer_id``
    (голова amend-цепочки) и ``amended_transfer_id`` (списанный Transfer).
    """
    from app.reversal.errors import AlreadyReversed, CoverageShortfall, NotAllowed, StalePlanToken
    from app.reversal.service import ReversalService

    transfer = await _get_transfer(db, transfer_id)
    if transfer.status == TransferStatus.amended:
        raise ValueError(
            "This transfer was superseded by an amend; operate on the new transfer"
        )
    if transfer.status != TransferStatus.accepted:
        raise ValueError("Only accepted transfers can be corrected")

    new_quantity = _to_decimal(new_quantity)
    _ensure_positive(new_quantity, "quantity")

    old_quantity = transfer.sent_quantity
    if new_quantity == old_quantity:
        return {
            "new_transfer_id": transfer.id,
            "amended_transfer_id": None,
            "status": transfer.status.value,
            "quantity": str(transfer.sent_quantity),
        }

    from_task = await _get_task(db, transfer.from_task_id)
    to_task = await _get_task(db, transfer.to_task_id)
    await _require_mutable_task(db, from_task)

    # 1. Domain-guard: источник имеет достаточно transferable (с учётом
    # возврата старого количества после компенсации). Лимит — через модуль
    # transferable (#131), как и в transfer_send.
    transferable = (
        await task_transferable(db, from_task, dimensions=transfer.dimensions)
        + old_quantity
    )
    if new_quantity > transferable:
        raise ValueError(
            f"Corrected quantity exceeds transferable amount of source task. "
            f"Available to transfer: {transferable}"
        )

    # 2. Domain-guard: приёмная сторона. При reduce (diff < 0) — in_work
    # баланс защищает от «фантомного» слива уже завершённого/отклонённого.
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

    # 3. Найти исходный transfer_send Action; без него amend невозможен.
    send_action = await _find_transfer_send_action(db, transfer.id)
    if send_action is None:
        raise ValueError(
            f"Transfer #{transfer.id}: исходное действие transfer_send не найдено или уже отменено"
        )

    # 4. Preview → amend (одна транзакция, preview-first ADR-0019).
    actor_name = await _get_user_snapshot_name(db, actor_id)
    svc = ReversalService()
    changes = {"quantity": str(new_quantity)}
    preview = await svc.preview_amend(db, send_action.id, changes, cascade=True)
    if preview.blockers:
        detail = "; ".join(b.detail for b in preview.blockers)
        raise ValueError(f"correct_transfer blocked: {detail}")
    assert preview.plan_token is not None  # блокеров нет → токен выдан
    try:
        amend_result = await svc.amend(
            db,
            send_action.id,
            changes=changes,
            plan_token=preview.plan_token,
            reason=comment,
            actor=actor_name,
            actor_id=actor_id,
        )
    except (CoverageShortfall, NotAllowed, StalePlanToken, AlreadyReversed) as exc:
        # Маппинг reversal-исключений → ValueError для API-слоя (400).
        raise ValueError(str(exc)) from exc

    # 5. Append-only: старый Transfer → ``amended`` (без мутации sent_quantity).
    transfer.status = TransferStatus.amended
    if comment:
        transfer.comment = comment
    await db.flush()

    # 6. Refresh проекций/кэшей для обеих сторон (отправка + приём).
    await _refresh_section_plan_line_cache(db, from_task.section_plan_line_id)
    await _refresh_section_plan_line_cache(db, to_task.section_plan_line_id)

    # 7. Audit log.
    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction, AuditEntityType
    from app.models.product import Product
    from app.models.section import Section

    from_section = await db.get(Section, transfer.from_section_id)
    to_section = await db.get(Section, transfer.to_section_id)
    product = await db.get(Product, transfer.product_id)
    await log_action(
        db,
        status="success",
        title="Корректировка передачи (amend)",
        message=(
            f"Передача #{transfer.transfer_no} скорректирована (amend). "
            f"Количество изменено с {old_quantity} на {new_quantity} шт."
        ),
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
        changes={
            "before": {"quantity": str(old_quantity)},
            "after": {"quantity": str(new_quantity), "new_transfer_id": amend_result.new_ref_id},
        },
    )

    return {
        "new_transfer_id": amend_result.new_ref_id,
        "amended_transfer_id": transfer.id,
        "status": "amended",
        "quantity": str(new_quantity),
    }


async def cancel_transfer(
    db: AsyncSession,
    *,
    transfer_id: int,
    actor_id: int,
    comment: str | None = None,
) -> dict:
    """Отмена передачи через ``ReversalService.reverse`` (тикет #124).

    Зеркальные проводки создаёт ``StockCompensator`` (``MirrorLedgerMixin``);
    ``transfer.status=cancelled`` и ``accepted_quantity=0`` ставит его
    ``apply`` — caller здесь их не пишет. Domain-guard ``in_work``
    (приёмная сторона уже завершила часть) — предварительная проверка
    до вызова reverse.
    """
    from app.reversal.errors import AlreadyReversed, CoverageShortfall, NotAllowed, StalePlanToken
    from app.reversal.service import ReversalService

    transfer = await _get_transfer(db, transfer_id)
    if transfer.status == TransferStatus.cancelled:
        return {
            "transfer_id": transfer.id,
            "status": transfer.status.value,
        }
    if transfer.status == TransferStatus.amended:
        raise ValueError(
            "This transfer was superseded by an amend; cancel the new transfer instead"
        )
    if transfer.status != TransferStatus.accepted:
        raise ValueError("Only accepted transfers can be cancelled")

    from_task = await _get_task(db, transfer.from_task_id)
    to_task = await _get_task(db, transfer.to_task_id)
    await _require_mutable_task(db, from_task)

    # Domain-guard: приёмная сторона не должна иметь завершённых/отклонённых
    # частей сверх sent_quantity; иначе cancel создал бы отрицательный баланс.
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

    # Найти исходный transfer_send Action; без него reverse невозможен.
    send_action = await _find_transfer_send_action(db, transfer.id)
    if send_action is None:
        # Transfer принят, но активного действия нет: legacy-запись до
        # журнала действий либо гонка с другой транзакцией. Тихий no-op
        # здесь солгал бы об успехе — требуем явного разбора.
        raise ValueError(
            f"Transfer #{transfer.id}: исходное действие transfer_send не найдено "
            f"(уже отменено или запись до внедрения журнала действий)"
        )

    # Preview → reverse (preview-first ADR-0019).
    actor_name = await _get_user_snapshot_name(db, actor_id)
    svc = ReversalService()
    preview = await svc.preview_reverse(db, send_action.id, cascade=True)
    if preview.blockers:
        detail = "; ".join(b.detail for b in preview.blockers)
        raise ValueError(f"cancel_transfer blocked: {detail}")
    assert preview.plan_token is not None
    try:
        await svc.reverse(
            db,
            send_action.id,
            plan_token=preview.plan_token,
            reason=comment,
            actor=actor_name,
            actor_id=actor_id,
        )
    except AlreadyReversed:
        # Идемпотентность: другой транзакцией уже отменено.
        pass
    except (CoverageShortfall, NotAllowed, StalePlanToken) as exc:
        raise ValueError(str(exc)) from exc

    # Обновить комментарий после компенсации (status/accepted_quantity
    # выставил StockCompensator.apply).
    await db.refresh(transfer)
    if comment:
        transfer.comment = comment
    await db.flush()

    # Refresh проекций/кэшей после компенсации (net=0).
    await _refresh_section_plan_line_cache(db, from_task.section_plan_line_id)
    await _refresh_section_plan_line_cache(db, to_task.section_plan_line_id)

    # Audit log (отмена передачи).
    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction, AuditEntityType
    from app.models.product import Product
    from app.models.section import Section

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
        rows = await build_task_output_rows(
            db,
            task_id=from_task.id,
            outputs=from_task.outputs,
            used_source=UsedSource.NET_TRANSFERRED,
        )
        pairs: list[tuple[Decimal, dict | None]] = [
            (row_out.remaining_quantity, row_out.dimensions)
            for row_out in rows
            if row_out.remaining_quantity > 0
        ]
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

        next_task = None
        if next_stage.is_transit:
            next_task = await db.scalar(
                select(WorkTask).where(
                    WorkTask.section_plan_line_id == next_line.id,
                    WorkTask.status.notin_([WorkTaskStatus.completed, WorkTaskStatus.cancelled]),
                )
            )
        step_idx = next_line.sequence - from_line.sequence
        for pair_idx, (qty, dims) in enumerate(pairs):
            key = (
                f"{idempotency_key}:auto-transfer-complete:{step_idx}:{pair_idx}"
                if idempotency_key
                else None
            )
            target_task = next_task
            if not next_stage.is_transit:
                target_task = await db.scalar(
                    select(WorkTask).where(
                        WorkTask.section_plan_line_id == next_line.id,
                        WorkTask.status.notin_([WorkTaskStatus.completed, WorkTaskStatus.cancelled]),
                        dimensions_match_clause(WorkTask.dimensions, dims),
                    )
                )

            result = await transfer_send(
                db,
                from_task_id=current_task.id,
                to_task_id=target_task.id if target_task is not None else None,
                quantity=qty,
                actor_id=actor_id,
                comment=comment or "Авто-перемещение после завершения",
                idempotency_key=key,
                dimensions=dims,
            )

            if first_result is None:
                first_result = result

            if result.get("to_task_id") is not None:
                receiving_task = await db.get(WorkTask, int(result["to_task_id"]))
                if receiving_task is not None:
                    receiving_task.planned_quantity = qty
                    await db.flush()

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
