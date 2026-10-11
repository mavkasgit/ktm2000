"""Батчевость доски участка (#293).

Контракт, который защищают тесты:

- число SQL на доске не растёт с числом трансформирующих заданий и с числом
  парных позиций (было +1 на задание и +2 на пару);
- ответ доски при этом прежний: задачи, статусы и прогресс те же;
- прогресс трансформации приходит из карты батча, а не из поштучного запроса;
- доска — чистое чтение: ни одного UPDATE и ни одного flush на доску.
  Свежестью статуса владеет write-path (``StockCommandService.record``,
  ADR-0041), а не опрос: проводка доводит статус до проекции в своей же
  транзакции, доска его только читает.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from app.models.internal_plan import InternalPlan, InternalPlanStatus, SectionPlanLine
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import (
    ProductionRoute,
    RouteOperation,
    RouteStage,
    SectionOperation,
)
from app.models.section import Section
from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.shopfloor.queries_sections import get_section_board
from app.stock.models import QualityState, Reason, StockTransaction
from app.stock.services import StockCommand, StockCommandService
from sqlalchemy import event, select, text

pytestmark = pytest.mark.asyncio

CONSUMED_OUTPUTS = [{"length_mm": 900}, {"length_mm": 1350}]


class SqlRecorder:
    """Счётчик SQL и savepoint'ов одного вызова: доска не должна ими ветвиться."""

    def __init__(self, engine) -> None:
        self.engine = engine
        self.statements: list[str] = []

    def __enter__(self) -> SqlRecorder:
        event.listen(self.engine.sync_engine, "before_cursor_execute", self._on_execute)
        return self

    def __exit__(self, *exc) -> None:
        event.remove(self.engine.sync_engine, "before_cursor_execute", self._on_execute)

    def _on_execute(self, conn, cursor, statement, parameters, context, executemany) -> None:
        self.statements.append(" ".join(statement.split()).upper())

    @property
    def queries(self) -> int:
        return len(self.statements)

    @property
    def flushes(self) -> int:
        """`flush()` в asyncpg-сессии виден как SAVEPOINT: их число и есть flush'и."""
        return sum(1 for statement in self.statements if statement.startswith("SAVEPOINT"))


async def _make_transform_section(session, *, tasks: int, paired: bool, prefix: str) -> Section:
    """Участок с маршрутом из одного трансформирующего этапа и N заданиями."""
    section = Section(code=f"B923-{prefix}-{tasks}", name="Пиление", type="production")
    session.add(section)
    await session.flush()

    product = Product(sku=f"B923-SKU-{prefix}-{tasks}", name="SKU", type=ProductType.finished_good, unit="pcs")
    session.add(product)
    await session.flush()

    route = ProductionRoute(name=f"B923-ROUTE-{prefix}-{tasks}", is_active=True)
    session.add(route)
    await session.flush()

    stage = RouteStage(
        route_id=route.id,
        sequence=1,
        section_id=section.id,
        is_final=True,
        transforms_dimensions=True,
    )
    session.add(stage)
    await session.flush()
    session.add(RouteOperation(route_stage_id=stage.id, sequence=1, operation_code="OP1", operation_name="Пиление"))
    session.add(SectionOperation(section_id=section.id, operation_code="OP1", operation_name="Пиление"))
    await session.flush()

    plan = ProductionPlan(
        plan_no=f"B923-P-{prefix}-{tasks}", name="p", status=ProductionPlanStatus.approved,
        period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
    )
    session.add(plan)
    await session.flush()

    internal = InternalPlan(production_plan_id=plan.id, status=InternalPlanStatus.active)
    session.add(internal)
    await session.flush()

    created: list[WorkTask] = []
    for index in range(tasks):
        payload: dict = {}
        if paired:
            # Пара, которой нет в справочнике: резолв идёт до конца и стоит
            # запросов, но результат всё равно None — считаем именно путь.
            payload = {
                "paired_profile": True,
                "components": [{"sku": f"B923-MISSING-A-{index}"}, {"sku": f"B923-MISSING-B-{index}"}],
            }
        position = PlanPosition(
            production_plan_id=plan.id,
            product_id=product.id,
            source_type=PlanSourceType.manual,
            source_sku=product.sku,
            source_name=product.name,
            quantity=Decimal(10),
            source_payload=payload,
            status=PlanPositionStatus.approved,
            validation_status=PlanPositionValidationStatus.valid,
            validation_errors=[],
            period_start=plan.period_start,
            period_end=plan.period_end,
            has_pack_ops=False,
            route_id=route.id,
        )
        session.add(position)
        await session.flush()
        line = SectionPlanLine(
            internal_plan_id=internal.id,
            plan_position_id=position.id,
            section_id=section.id,
            route_stage_id=stage.id,
            product_id=product.id,
            route_id=route.id,
            sequence=1,
            planned_quantity=Decimal(10),
        )
        session.add(line)
        await session.flush()
        task = WorkTask(
            section_plan_line_id=line.id,
            section_id=section.id,
            product_id=product.id,
            route_stage_id=stage.id,
            planned_quantity=Decimal(10),
            input_quantity=Decimal(10),
            input_dimensions={"length_mm": 2750},
            outputs=CONSUMED_OUTPUTS,
            status=WorkTaskStatus.in_progress,
        )
        session.add(task)
        created.append(task)
    await session.commit()
    return section


async def _make_non_transform_section_with_stale_input(session, *, prefix: str) -> Section:
    """Участок с НЕ-трансформирующим этапом, но заданием с `input_quantity`.

    Так бывает, когда маркер этапа сняли после создания задания: задание
    сохраняет вход и выходы, а `transforms_dimensions` у этапа уже `False`.
    """
    section = Section(code=f"B923-{prefix}", name="Не пиление", type="production")
    session.add(section)
    await session.flush()

    product = Product(sku=f"B923-SKU-{prefix}", name="SKU", type=ProductType.finished_good, unit="pcs")
    session.add(product)
    await session.flush()

    route = ProductionRoute(name=f"B923-ROUTE-{prefix}", is_active=True)
    session.add(route)
    await session.flush()

    stage = RouteStage(
        route_id=route.id,
        sequence=1,
        section_id=section.id,
        is_final=True,
        transforms_dimensions=False,
    )
    session.add(stage)
    await session.flush()
    session.add(RouteOperation(route_stage_id=stage.id, sequence=1, operation_code="OP1", operation_name="Оп1"))
    await session.flush()

    plan = ProductionPlan(
        plan_no=f"B923-P-{prefix}", name="p", status=ProductionPlanStatus.approved,
        period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
    )
    session.add(plan)
    await session.flush()
    internal = InternalPlan(production_plan_id=plan.id, status=InternalPlanStatus.active)
    session.add(internal)
    await session.flush()

    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal(10),
        source_payload={},
        status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        period_start=plan.period_start,
        period_end=plan.period_end,
        has_pack_ops=False,
        route_id=route.id,
    )
    session.add(position)
    await session.flush()
    line = SectionPlanLine(
        internal_plan_id=internal.id,
        plan_position_id=position.id,
        section_id=section.id,
        route_stage_id=stage.id,
        product_id=product.id,
        route_id=route.id,
        sequence=1,
        planned_quantity=Decimal(10),
    )
    session.add(line)
    await session.flush()
    task = WorkTask(
        section_plan_line_id=line.id,
        section_id=section.id,
        product_id=product.id,
        route_stage_id=stage.id,
        planned_quantity=Decimal(10),
        input_quantity=Decimal(10),
        input_dimensions={"length_mm": 2750},
        outputs=CONSUMED_OUTPUTS,
        status=WorkTaskStatus.in_progress,
    )
    session.add(task)
    await session.flush()
    # Движение по ledger есть — значит задание попадёт в карту прогресса.
    session.add(
        StockTransaction(
            task_id=task.id,
            product_id=product.id,
            created_by=1,
            from_location_id=section.id,
            reason=Reason.TRANSFORM_CONSUME,
            quantity=Decimal(5),
            dimensions={"length_mm": 2750},
        )
    )
    # `id` читаем ДО commit: после commit атрибуты истёкли, а ленивая
    # перечитка после `rollback` в async-сессии даёт MissingGreenlet.
    task_id = task.id
    section_id = section.id
    await session.commit()
    return section_id, task_id


async def test_board_hides_output_card_on_non_transform_stage(engine, session) -> None:
    """Карточка выходов — по маркеру этапа, а не по наличию id в карте (#293).

    Карта прогресса батча шире выдачи: в неё входят задания с
    `input_quantity` даже без `transforms_dimensions` — они нужны
    синхронизации статусов. Пока карта была единственным гейтом, такое
    задание получало `outputs_progress` на не-трансформирующем этапе.
    """
    section_id, task_id = await _make_non_transform_section_with_stale_input(session, prefix="NOGATE")
    await session.rollback()

    board = await get_section_board(session, section_id=section_id, limit=500, offset=0)

    row = next(r for r in board["tasks"] if r["id"] == task_id)
    assert row["outputs_progress"] is None, (
        "не-трансформирующий этап не должен отдавать карточку выходов: "
        f"{row['outputs_progress']}"
    )
    assert row["input_consumed_quantity"] is None


async def _board_sql(engine, session, section_id: int) -> tuple[SqlRecorder, dict]:
    """GET-доска под записью SQL; возвращает и счётчик, и ответ доски."""
    # После rollback/commit сессия открывает свежий savepoint на первом же
    # SQL — служебный маркер своей транзакции, а не flush доски. Прогоняем
    # его ДО записи, чтобы счётчик flush'ей доски был честным.
    await session.execute(text("SELECT 1"))
    recorder = SqlRecorder(engine)
    with recorder:
        board = await get_section_board(session, section_id=section_id, limit=500, offset=0)
    return recorder, board


async def test_board_sql_does_not_grow_with_transform_tasks(engine, session) -> None:
    """Трансформирующих заданий в 20 раз больше — запросов столько же (#293)."""
    small = await _make_transform_section(session, tasks=5, paired=False, prefix="SMALL")
    large = await _make_transform_section(session, tasks=100, paired=False, prefix="LARGE")
    await session.rollback()

    small_sql, _ = await _board_sql(engine, session, small.id)
    large_sql, _ = await _board_sql(engine, session, large.id)

    # Инвариант тикета — «не растёт», а не «одинаковое число»: на малом
    # участке часть батчей не нужна, и лишний запрос там просто не возникает.
    assert large_sql.queries <= small_sql.queries, (
        f"5 заданий → {small_sql.queries} SQL, 100 заданий → {large_sql.queries} SQL"
    )


async def test_board_sql_does_not_grow_with_paired_positions(engine, session) -> None:
    """Парных позиций в 20 раз больше — запросов столько же (#293)."""
    few = await _make_transform_section(session, tasks=5, paired=True, prefix="FEW")
    many = await _make_transform_section(session, tasks=100, paired=True, prefix="MANY")
    await session.rollback()

    few_sql, _ = await _board_sql(engine, session, few.id)
    many_sql, _ = await _board_sql(engine, session, many.id)

    assert many_sql.queries <= few_sql.queries, (
        f"5 парных позиций → {few_sql.queries} SQL, 100 → {many_sql.queries} SQL"
    )


async def test_board_get_writes_nothing(engine, session) -> None:
    """Доска — чистое чтение: ни одного UPDATE и ни одного flush на доску.

    Раньше опрос доски сам синхронизировал статусы (один flush на доску,
    но UPDATE со строки на строку с каждого терминала каждые 12 с). Теперь
    свежестью владеет write-path, и GET не пишет вообще (#293, ADR-0041).
    """
    section = await _make_transform_section(session, tasks=20, paired=False, prefix="FLUSH")
    # Разные пары в справочнике не нужны: записи видны по savepoint'ам и DML.
    await session.rollback()

    recorder, _ = await _board_sql(engine, session, section.id)

    writes = [s for s in recorder.statements if s.startswith(("INSERT", "UPDATE", "DELETE"))]
    assert recorder.flushes == 0, f"{recorder.flushes} flush на доску из 20 заданий"
    assert writes == [], f"доска пишет в БД: {writes[:5]}"


async def test_board_returns_stored_status_without_ledger_recompute(engine, session) -> None:
    """Доска отдаёт статус из БД, а не пересчитывает его по ledger.

    Устаревший статус в БД при полном списании входа в ledger — состояние,
    которое доска больше не чинит: чинка — работа write-path, а не опроса
    (ADR-0041). Здесь оно воспроизводится сырой вставкой мимо record() и
    документируется как read-only ответ доски.
    """
    section = await _make_transform_section(session, tasks=1, paired=False, prefix="STALE")
    tasks = (
        await session.execute(
            select(WorkTask).where(WorkTask.section_id == section.id)
        )
    ).scalars().all()
    assert len(tasks) == 1
    task = tasks[0]

    # Списан весь вход — но проводка вставлена мимо write-path, и статус в
    # БД так и остался in_progress.
    session.add(
        StockTransaction(
            task_id=task.id,
            product_id=task.product_id,
            created_by=1,
            from_location_id=section.id,
            reason=Reason.TRANSFORM_CONSUME,
            quantity=Decimal(10),
            dimensions={"length_mm": 2750},
        )
    )
    await session.commit()
    task_id = task.id
    section_id = section.id
    assert task.status == WorkTaskStatus.in_progress

    recorder, board = await _board_sql(engine, session, section_id)

    statuses = {row["id"]: row["status"] for row in board["tasks"]}
    assert statuses[task_id] == WorkTaskStatus.in_progress.value
    writes = [s for s in recorder.statements if s.startswith(("INSERT", "UPDATE", "DELETE"))]
    assert writes == [], f"доска чинит статус сама: {writes[:5]}"


async def test_record_write_path_syncs_status_for_board(engine, session) -> None:
    """Свежесть статуса без F5 (ADR-0041): проводка через record() доводит
    статус до проекции в своей транзакции, а доска его только читает."""
    section = await _make_transform_section(session, tasks=1, paired=False, prefix="WPATH")
    tasks = (
        await session.execute(
            select(WorkTask).where(WorkTask.section_id == section.id)
        )
    ).scalars().all()
    assert len(tasks) == 1
    task = tasks[0]
    task_id = task.id
    section_id = section.id

    svc = StockCommandService()
    # Вход на участке — приход до операции (та же пустая группа признака,
    # которую спросит списание ниже).
    await svc.record(session, StockCommand(
        product_id=task.product_id,
        from_location_id=None,
        to_location_id=section_id,
        quantity=Decimal(10),
        reason=Reason.MANUAL_IN,
        dimensions={"length_mm": 2750},
        completed_operations=[],
        created_by=1,
    ))
    # Весь вход списан операцией — ровно ту проводку пишет complete_task.
    await svc.record(session, StockCommand(
        product_id=task.product_id,
        from_location_id=section_id,
        to_location_id=None,
        quantity=Decimal(10),
        reason=Reason.TRANSFORM_CONSUME,
        quality_state=QualityState.GOOD,
        dimensions={"length_mm": 2750},
        completed_operations=[],
        task_id=task_id,
        created_by=1,
    ))
    await session.commit()
    # Статус уже в БД до всякого чтения доски — его записал write-path.
    refreshed = await session.get(WorkTask, task_id)
    assert refreshed.status == WorkTaskStatus.completed

    recorder, board = await _board_sql(engine, session, section_id)

    statuses = {row["id"]: row["status"] for row in board["tasks"]}
    assert statuses[task_id] == WorkTaskStatus.completed.value
    assert recorder.flushes == 0, f"{recorder.flushes} flush на доску после проводки"
    writes = [s for s in recorder.statements if s.startswith(("INSERT", "UPDATE", "DELETE"))]
    assert writes == [], f"доска пишет в БД: {writes[:5]}"
