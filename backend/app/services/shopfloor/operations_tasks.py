from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import Defect, DefectItem, DefectStatus
from app.models.internal_plan import SectionPlanLine
from app.models.production_plan import PlanPosition, PlanPositionStatus
from app.models.work_task import WorkTask, WorkTaskStatus
from app.stock import QualityState, Reason, StockBalance, StockCommand, StockCommandService

from .common import _check_idempotency, _ensure_positive, _get_route_stage, _get_task, _get_user_snapshot_name, _to_decimal
from .cache import _refresh_section_plan_line_cache

ISSUE_ALLOWED_STATUSES = {
    WorkTaskStatus.ready,
    WorkTaskStatus.in_progress,
    WorkTaskStatus.partially_completed,
}


async def _get_stock_location(session: AsyncSession, section_id: int) -> int | None:
    """Find the stock (RAW / WIP / FINISHED) location corresponding to a production section.

    Walks up the RouteStages to find the preceding non-production section.
    For the first production stage, returns the RAW_STOCK;
    for subsequent stages, returns WIP_STOCK of the same SPG.
    Returns None if no stock location is found (falls back to the section itself).
    """
    from app.models.route import RouteStage
    from app.models.section import Section

    # Check if the section itself is a stock location
    sec = await session.get(Section, section_id)
    if sec is not None and sec.kind != "production":
        return section_id

    # Find the preceding stock stage in the route
    wt = await session.scalar(
        select(WorkTask).where(WorkTask.section_id == section_id).limit(1)
    )
    if wt is None:
        return None

    line = await session.get(SectionPlanLine, wt.section_plan_line_id)
    if line is None:
        return None

    # Find preceding non-production section
    prev_lines = (
        await session.execute(
            select(SectionPlanLine)
            .where(
                SectionPlanLine.plan_position_id == line.plan_position_id,
                SectionPlanLine.sequence < line.sequence,
            )
            .order_by(SectionPlanLine.sequence.desc())
        )
    ).scalars().all()

    for prev in prev_lines:
        prev_sec = await session.get(Section, prev.section_id)
        if prev_sec is not None and prev_sec.kind != "production":
            return prev.section_id

    return None


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
    from_location_id: int | None = None,
    shortage_strategy: Literal["fail", "partial", "force"] = "partial",
    auto_consume: bool = False,
) -> dict:
    """Issue material to a work task.

    Uses StockTransaction ledger (no Movement, no SpgRemainder).
    Stock availability is checked via StockBalance.
    ``auto_consume=True`` allows issuing whatever is available without hard-fail.
    ``shortage_strategy='force'`` bypasses stock check (for manual pass etc.).
    """
    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")

    if idempotency_key:
        from app.stock.models import StockTransaction
        existing = await _check_idempotency(db, idempotency_key=idempotency_key, entity_type=StockTransaction)
        if existing is not None:
            task = await _get_task(db, task_id)
            return {"transaction_id": existing.id, "task_id": task.id, "status": task.status.value, "idempotent_replay": True}

    task = await _get_task(db, task_id)
    if task.status not in ISSUE_ALLOWED_STATUSES:
        is_first_active = False
        if task.status == WorkTaskStatus.waiting_previous:
            line = await db.get(SectionPlanLine, task.section_plan_line_id)
            if line is not None:
                preceding_has_task = await db.scalar(
                    select(func.count(WorkTask.id))
                    .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
                    .where(
                        SectionPlanLine.plan_position_id == line.plan_position_id,
                        SectionPlanLine.sequence < line.sequence,
                        WorkTask.status.notin_([WorkTaskStatus.cancelled])
                    )
                ) > 0
                if not preceding_has_task:
                    is_first_active = True

        if not is_first_active:
            if task.status == WorkTaskStatus.waiting_previous:
                raise ValueError("Нельзя выдать в работу задание, ожидающее передачи сырья с предыдущего участка")
            raise ValueError("Task must be ready/in_progress/partially_completed")

    # Determine from_location (stock) if not provided
    from_loc = from_location_id
    if shortage_strategy == "force":
        # Force issue: material appears at the task section from nowhere
        from_loc = None
    else:
        if from_loc is None:
            from_loc = await _get_stock_location(db, task.section_id)
        if from_loc is None:
            from_loc = task.section_id

        # Check availability via StockBalance
        available = await db.scalar(
            select(func.coalesce(func.sum(StockBalance.balance_qty), 0))
            .where(
                StockBalance.product_id == task.product_id,
                StockBalance.location_id == from_loc,
                StockBalance.quality_state == QualityState.good,
            )
        ) or Decimal("0")

        if quantity > available:
            if shortage_strategy == "fail":
                raise ValueError(f"Недостаточно доступного количества (доступно: {available}, запрошено: {quantity})")
            elif shortage_strategy == "partial":
                quantity = min(quantity, available)
                if quantity <= 0:
                    raise ValueError("Доступное количество равно 0. Нечего брать в работу.")
            # auto_consume: use what's available without error

    svc = StockCommandService()
    tx = await svc.record(db, StockCommand(
        product_id=task.product_id,
        from_location_id=from_loc,
        to_location_id=task.section_id,
        quantity=quantity,
        reason=Reason.issue_to_work,
        task_id=task.id,
        transfer_id=transfer_id,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        comment=comment,
        created_by=actor_id,
        executor_user_id=executor_user_id or actor_id,
        performed_at=performed_at or datetime.now(UTC),
        accounted_at=accounted_at or datetime.now(UTC),
    ))

    task.status = WorkTaskStatus.in_progress
    await db.flush()
    await _refresh_section_plan_line_cache(db, task.section_plan_line_id)

    return {"transaction_id": tx.id, "task_id": task.id, "status": task.status.value}


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
    shortage_strategy: Literal["fail", "partial"] = "partial",
    auto_transfer_next: bool = False,
) -> dict:
    """Complete (good + defect) quantity on a SectionTask.

    Writes StockTransaction(COMPLETE) for good output and
    StockTransaction(SCRAP) for defect. Creates Defect/DefectItem
    for traceability. Stock cache is updated automatically via
    StockProjectionManager.
    """
    task = await _get_task(db, task_id)

    if idempotency_key:
        from app.stock.models import StockTransaction as _ST
        existing = await _check_idempotency(db, idempotency_key=idempotency_key, entity_type=_ST)
        if existing is not None:
            reject_movement_key = f"{idempotency_key}:reject"
            existing_defect = await db.scalar(
                select(Defect).where(Defect.idempotency_key == reject_movement_key)
            )
            return {
                "task_id": task.id,
                "transaction_ids": [existing.id],
                "defect_id": existing_defect.id if existing_defect else None,
                "status": task.status.value,
                "idempotent_replay": True,
            }

    if task.status not in {WorkTaskStatus.in_progress, WorkTaskStatus.partially_completed, WorkTaskStatus.ready}:
        if task.status == WorkTaskStatus.waiting_previous:
            raise ValueError("Нельзя завершить задание, так как оно ожидает передачи сырья с предыдущего участка")
        raise ValueError("Task must be in progress")

    good_quantity = _to_decimal(good_quantity)
    defect_quantity = _to_decimal(defect_quantity)
    if good_quantity < 0 or defect_quantity < 0:
        raise ValueError("Quantities must be >= 0")
    total = good_quantity + defect_quantity
    _ensure_positive(total, "good_quantity + defect_quantity")

    from app.stock.services import StockProjectionManager
    pm = StockProjectionManager()
    cache = await pm.get_task_cache(db, task.id)
    in_work = cache["issued_quantity"] - cache["completed_quantity"] - cache["rejected_quantity"]
    if total > in_work:
        raise ValueError("Complete quantity exceeds issued quantity")

    now = datetime.now(UTC)
    eff_performed = performed_at or now
    eff_accounted = accounted_at or now
    eff_executor = executor_user_id or actor_id

    svc = StockCommandService()
    tx_ids: list[int] = []
    defect_id: int | None = None

    if good_quantity > 0:
        # complete: good output appears on the section (from nowhere)
        tx_good = await svc.record(db, StockCommand(
            product_id=task.product_id,
            from_location_id=None,
            to_location_id=task.section_id,
            quantity=good_quantity,
            reason=Reason.complete,
            quality_state=QualityState.good,
            task_id=task.id,
            source_ref=source_ref,
            idempotency_key=idempotency_key,
            comment=comment,
            created_by=actor_id,
            executor_user_id=eff_executor,
            performed_at=eff_performed,
            accounted_at=eff_accounted,
        ))
        tx_ids.append(tx_good.id)

    if defect_quantity > 0:
        # scrap: from production section to scrap location
        from app.models.section import Section as _Section
        scrap_loc = await db.scalar(
            select(_Section.id).where(_Section.type == "scrap").limit(1)
        )
        if scrap_loc is None:
            scrap_sec = _Section(
                code="SCRAP",
                name="Scrap",
                kind="storage",
                type="scrap",
                is_active=True,
                sort_order=999,
            )
            db.add(scrap_sec)
            await db.flush()
            scrap_loc = scrap_sec.id

        tx_scrap = await svc.record(db, StockCommand(
            product_id=task.product_id,
            from_location_id=task.section_id,
            to_location_id=scrap_loc,
            quantity=defect_quantity,
            reason=Reason.scrap,
            quality_state=QualityState.good,
            to_quality_state=QualityState.scrap,
            task_id=task.id,
            source_ref=source_ref,
            idempotency_key=f"{idempotency_key}:reject" if idempotency_key else None,
            comment=comment,
            created_by=actor_id,
            executor_user_id=eff_executor,
            performed_at=eff_performed,
            accounted_at=eff_accounted,
        ))
        tx_ids.append(tx_scrap.id)

        defect = Defect(
            product_id=task.product_id,
            section_id=task.section_id,
            task_id=task.id,
            stock_transaction_id=tx_scrap.id,
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

    await _refresh_section_plan_line_cache(db, task.section_plan_line_id)

    if auto_transfer_next and good_quantity > 0:
        from app.transfers.services import auto_create_transfer_after_complete
        await auto_create_transfer_after_complete(
            db,
            from_task=task,
            good_quantity=good_quantity,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            comment=comment or "Авто-перемещение после завершения",
        )

    return {"task_id": task.id, "transaction_ids": tx_ids, "defect_id": defect_id, "status": task.status.value}


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
    """Final release of finished goods to finished stock.

    Writes StockTransaction(FINAL_RELEASE). No SpgRemainder or
    compensate_spg_remainders.
    """
    if idempotency_key:
        from app.stock.models import StockTransaction
        existing = await _check_idempotency(db, idempotency_key=idempotency_key, entity_type=StockTransaction)
        if existing is not None:
            return {"transaction_id": existing.id, "task_id": task_id, "idempotent_replay": True}

    task = await _get_task(db, task_id)
    stage = await _get_route_stage(db, task.route_stage_id)
    if not stage.is_final:
        raise ValueError("Final release allowed only for final route stage")

    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")

    # Releasable = completed - already final_released
    from app.stock.models import StockTransaction
    already_released = await db.scalar(
        select(func.coalesce(func.sum(StockTransaction.quantity), 0))
        .where(
            StockTransaction.task_id == task.id,
            StockTransaction.reason == Reason.final_release,
        )
    ) or Decimal("0")

    from app.stock.services import StockProjectionManager
    pm = StockProjectionManager()
    cache = await pm.get_task_cache(db, task.id)
    releasable = cache["completed_quantity"] - already_released
    if quantity > releasable:
        raise ValueError("Final release exceeds releasable quantity")

    # Find finished stock location
    from app.models.section import Section as _FinSection
    finished_stock = await db.scalar(
        select(_FinSection.id)
        .where(_FinSection.type == "finished_stock")
        .limit(1)
    )

    svc = StockCommandService()
    # final_release: from production section to finished stock (or None if not found)
    tx = await svc.record(db, StockCommand(
        product_id=task.product_id,
        from_location_id=task.section_id if finished_stock else task.section_id,
        to_location_id=finished_stock,
        quantity=quantity,
        reason=Reason.final_release,
        task_id=task.id,
        source_ref=None,
        idempotency_key=idempotency_key,
        comment=comment,
        created_by=actor_id,
        executor_user_id=executor_user_id or actor_id,
        performed_at=performed_at or datetime.now(UTC),
        accounted_at=accounted_at or datetime.now(UTC),
    ))

    await _refresh_section_plan_line_cache(db, task.section_plan_line_id)

    # Запись лога аудита (финальный выпуск)
    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction, AuditEntityType

    from app.models.section import Section as _SecAudit
    section = await db.get(_SecAudit, task.section_id)
    from app.models.product import Product
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

    return {"transaction_id": tx.id, "task_id": task.id}


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

    pos = await db.get(PlanPosition, plan_position_id)
    if pos is None:
        raise ValueError("Plan position not found")
    if pos.status != PlanPositionStatus.released:
        raise ValueError("Plan position must be released")

    line = await db.scalar(
        select(SectionPlanLine).where(
            SectionPlanLine.plan_position_id == plan_position_id,
            SectionPlanLine.section_id == section_id,
        )
    )
    if line is None:
        raise ValueError("No route step found for this section in the plan position")

    from app.models.section import Section as _Section
    sec_meta = await db.get(_Section, line.section_id)
    if sec_meta is not None and sec_meta.kind != "production":
        return {
            "task_id": None,
            "status": "skipped_storage_section",
            "section_kind": sec_meta.kind,
        }

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
    # Auto-consume removed — use issue_to_work(auto_consume=True) explicitly
    await _refresh_section_plan_line_cache(db, task.section_plan_line_id)
    return {"task_id": task.id, "status": task.status.value}
