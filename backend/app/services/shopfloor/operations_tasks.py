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
from app.models.section import Section
from app.models.work_task import WorkTask, WorkTaskStatus
from app.seeds.canon.models import ScrapPolicy
from app.services.plan_position_hanger import position_dimensions_for_task
from app.services.action_journal_service import action_journal_service
from app.services.route_storage_classifier import (
    SECTION_TYPE_FINISHED_STOCK,
    STAGE_KIND_TRANSIT,
    is_storage_section,
)
from app.stock import QualityState, Reason, StockCommand, StockCommandService
from app.stock.models import StockBalance, StockTransaction
from app.stock.services import dimensions_match_clause

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


def _scrap_tx_key(idempotency_key: str) -> str:
    """Ключ SCRAP-проводки брака (суффикс :reject живёт в БД — не переименовывать)."""
    return f"{idempotency_key}:reject"


def _defect_key(idempotency_key: str) -> str:
    """Ключ Defect, созданного вместе с браком порции (см. _register_scrap_and_defect)."""
    return f"{idempotency_key}:defect"


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


class _CompletionCtx(NamedTuple):
    """Общий контекст порции завершения для этапов проводок (ADR-0019).

    Актёр, комментарии/ссылки, идемпотентность, эффективные исполнитель и
    моменты времени, id Action журнала. Один объект вместо пучка kwarg'ов,
    дублирующегося в сигнатурах этапов.
    """

    actor_id: int
    comment: str | None
    source_ref: str | None
    idempotency_key: str | None
    eff_executor: int
    eff_performed: datetime
    eff_accounted: datetime
    action_id: int


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
    existing = await _check_idempotency(db, idempotency_key=idempotency_key, entity_type=StockTransaction)
    if existing is None:
        return None
    existing_defect = await db.scalar(
        select(Defect).where(Defect.idempotency_key == _defect_key(idempotency_key))
    )
    # Порция — пучок проводок с общим префиксом: bare-ключ (списание входа),
    # :out{N} (выходы трансформации), :reject (SCRAP брака). Собираем весь
    # пучок, иначе replay-ответ теряет ссылки на созданные проводки.
    portion_txs = (
        await db.scalars(
            select(StockTransaction)
            .where(
                (StockTransaction.idempotency_key == idempotency_key)
                | StockTransaction.idempotency_key.startswith(f"{idempotency_key}:")
            )
            .order_by(StockTransaction.id)
        )
    ).all()
    return {
        "task_id": task.id,
        "transaction_ids": [tx.id for tx in portion_txs],
        "defect_id": existing_defect.id if existing_defect else None,
        "status": task.status.value,
        # Replay не пересчитывает порцию — факт уже в ledger (#133).
        "completed_quantity": None,
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


async def _good_input_balance(
    db: AsyncSession, *, product_id: int, location_id: int, consume_dims: dict | None,
) -> Decimal:
    """Доступный GOOD-баланс входной габаритной группы на участке.

    Ключ тот же, по которому ``record_transform_portion`` будет списывать
    вход порции: ``(product, section, GOOD, consume_dims)`` через
    ``dimensions_match_clause`` (NULL-группа матчится явно).
    """
    total = await db.scalar(
        select(func.coalesce(func.sum(StockBalance.balance_qty), 0)).where(
            StockBalance.product_id == product_id,
            StockBalance.location_id == location_id,
            StockBalance.quality_state == QualityState.GOOD,
            dimensions_match_clause(StockBalance.dimensions, consume_dims),
        )
    )
    return Decimal(total)


async def _resolve_shortage(
    db: AsyncSession,
    *,
    task: WorkTask,
    plan: _TransformPlan,
    good_quantity: Decimal,
    defect_quantity: Decimal,
    shortage_strategy: Literal["fail", "partial", "negative_remainder"],
) -> tuple[Decimal, Decimal, bool]:
    """Стратегия недостачи (#133) — применяется только к расходу входа
    трансформации; обычный этап недостач не имеет по построению.

    Возвращает ``(good, defect, allow_negative)`` — порцию к проводке и флаг
    осознанного минуса для ledger. Плановый лимит ``remaining_input`` жёсткий
    при любой стратегии (проверен ранее в ``_resolve_transform_plan``);
    стратегия — про физику склада:

    - ``fail`` — отказ всей операции; текст ошибки называет доступное
      количество («введено 100, доступно 80»);
    - ``partial`` — кламп порции до доступного баланса заготовок: провести
      сколько есть (годные приоритетнее брака), задача остаётся частично
      выполненной;
    - ``negative_remainder`` — полная порция, баланс заготовок участка уходит
      в минус до закрытия последующей выдачей (для СПГ с lot-учётом минус
      блокирует сам StockCommandService).
    """
    if plan.spec is None:
        return good_quantity, defect_quantity, False

    available = await _good_input_balance(
        db,
        product_id=task.product_id,
        location_id=task.section_id,
        consume_dims=plan.consume_dims,
    )
    if good_quantity + defect_quantity <= available:
        return good_quantity, defect_quantity, False

    if shortage_strategy == "fail":
        raise ValueError(
            f"Недостаточно заготовок на участке: введено {good_quantity + defect_quantity}, "
            f"доступно {available}"
        )
    if shortage_strategy == "partial":
        clamped_good = min(good_quantity, available)
        clamped_defect = min(defect_quantity, max(Decimal("0"), available - clamped_good))
        return clamped_good, clamped_defect, False
    if shortage_strategy == "negative_remainder":
        return good_quantity, defect_quantity, True
    raise ValueError(f"Unknown shortage strategy: {shortage_strategy}")


async def _post_good_portion(
    db: AsyncSession,
    svc: StockCommandService,
    task: WorkTask,
    plan: _TransformPlan,
    ctx: _CompletionCtx,
    *,
    cache_issued: Decimal,
    good_quantity: Decimal,
    allow_negative: bool = False,
) -> list[int]:
    """Проводки годной части порции; возвращает ids созданных транзакций.

    Трансформирующий этап — атомарные списание входа + приход всех выходов
    (record_transform_portion); обычный этап — net-zero COMPLETE при уже
    выданном материале либо выпуск «из ниоткуда» (legacy).
    ``cache_issued`` — issued_quantity из task-cache, прочитанного ДО проводок.
    ``allow_negative`` (#133) — осознанный минус входной группы, действует
    только на трансформирующем этапе.
    """
    if good_quantity <= 0:
        return []
    tx_ids: list[int] = []

    if plan.spec is not None:
        # Порция трансформации: списание входа + приход всех выходов
        # (включая годный остаток) в текущей транзакции БД.
        complete_comment = ctx.comment
        line = await db.get(SectionPlanLine, task.section_plan_line_id)
        if line is not None and plan.stage is not None:
            complete_comment = await enrich_comment_with_route_operations(
                db,
                ctx.comment,
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
            actor_id=ctx.actor_id,
            executor_user_id=ctx.eff_executor,
            comment=complete_comment,
            source_ref=ctx.source_ref,
            idempotency_key=ctx.idempotency_key,
            performed_at=ctx.eff_performed,
            accounted_at=ctx.eff_accounted,
            action_id=ctx.action_id,
            allow_negative=allow_negative,
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
    complete_comment = ctx.comment
    if complete_to == task.section_id:
        line = await db.get(SectionPlanLine, task.section_plan_line_id)
        legacy_stage = await _get_route_stage(db, task.route_stage_id)
        if line is not None:
            complete_comment = await enrich_comment_with_route_operations(
                db,
                ctx.comment,
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
        source_ref=ctx.source_ref,
        idempotency_key=ctx.idempotency_key,
        comment=complete_comment,
        created_by=ctx.actor_id,
        executor_user_id=ctx.eff_executor,
        performed_at=ctx.eff_performed,
        accounted_at=ctx.eff_accounted,
        action_id=ctx.action_id,
    ))
    tx_ids.append(tx_good.id)
    return tx_ids


async def _register_scrap_and_defect(
    db: AsyncSession,
    svc: StockCommandService,
    task: WorkTask,
    plan: _TransformPlan,
    ctx: _CompletionCtx,
    *,
    defect_quantity: Decimal,
    defect_reason: str | None,
    scrap_policy: ScrapPolicy | None,
    allow_negative: bool = False,
) -> tuple[list[int], int | None]:
    """Брак порции: SCRAP-проводка на SCRAP-секцию + Defect/DefectItem.

    Find-or-create SCRAP-секции — общий шов ``scrap_policy`` (тикет #132),
    тот же модуль использует defect_decide. Брак заготовок трансформации
    уходит с габаритом входа; на нетрансформирующих этапах — с габаритом
    задания (ADR-0001). ``allow_negative`` (#133) наследует стратегию
    negative_remainder: брак списывается вслед за годными, когда входная
    группа уже уведена в минус.
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
        allow_negative=allow_negative,
        task_id=task.id,
        source_ref=ctx.source_ref,
        idempotency_key=_scrap_tx_key(ctx.idempotency_key) if ctx.idempotency_key else None,
        comment=ctx.comment,
        created_by=ctx.actor_id,
        executor_user_id=ctx.eff_executor,
        performed_at=ctx.eff_performed,
        accounted_at=ctx.eff_accounted,
        action_id=ctx.action_id,
    ))

    defect = Defect(
        product_id=task.product_id,
        section_id=task.section_id,
        task_id=task.id,
        stock_transaction_id=tx_scrap.id,
        status=DefectStatus.decision_required,
        comment=ctx.comment,
        created_by=ctx.actor_id,
        idempotency_key=_defect_key(ctx.idempotency_key) if ctx.idempotency_key else None,
    )
    db.add(defect)
    await db.flush()

    defect_item = DefectItem(
        defect_id=defect.id,
        defect_type_id=None,
        defect_type_code_snapshot=defect_reason,
        defect_type_name_snapshot=defect_reason,
        quantity=defect_quantity,
        description=ctx.comment,
        created_by=ctx.actor_id,
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
    shortage_strategy: Literal["fail", "partial", "negative_remainder"] = "fail",
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

    Стратегия недостачи (#133) — только расход входа трансформации,
    дефолт ``fail``: при нехватке GOOD-баланса входной группы операция
    отклоняется с указанием доступного количества; ``partial`` клампит
    порцию до доступного; ``negative_remainder`` проводит полностью и
    уводит баланс участка в минус. Плановый лимит remaining_input жёсткий
    при любой стратегии. Ответ дополняется ``completed_quantity`` —
    фактически проведённой порцией во входных заготовках; поле присутствует
    во всех ответах, КРОМЕ idempotent-replay, где оно ``None``
    (replay не пересчитывает порцию — факт уже в ledger).
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

    # Стратегия недостачи (#133): решение по GOOD-балансу входной группы —
    # ДО проводок; кламп/минус/отказ применяются к порции целиком.
    post_good, post_defect, allow_negative = await _resolve_shortage(
        db,
        task=task,
        plan=plan,
        good_quantity=good_quantity,
        defect_quantity=defect_quantity,
        shortage_strategy=shortage_strategy,
    )

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

    # Общий контекст порции для обоих этапов проводок.
    ctx = _CompletionCtx(
        actor_id=actor_id,
        comment=comment,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        eff_executor=eff_executor,
        eff_performed=eff_performed,
        eff_accounted=eff_accounted,
        action_id=action.id,
    )

    tx_ids = list(await _post_good_portion(
        db, svc, task, plan, ctx,
        cache_issued=cache["issued_quantity"],
        good_quantity=post_good,
        allow_negative=allow_negative,
    ))
    scrap_tx_ids, defect_id = await _register_scrap_and_defect(
        db, svc, task, plan, ctx,
        defect_quantity=post_defect,
        defect_reason=defect_reason,
        scrap_policy=scrap_policy,
        allow_negative=allow_negative,
    )
    tx_ids.extend(scrap_tx_ids)

    await _refresh_section_plan_line_cache(db, task.section_plan_line_id)

    # Второе чтение task-cache — ПОСЛЕ проводок: статус выводится из факта
    # ledger, уже включающего эту порцию.
    from .task_status import sync_work_task_status

    cache_after = await pm.get_task_cache(db, task.id)
    await sync_work_task_status(db, task, cache=cache_after)

    # Авто-передача следует за фактом: передаётся только реально проведённая
    # годная часть порции (#133), а не запрошенная оператором.
    if auto_transfer_next and post_good > 0:
        from app.transfers.services import auto_create_transfer_after_complete
        await auto_create_transfer_after_complete(
            db,
            from_task=task,
            good_quantity=post_good,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            comment=comment or "Авто-перемещение после завершения",
        )

    return {
        "task_id": task.id,
        "transaction_ids": tx_ids,
        "defect_id": defect_id,
        "status": task.status.value,
        # Фактически проведённая порция во входных заготовках (#133): при
        # клампе partial меньше запрошенной; присутствует во всех ответах,
        # кроме idempotent-replay (там None — см. _replay_existing_completion);
        # расхождение с введённым количеством и есть признак частичного
        # проведения.
        "completed_quantity": post_good + post_defect,
    }


async def resolve_final_release_destination(
    db: AsyncSession,
    stage: RouteStage,
) -> Section:
    """Адресат FINAL_RELEASE — каскад (#137), вместо «первой по sort_order».

    1. Складский (transit) хоп маршрута, следующий за финальным этапом:
       контекст маршрута приоритетнее глобального дефолта (SAP: production
       version → material master; Odoo: выходная локация маршрута).
    2. Глобальный дефолт «склад выпуска» — секция с ``is_output_default``.
    3. Неоднозначность/отсутствие адресата → ``ValueError`` (отказ операции,
       не молчаливый выбор).
    """
    next_stage = await db.scalar(
        select(RouteStage)
        .where(
            RouteStage.route_id == stage.route_id,
            RouteStage.sequence > stage.sequence,
        )
        .order_by(RouteStage.sequence)
        .limit(1)
    )
    if (
        next_stage is not None
        and next_stage.stage_kind == STAGE_KIND_TRANSIT
        and next_stage.storage_section_id is not None
    ):
        hop = await db.get(Section, next_stage.storage_section_id)
        if hop is None or not is_storage_section(hop):
            # Сломанный маршрут: транзитный хоп без склада. Молча
            # подменять его глобальным дефолтом нельзя — отказ.
            raise ValueError(
                f"Транзитный хоп маршрута (stage_id={next_stage.id}) "
                f"ссылается на несуществующую или не-складскую секцию "
                f"(storage_section_id={next_stage.storage_section_id})"
            )
        return hop

    defaults = (await db.execute(
        select(Section).where(Section.is_output_default.is_(True))
    )).scalars().all()
    if not defaults:
        raise ValueError(
            "Не найден склад выпуска: задайте транзитный хоп после финального "
            "этапа маршрута или пометьте склад ГП как «склад выпуска» "
            "(is_output_default)"
        )
    if len(defaults) > 1:
        codes = ", ".join(sorted(s.code for s in defaults))
        raise ValueError(
            f"Неоднозначный склад выпуска: is_output_default у нескольких "
            f"секций ({codes}); оставьте флаг у одной"
        )
    default = defaults[0]
    if default.type != SECTION_TYPE_FINISHED_STOCK:
        # Каталог сломан вручную: «склад выпуска» перестал быть складом ГП —
        # молча выпускать готовую продукцию туда нельзя.
        raise ValueError(
            f"Секция «склад выпуска» {default.code} имеет тип "
            f"{default.type}: is_output_default допустим только на "
            f"складе готовой продукции ({SECTION_TYPE_FINISHED_STOCK})"
        )
    return default


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

    # Адресат финального выпуска — каскад (#137): транзитный хоп маршрута
    # после финального этапа → дефолт «склад выпуска» → отказ (ValueError)
    # при отсутствии/неоднозначности. Отказ происходит до записи в журнал
    # действий. Без адресата проводка «в никуда» запрещена: продукция
    # списалась бы с баланса участка, не придя никуда (проекция
    # пересчитывает только from-сторону).
    destination = await resolve_final_release_destination(db, stage)
    finished_stock = destination.id

    # Журнал действий (#116): final_release = Action по цепочке задачи.
    # Пишется после стража адресата — отказ не оставляет сироту в журнале.
    action = await action_journal_service.log_task_action(
        db,
        action_type="final_release",
        ref_id=task.id,
        actor=await _get_user_snapshot_name(db, actor_id),
    )

    svc = StockCommandService()
    tx = await svc.record(db, StockCommand(
        product_id=task.product_id,
        from_location_id=task.section_id,
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
