"""SQL-регресс списка строк плана (#297).

Страница «Контроль выполнения» опрашивается каждые 12 секунд, поэтому её
список обязан стоить фиксированное число SQL: ни одна строка не должна
добавлять запрос. Тикет #297 — про N+1 в ``GET /production-planning/rows``;
здесь фиксируется результат: потолок на default-фильтре и постоянство
числа запросов при росте ``limit`` (100 против 500).

Счёт — слушателем ``before_cursor_execute`` на engine, как в замерах #290 и
тестах #292/#295. Считаются только SELECT'ы: SAVEPOINT/RELEASE — служебные
операторы тестовой транзакции (``create_savepoint``), а не запросы ручки.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.models.internal_plan import InternalPlan, InternalPlanStatus, SectionPlanLine
from app.models.product import Product, ProductLength, ProductPair, ProductType
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
from sqlalchemy import select, update

from tests.helpers.sql_counter import SqlRecorder

pytestmark = pytest.mark.asyncio

# Минимум default-фильтра после #297: 29 SELECT'ов на этой конфигурации
# (см. ``test_sql_count_is_flat_and_within_ceiling``). Потолок — не «с запасом»:
# любая новая per-строчная загрузка обязана его сломать, а не спрятаться в
# допуске. На dev-данных замер R-09 дал 31 SELECT; два лишних агрегата
# (``has_tasks``/``task_counts``/``final_step``) сведены в один, поэтому здесь
# 31 → 29. Состав задаётся сидом: пагинация, агрегаты, текущий этап, снимок
# маршрутов, подбор (позиции без маршрута), остатки, подвесы с парой.
MAX_SELECTS = 29

POSITIONS = 520
# Каждая 50-я позиция — без маршрута: ветка подбора по правилам и её снимок
# (4 запроса на профиль) должны оставаться константой, а не расти по строке.
NO_ROUTE_EVERY = 50
# Каждая 37-я позиция с маршрутом — все задания закрыты: ветка fallback
# текущего этапа тоже должна стоить один запрос на страницу.
FALLBACK_EVERY = 37


async def _seed_sections(session) -> dict[str, Section]:
    sections = {
        "raw": Section(code="P297-RAW", name="Склад сырья", type="raw_stock", is_active=True, sort_order=0),
        "cut": Section(code="P297-CUT", name="Раскрой", type="production", is_active=True, sort_order=1),
        "pack": Section(code="P297-PACK", name="Упаковка", type="production", is_active=True, sort_order=2),
        "fin": Section(code="P297-FIN", name="Склад ГП", type="finished_stock", is_active=True, sort_order=3),
    }
    session.add_all(sections.values())
    await session.flush()
    for index, section in enumerate(sections.values()):
        session.add(
            SectionOperation(
                section_id=section.id,
                operation_code=f"OP297{index}",
                operation_name=f"Операция {index}",
            )
        )
    await session.flush()
    return sections


async def _seed_routes(
    session,
    sections: dict[str, Section],
    count: int,
) -> tuple[list[ProductionRoute], list[tuple[RouteStage, RouteStage]]]:
    routes: list[ProductionRoute] = []
    stage_sets: list[tuple[RouteStage, RouteStage]] = []
    for index in range(count):
        route = ProductionRoute(name=f"Маршрут 297-{index}", is_active=True, sort_order=index)
        session.add(route)
        await session.flush()
        stages = (
            (sections["cut"], "CUT", "Резка"),
            (sections["pack"], "PACK", "Упаковка"),
            (sections["fin"], "SHIP", "Отгрузка"),
        )
        created: list[RouteStage] = []
        for sequence, (section, code, name) in enumerate(stages, start=1):
            stage = RouteStage(
                route_id=route.id,
                sequence=sequence,
                section_id=section.id,
                is_final=sequence == len(stages),
            )
            session.add(stage)
            await session.flush()
            session.add(
                RouteOperation(
                    route_stage_id=stage.id,
                    sequence=1,
                    operation_code=f"{code}{index}",
                    operation_name=name,
                )
            )
            created.append(stage)
        routes.append(route)
        stage_sets.append((created[0], created[1]))
    await session.flush()
    # Этапы первых двух участков нужны строкам плана; отдаём их наружу.
    return routes, stage_sets


async def _seed_products(session, count: int) -> list[Product]:
    products: list[Product] = []
    for index in range(count):
        product = Product(
            sku=f"P297-SKU-{index:03d}",
            name=f"Артикул {index}",
            type=ProductType.finished_good,
            unit="pcs",
            is_active=True,
            attributes={"hanger_mode": "auto", "perimeter_mm": 40.0},
        )
        session.add(product)
        await session.flush()
        session.add(
            ProductLength(
                product_id=product.id,
                length_mm=2700,
                raw_length_mm=6000,
                is_primary=True,
            )
        )
        products.append(product)
    await session.flush()
    return products


async def _seed_positions(
    session,
    *,
    count: int,
    routes: list[ProductionRoute],
    stage_sets: list[tuple[RouteStage, RouteStage]],
    products: list[Product],
) -> None:
    plan = ProductionPlan(
        plan_no="PLAN-297-SQL",
        name="План SQL 297",
        status=ProductionPlanStatus.approved,
    )
    session.add(plan)
    await session.flush()
    internal = InternalPlan(production_plan_id=plan.id, status=InternalPlanStatus.active)
    session.add(internal)
    await session.flush()

    positions: list[PlanPosition] = []
    for index in range(count):
        route_index = index % len(routes)
        route_id = (
            None
            if index % NO_ROUTE_EVERY == 0
            else routes[route_index].id
        )
        position = PlanPosition(
            production_plan_id=plan.id,
            product_id=products[index % len(products)].id,
            source_type=PlanSourceType.manual,
            source_sku=f"P297-{index:04d}",
            source_name=f"Позиция {index}",
            quantity=Decimal(100),
            input_dimensions={"length_mm": 2700},
            source_payload={},
            status=PlanPositionStatus.approved,
            validation_status=PlanPositionValidationStatus.valid,
            validation_errors=[],
            has_pack_ops=False,
            route_id=route_id,
            source_row_number=index + 1,
        )
        session.add(position)
        positions.append(position)
    await session.flush()

    lines: list[SectionPlanLine] = []
    line_meta: list[tuple[int, RouteStage]] = []
    for index, position in enumerate(positions):
        if position.route_id is None:
            continue
        first, second = stage_sets[index % len(routes)]
        for sequence, stage in enumerate((first, second), start=1):
            lines.append(
                SectionPlanLine(
                    internal_plan_id=internal.id,
                    plan_position_id=position.id,
                    section_id=stage.section_id,
                    route_stage_id=stage.id,
                    product_id=position.product_id,
                    route_id=position.route_id,
                    sequence=sequence,
                    planned_quantity=Decimal(100),
                )
            )
            line_meta.append((index, stage))
    session.add_all(lines)
    await session.flush()

    tasks: list[WorkTask] = []
    for line, (index, stage) in zip(lines, line_meta, strict=True):
        all_completed = index % FALLBACK_EVERY == 0
        if all_completed:
            status = WorkTaskStatus.completed
        elif line.sequence == 1:
            status = WorkTaskStatus.ready if index % 3 else WorkTaskStatus.in_progress
        else:
            status = WorkTaskStatus.waiting_previous
        tasks.append(
            WorkTask(
                section_plan_line_id=line.id,
                section_id=stage.section_id,
                product_id=line.product_id,
                route_stage_id=stage.id,
                planned_quantity=Decimal(100),
                status=status,
                dimensions={"length_mm": 2700},
            )
        )
    session.add_all(tasks)
    await session.commit()


async def _seed_pairs(session, products: list[Product]) -> None:
    """Пара в справочнике — ветка ``product_pairs`` в резолве подвесов."""
    session.add(ProductPair(product_a_id=products[0].id, product_b_id=products[1].id))
    await session.commit()


async def _seed_all(session) -> None:
    sections = await _seed_sections(session)
    routes, stage_sets = await _seed_routes(session, sections, 3)
    products = await _seed_products(session, 4)
    await _seed_positions(
        session,
        count=POSITIONS,
        routes=routes,
        stage_sets=stage_sets,
        products=products,
    )
    await _seed_pairs(session, products)


@pytest.mark.parametrize("limit", [100, 500])
async def test_sql_count_is_flat_and_within_ceiling(engine, session, client, limit: int) -> None:
    """Число SELECT'ов на странице — константа, а не функция от числа строк."""
    await _seed_all(session)

    with SqlRecorder(engine) as recorder:
        response = await client.get(f"/api/production-planning/rows?limit={limit}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == POSITIONS
    assert len(body["rows"]) == limit
    assert recorder.count <= MAX_SELECTS, [
        statement[:140] for statement in recorder.selects
    ]


async def test_sql_count_does_not_grow_between_limits(engine, session, client) -> None:
    """limit 500 не добавляет ни одного запроса к limit 100: разница — ноль.

    Это сильнее требования «разница только на константу»: на сиде обе
    страницы содержат все ветки (маршрут/подбор/fallback/пара), поэтому
    любая per-строчная загрузка проявится как разница и уронит тест.
    """
    await _seed_all(session)

    with SqlRecorder(engine) as recorder_100:
        response_100 = await client.get("/api/production-planning/rows?limit=100")
    with SqlRecorder(engine) as recorder_500:
        response_500 = await client.get("/api/production-planning/rows?limit=500")

    assert response_100.status_code == 200, response_100.text
    assert response_500.status_code == 200, response_500.text
    assert recorder_100.count == recorder_500.count, (
        f"limit 100: {recorder_100.count} SQL, limit 500: {recorder_500.count} SQL"
    )


async def test_response_order_and_aggregates_unchanged(engine, session, client) -> None:
    """Ответ прежний: порядок, total и флаги, посчитанные слитым агрегатом."""
    await _seed_all(session)

    response_100 = await client.get("/api/production-planning/rows?limit=100")
    response_500 = await client.get("/api/production-planning/rows?limit=500")

    assert response_100.status_code == 200, response_100.text
    assert response_500.status_code == 200, response_500.text
    body_100 = response_100.json()
    body_500 = response_500.json()

    # Дефолтная сортировка: один план, строки — по source_row_number.
    assert body_100["total"] == body_500["total"] == POSITIONS
    assert [row["source_row_number"] for row in body_100["rows"]] == list(range(1, 101))
    assert [row["plan_position_id"] for row in body_500["rows"][:100]] == [
        row["plan_position_id"] for row in body_100["rows"]
    ]

    rows_by_number = {row["source_row_number"]: row for row in body_100["rows"]}

    # Обычная позиция с открытыми заданиями: выпущена, не выполнена.
    normal = rows_by_number[2]
    assert normal["has_tasks"] is True
    assert normal["is_released"] is True
    assert normal["is_completed"] is False
    assert normal["route_id"] is not None
    assert normal["route_steps"], "route_steps не должны опустеть"

    # Позиция с закрытыми заданиями всех этапов: выполнена (fallback-ветка).
    completed = rows_by_number[FALLBACK_EVERY + 1]
    assert completed["has_tasks"] is True
    assert completed["is_completed"] is True

    # Позиция без маршрута и без строк плана: не выпущена и не выполнена.
    no_route = rows_by_number[NO_ROUTE_EVERY + 1]
    assert no_route["has_tasks"] is False
    assert no_route["is_released"] is False
    assert no_route["is_completed"] is False

    # Фильтр по статусу не меняет ни ответ, ни число запросов.
    with SqlRecorder(engine) as recorder_filtered:
        filtered = await client.get(
            "/api/production-planning/rows?limit=100&status=approved"
        )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == POSITIONS
    assert recorder_filtered.count <= MAX_SELECTS


async def test_two_ticks_and_exists_filters_stay_flat(engine, session, client) -> None:
    """Соседний тик и EXISTS-фильтры не добавляют запросов.

    Страница опрашивается каждые 12 секунд: второй тик обязан стоить столько
    же, сколько первый. Фильтры по участку и текущему этапу — это EXISTS
    внутри основного SELECT'а, а не отдельные запросы на строку.
    """
    await _seed_all(session)

    with SqlRecorder(engine) as first_tick:
        first = await client.get("/api/production-planning/rows?limit=100")
    with SqlRecorder(engine) as second_tick:
        second = await client.get("/api/production-planning/rows?limit=100")
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first_tick.count == second_tick.count, (
        f"тик 1: {first_tick.count} SQL, тик 2: {second_tick.count} SQL"
    )
    baseline = first_tick.count

    section_id = await session.scalar(
        select(Section.id).where(Section.code == "P297-CUT")
    )
    for query in (
        f"limit=100&section_id={section_id}",
        "limit=100&current_stage_section_name=Раскрой",
        "limit=100&status=completed",
    ):
        with SqlRecorder(engine) as recorder:
            response = await client.get(f"/api/production-planning/rows?{query}")
        assert response.status_code == 200, response.text
        assert recorder.count <= baseline, (
            f"{query}: {recorder.count} SQL против {baseline} у базового тика"
        )


async def test_route_stage_without_section_does_not_add_queries(
    engine, session, client
) -> None:
    """Транзитный этап без участка не роняет строку и не тянет запросов.

    ``RouteStage.section_id`` допускает NULL (транзитный склад): выборка
    текущего этапа соединяет участок inner join'ом, поэтому такая строка
    уходит в fallback, а не в отдельный запрос.
    """
    await _seed_all(session)
    stage_id = await session.scalar(
        select(RouteStage.id)
        .where(RouteStage.sequence == 3)
        .order_by(RouteStage.id)
        .limit(1)
    )
    await session.execute(
        update(RouteStage).where(RouteStage.id == stage_id).values(section_id=None)
    )
    await session.commit()

    with SqlRecorder(engine) as recorder:
        response = await client.get("/api/production-planning/rows?limit=100")

    assert response.status_code == 200, response.text
    assert len(response.json()["rows"]) == 100
    assert recorder.count <= MAX_SELECTS, [
        statement[:140] for statement in recorder.selects
    ]
