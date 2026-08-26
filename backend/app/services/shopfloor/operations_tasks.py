from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import Defect, DefectItem, DefectStatus
from app.models.internal_plan import SectionPlanLine
from app.models.production_plan import PlanPosition, PlanPositionStatus
from app.models.route import RouteStage
from app.models.work_task import WorkTask, WorkTaskStatus
from app.seeds.canon.models import ScrapPolicy
from app.services.plan_position_hanger import position_dimensions_for_task
from app.services.action_journal_service import action_journal_service
from app.stock import QualityState, Reason, StockCommand, StockCommandService

from .common import (
    _check_idempotency,
    _ensure_positive,
    _get_route_stage,
    _get_task,
    _get_user_snapshot_name,
    _to_decimal,
    enrich_comment_with_route_operations,
)
from .cache import _refresh_section_plan_line_cache
from . import send_budget
from .operations_transform import (
    TransformProgress,
    TransformSpec,
    get_transform_progress,
    record_transform_portion,
    resolve_consume_dimensions,
    resolve_transform_spec,
)
from .scrap_policy import find_or_create_scrap_section_id


async def _get_stock_location(session: AsyncSession, section_id: int) -> int | None:
    """Find the stock (RAW / WIP / FINISHED) location corresponding to a production section.

    Walks up the RouteStages to find the preceding non-production section.
    For the first production stage, returns the RAW_STOCK;
    for subsequent stages, returns WIP_STOCK of the same SPG.
    Returns None if no stock location is found (falls back to the section itself).
    """
    from app.models.route import RouteStage
    from app.models.section import Section
    from app.services.route_storage_classifier import is_production_section

    # Check if the section itself is a stock location
    sec = await session.get(Section, section_id)
    if sec is not None and not is_production_section(sec):
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
        if prev_sec is not None and not is_production_section(prev_sec):
            return prev.section_id

    return None


class _TransformPlan(NamedTuple):
    """Резолв трансформирующего этапа для одной порции завершения.

    Собирается один раз до проводок; этапы-функции получают план готовым
    и не повторяют резолв сами.
    """

    stage: RouteStage | None
    spec: TransformSpec | None
    progress: TransformProgress | None
    consume_dims: dict | None


def _ensure_task_completable(task: WorkTask) -> None:
    """Статус-guard: завершать можно только активные задания."""
    if task.status not in {WorkTaskStatus.in_progress, WorkTaskStatus.partially_completed, WorkTaskStatus.ready}:
        if task.status == WorkTaskStatus.waiting_previous:
            raise ValueError("Нельзя завершить задание, так как оно ожидает передачи сырья с предыдущего участка")
        raise ValueError("Task must be in progress")


def _normalize_quantities(
    good_quantity: Decimal, defect_quantity: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    """Нормализовать количества порции; вернуть ``(good, defect, total)``."""
    good_quantity = _to_decimal(good_quantity)
    defect_quantity = _to_decimal(defect_quantity)
    if good_quantity < 0 or defect_quantity < 0:
        raise ValueError("Quantities must be >= 0")
    total = good_quantity + defect_quantity
    _ensure_positive(total, "good_quantity + defect_quantity")
    return good_quantity, defect_quantity, total


async def _replay_existing_completion(
    db: AsyncSession, *, task: WorkTask, idempotency_key: str | None,
) -> dict | None:
    """Идемпотентность-replay: проводка по ключу уже есть — дубли в ledger не пишутся."""
    if not idempotency_key:
        return None
    from app.stock.models import StockTransaction as _ST
    existing = await _check_idempotency(db, idempotency_key=idempotency_key, entity_type=_ST)
    if existing is None:
        return None
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


async def _resolve_transform_plan(
    db: AsyncSession, *, task: WorkTask, cache: dict, total: Decimal,
) -> _TransformPlan:
    """Резолв transform-spec и проверка лимитов порции ДО проводок.

    Трансформация определяется маркером этапа и спецификацией задания,
    никогда — кодом секции (factory-agnostic core). Лимиты: на
    трансформирующем этапе нельзя раскроить больше нераскроенного входа
    по спецификации, на обычном — завершить больше выданного в работу.
    """
    stage = None
    if task.route_stage_id is not None:
        stage = await db.get(RouteStage, task.route_stage_id)
    spec = resolve_transform_spec(task, stage)

    progress: TransformProgress | None = None
    consume_dims: dict | None = None
    if spec is not None:
        # Порция считается во входных заготовках: нельзя раскроить
        # больше, чем осталось нераскроенного входа по спецификации.
        # auto_transfer_next на трансформирующем этапе создаёт по передаче
        # на каждый выход — см. auto_create_transfer_after_complete (тикет #91).
        progress = await get_transform_progress(db, task.id)
        remaining_input = (
            spec.input_quantity
            - progress.consumed_quantity
            - progress.scrapped_quantity
        )
        if total > remaining_input:
            raise ValueError(
                f"Portion exceeds remaining input quantity: "
                f"requested {total}, remaining input {remaining_input}"
            )
        consume_dims = await resolve_consume_dimensions(
            db,
            product_id=task.product_id,
            location_id=task.section_id,
            dimensions=spec.input_dimensions,
            required=total,
        )
    else:
        in_work = cache["issued_quantity"] - cache["completed_quantity"] - cache["rejected_quantity"]
        if total > in_work:
            raise ValueError("Complete quantity exceeds issued quantity")

    return _TransformPlan(stage=stage, spec=spec, progress=progress, consume_dims=consume_dims)


async def _post_good_portion(
    db: AsyncSession,
    svc: StockCommandService,
    task: WorkTask,
    plan: _TransformPlan,
    *,
    cache_issued: Decimal,
    good_quantity: Decimal,
    actor_id: int,
    comment: str | None,
    source_ref: str | None,
    idempotency_key: str | None,
    eff_executor: int,
    eff_performed: datetime,
    eff_accounted: datetime,
    action_id: int,
) -> list[int]:
    """Проводки годной части порции; возвращает ids созданных транзакций.

    Трансформирующий этап — атомарные списание входа + приход всех выходов
    (record_transform_portion); обычный этап — net-zero COMPLETE при уже
    выданном материале либо выпуск «из ниоткуда» (legacy).
    ``cache_issued`` — issued_quantity из task-cache, прочитанного ДО проводок.
    """
    if good_quantity <= 0:
        return []
    tx_ids: list[int] = []

    if plan.spec is not None:
        # Порция трансформации: списание входа + приход всех выходов
        # (включая годный остаток) в текущей транзакции БД.
        complete_comment = comment
        line = await db.get(SectionPlanLine, task.section_plan_line_id)
        if line is not None and plan.stage is not None:
            complete_comment = await enrich_comment_with_route_operations(
                db,
                comment,
                route_id=line.route_id,
                through_sequence=plan.stage.sequence,
            )
        tx_ids.extend(await record_transform_portion(
            db,
            svc=svc,
            task=task,
            spec=plan.spec,
            progress=plan.progress,
            good_quantity=good_quantity,
            consume_dims=plan.consume_dims,
            actor_id=actor_id,
            executor_user_id=eff_executor,
            comment=complete_comment,
            source_ref=source_ref,
            idempotency_key=idempotency_key,
            performed_at=eff_performed,
            accounted_at=eff_accounted,
            action_id=action_id,
        ))
        return tx_ids

    # Material already on section (issued_quantity > 0): net-zero COMPLETE
    # records выпуск without duplicating balance after TRANSFER_SEND.
    # Legacy path (issued_quantity == 0): good appears from nowhere.
    if cache_issued > 0:
        complete_from = task.section_id
        complete_to = task.section_id
    else:
        complete_from = None
        complete_to = task.section_id
    complete_comment = comment
    if complete_to == task.section_id:
        line = await db.get(SectionPlanLine, task.section_plan_line_id)
        legacy_stage = await _get_route_stage(db, task.route_stage_id)
        if line is not None:
            complete_comment = await enrich_comment_with_route_operations(
                db,
                comment,
                route_id=line.route_id,
                through_sequence=legacy_stage.sequence,
            )
    tx_good = await svc.record(db, StockCommand(
        product_id=task.product_id,
        from_location_id=complete_from,
        to_location_id=complete_to,
        quantity=good_quantity,
        reason=Reason.COMPLETE,
        quality_state=QualityState.GOOD,
        # Габарит задания (ADR-0001): запись не движет баланс (net-zero),
        # но несёт ту же размерную группу, что и полученный материал.
        dimensions=task.dimensions,
        task_id=task.id,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        comment=complete_comment,
        created_by=actor_id,
        executor_user_id=eff_executor,
        performed_at=eff_performed,
        accounted_at=eff_accounted,
        action_id=action_id,
    ))
    tx_ids.append(tx_good.id)
    return tx_ids


async def _register_scrap_and_defect(
    db: AsyncSession,
    svc: StockCommandService,
    task: WorkTask,
    plan: _TransformPlan,
    *,
    defect_quantity: Decimal,
    defect_reason: str | None,
    scrap_policy: ScrapPolicy | None,
    actor_id: int,
    comment: str | None,
    source_ref: str | None,
    idempotency_key: str | None,
    eff_executor: int,
    eff_performed: datetime,
    eff_accounted: datetime,
    action_id: int,
) -> tuple[list[int], int | None]:
    """Брак порции: SCRAP-проводка на SCRAP-секцию + Defect/DefectItem.

    Find-or-create SCRAP-секции — общий шов ``scrap_policy`` (тикет #132),
    тот же модуль использует defect_decide. Брак заготовок трансформации
    уходит с габаритом входа; на нетрансформирующих этапах — с габаритом
    задания (ADR-0001).
    """
    if defect_quantity <= 0:
        return [], None
    # scrap: from production section to scrap location.
    # Данные SCRAP-секции приходят из composition root (ADR-0004 §5,
    # ADR-0007); сервис не резолвит PlantConfig сам.
    scrap_loc = await find_or_create_scrap_section_id(db, scrap_policy=scrap_policy)

    tx_scrap = await svc.record(db, StockCommand(
        product_id=task.product_id,
        from_location_id=task.section_id,
        to_location_id=scrap_loc,
        quantity=defect_quantity,
        reason=Reason.SCRAP,
        dimensions=plan.consume_dims if plan.spec is not None else task.dimensions,
        quality_state=QualityState.GOOD,
        to_quality_state=QualityState.SCRAP,
        task_id=task.id,
        source_ref=source_ref,
        idempotency_key=f"{idempotency_key}:reject" if idempotency_key else None,
        comment=comment,
        created_by=actor_id,
        executor_user_id=eff_executor,
        performed_at=eff_performed,
        accounted_at=eff_accounted,
        action_id=action_id,
    ))

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
    return [tx_scrap.id], defect.id


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
    # Объект канона plant_config.production.scrap_policy (ADR-0004 §5,
    # ADR-0007): вместо распакованного квартета scrap_* — один параметр;
    # шов find-or-create SCRAP-секции живёт в scrap_policy.py (тикет #132).
    scrap_policy: ScrapPolicy | None = None,
) -> dict:
    """Complete (good + defect) quantity on a SectionTask.

    Writes StockTransaction(COMPLETE) for good output and
    StockTransaction(SCRAP) for defect. Creates Defect/DefectItem
    for traceability. Stock cache is updated automatically via
    StockProjectionManager.

    Трансформирующий этап (ADR-0002): порция факта атомарно списывает
    вход (TRANSFORM_CONSUME × входной габарит) и приходует все выходы
    спецификации (COMPLETE × выходной габарит каждого) пропорционально
    доле входа; брак заготовок — SCRAP с габаритом входа.
    Здесь good_quantity/defect_quantity считаются во входных заготовках.
    """
    task = await _get_task(db, task_id)

    # Этапы оркестратора: replay → guard/лимиты → проводки good/scrap →
    # статус → авто-передача. Статус и передача — ЯВНЫЕ вызовы, без event-bus.
    replay = await _replay_existing_completion(db, task=task, idempotency_key=idempotency_key)
    if replay is not None:
        return replay

    _ensure_task_completable(task)
    good_quantity, defect_quantity, total = _normalize_quantities(good_quantity, defect_quantity)

    # Task-cache читается дважды намеренно: ЗДЕСЬ — до проводок, для лимитов
    # порции (issued/in_work в состоянии до неё); ниже — после проводок, для
    # синхронизации статуса по факту ledger, уже включающему эту порцию.
    from app.stock.services import StockProjectionManager
    pm = StockProjectionManager()
    cache = await pm.get_task_cache(db, task.id)

    plan = await _resolve_transform_plan(db, task=task, cache=cache, total=total)

    now = datetime.now(UTC)
    eff_performed = performed_at or now
    eff_accounted = accounted_at or now
    eff_executor = executor_user_id or actor_id

    svc = StockCommandService()
    # Журнал действий (ADR-0019, #116): одна операция = один Action
    # (good + scrap + transform-порция вместе); depends_on — цепочка задачи.
    actor_name = await _get_user_snapshot_name(db, actor_id)
    action = await action_journal_service.log_task_action(
        db, action_type="task_complete", ref_id=task.id, actor=actor_name,
    )

    tx_ids = list(await _post_good_portion(
        db, svc, task, plan,
        cache_issued=cache["issued_quantity"],
        good_quantity=good_quantity,
        actor_id=actor_id,
        comment=comment,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        eff_executor=eff_executor,
        eff_performed=eff_performed,
        eff_accounted=eff_accounted,
        action_id=action.id,
    ))
    scrap_tx_ids, defect_id = await _register_scrap_and_defect(
        db, svc, task, plan,
        defect_quantity=defect_quantity,
        defect_reason=defect_reason,
        scrap_policy=scrap_policy,
        actor_id=actor_id,
        comment=comment,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        eff_executor=eff_executor,
        eff_performed=eff_performed,
        eff_accounted=eff_accounted,
        action_id=action.id,
    )
    tx_ids.extend(scrap_tx_ids)

    await _refresh_section_plan_line_cache(db, task.section_plan_line_id)

    # Второе чтение task-cache — ПОСЛЕ проводок: статус выводится из факта
    # ledger, уже включающего эту порцию.
    from .task_status import sync_work_task_status

    cache_after = await pm.get_task_cache(db, task.id)
    await sync_work_task_status(db, task, cache=cache_after)

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
    dimensions: dict | None = None,
) -> dict:
    """Final release of finished goods to finished stock.

    Writes StockTransaction(FINAL_RELEASE). No SpgRemainder or
    compensate_spg_remainders.

    Трансформирующий финальный этап (ADR-0002): выпуск несёт один из
    выходных размеров задания (инвариант D3). При одном выходе габарит
    выводится из спецификации; при нескольких — обязателен явный
    ``dimensions``. На нетрансформирующих этапах ``dimensions``
    опционален (по умолчанию — габарит задания).
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

    from app.domain.dimensions import canonicalize_dimensions

    eff_dims = canonicalize_dimensions(dimensions)

    spec = resolve_transform_spec(task, stage)
    if spec is not None:
        # Трансформирующий этап: выпускаемый размер — один из выходов
        # спецификации.
        output_dims = [group.dimensions for group in spec.output_groups]
        if eff_dims is None:
            if len(output_dims) == 1:
                eff_dims = output_dims[0]
            else:
                raise ValueError(
                    "Final release on transforming stage requires dimensions "
                    "(task has multiple output sizes)"
                )
        if eff_dims not in output_dims:
            raise ValueError(
                "Final release dimensions must match one of the task outputs"
            )
    else:
        eff_dims = eff_dims if eff_dims is not None else task.dimensions

    # Бюджет отправки по (задача, размер) — единственный владелец чтения —
    # send_budget.remaining_send (тикет #128); «уже выпущено» — canonical
    # net FINAL_RELEASE через ledger-примитив (ADR-0018), формула и кламп —
    # чистый ярус app.transfers.budget.
    remaining = await send_budget.remaining_send(db, task=task, dims=eff_dims)
    if quantity > remaining:
        raise ValueError(
            f"Нельзя отправить {quantity}: доступно к отправке {remaining} шт."
        )

    # Find finished stock location
    from app.models.section import Section as _FinSection
    from app.services.route_storage_classifier import SECTION_TYPE_FINISHED_STOCK
    finished_stock = await db.scalar(
        select(_FinSection.id)
        .where(_FinSection.type == SECTION_TYPE_FINISHED_STOCK)
        .limit(1)
    )

    # Журнал действий (#116): final_release = Action по цепочке задачи.
    action = await action_journal_service.log_task_action(
        db,
        action_type="final_release",
        ref_id=task.id,
        actor=await _get_user_snapshot_name(db, actor_id),
    )

    svc = StockCommandService()
    # final_release: from production section to finished stock (or None if not found)
    tx = await svc.record(db, StockCommand(
        product_id=task.product_id,
        from_location_id=task.section_id if finished_stock else task.section_id,
        to_location_id=finished_stock,
        quantity=quantity,
        reason=Reason.FINAL_RELEASE,
        dimensions=eff_dims,
        task_id=task.id,
        source_ref=None,
        idempotency_key=idempotency_key,
        comment=comment,
        created_by=actor_id,
        executor_user_id=executor_user_id or actor_id,
        performed_at=performed_at or datetime.now(UTC),
        accounted_at=accounted_at or datetime.now(UTC),
        action_id=action.id,
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
    from app.services.route_storage_classifier import is_production_section
    sec_meta = await db.get(_Section, line.section_id)
    if sec_meta is not None and not is_production_section(sec_meta):
        return {
            "task_id": None,
            "status": "skipped_storage_section",
            "section_type": sec_meta.type,
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

    # Трансформирующий этап несёт вход/выходы позиции (ADR-0002)
    from app.services.route_transform import transform_fields_for_task

    transform_fields = await transform_fields_for_task(
        db,
        route_stage_id=line.route_stage_id,
        plan_position_id=line.plan_position_id,
        task_quantity=quantity,
    )
    task = WorkTask(
        section_plan_line_id=line.id,
        section_id=section_id,
        product_id=line.product_id,
        route_stage_id=line.route_stage_id,
        planned_quantity=quantity,
        status=WorkTaskStatus.ready,
        due_date=line.due_date,
        dimensions=position_dimensions_for_task(pos),
        **transform_fields,
    )
    db.add(task)
    await db.flush()
    await _refresh_section_plan_line_cache(db, task.section_plan_line_id)
    return {"task_id": task.id, "status": task.status.value}
