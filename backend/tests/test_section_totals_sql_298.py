"""SQL-регресс сводки плана по участкам (#298, место 4).

``GET /production-plans/{id}/section-totals`` читает этапы маршрутов, чтобы
посчитать по участкам число позиций и количества. До правки этапы грузились
**по одному запросу на каждый уникальный маршрут**, причём вместе с ORM-сущностью
``Section``: её связи объявлены ``lazy="selectin"`` (``users``, ``operations``,
``spg_links``), а ``RouteStage.operations`` — тоже selectin. Один маршрут стоил
пяти SELECT'ов, и сводка плана с десятком маршрутов — десятков.

Теперь участки и этапы приходят одной joined-проекцией по всем ``route_id IN
(…)``: ни ORM-коллекций ``Section``, ни ``RouteStage.operations`` в кэше нет.
Тест фиксирует три вещи:

* число SELECT'ов не зависит от размера плана (2 маршрута/3 участка против
  5 маршрутов/6 участков) и укладывается в жёсткий потолок;
* запросы не трогают таблицы связей ``Section`` — именно их тянула
  материализация ORM;
* ответ прежний: те же участки, агрегаты и порядок, а транзитный этап без
  участка в сводку не попадает (его отсекает inner join, как и раньше).

Счёт — слушателем ``before_cursor_execute`` на engine, как в #292/#295/#297.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionRouteOrigin,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteStage
from app.models.section import Section

from tests.helpers.sql_counter import SqlRecorder

pytestmark = pytest.mark.asyncio

# Потолок на сводку: загрузка плана, позиции плана, снимок батч-резолва
# маршрутов (он сам константен, #292: маршруты + их этапы + операции этапов,
# правила подбора, продукты) и один запрос этапов/участков этой правки.
# До #298 на этой фикстуре было 24 SELECT'а (2 маршрута) и 39 (5 маршрутов):
# пять запросов на каждый уникальный маршрут, то есть число росло с планом.
MAX_SELECTS = 15

# Таблицы, чтение которых означает материализацию ORM-сущности Section:
# её связи объявлены selectin. Сводке они не нужны ни в каком размере;
# `route_operations` здесь нет намеренно — его читает батч-резолв маршрутов
# (#292) до этой правки.
FORBIDDEN_RELATIONSHIP_TABLES = (
    "section_operations",
    "spg_sections",
)

# `user_sections` читает и auth-зависимость: доступные участки пользователя
# (selectin `User.sections`, фильтр по `user_id`). Это не материализация
# `Section`, поэтому такой запрос разрешён; selectin `Section.users` фильтрует
# по `section_id` и остаётся под запретом.
_AUTH_USER_SECTIONS = "user_sections.user_id IN"


def _forbidden_queries(recorder: SqlRecorder) -> list[str]:
    queries = recorder.touching(FORBIDDEN_RELATIONSHIP_TABLES)
    queries += [
        statement
        for statement in recorder.touching(("user_sections",))
        if _AUTH_USER_SECTIONS not in statement
    ]
    return queries


async def _seed_plan(
    session,
    plan_no: str,
    route_sections: list[list[str]],
    *,
    positions_per_route: int,
    extras: bool = True,
) -> tuple[ProductionPlan, dict[str, Section], list[ProductionRoute]]:
    """План с маршрутами по списку кодов участков плюс пустые ветки.

    ``route_sections[i]`` — участки i-го маршрута по порядку этапов. Коды
    участков уникальны внутри плана: два плана в одном тесте не должны
    делить строки ``sections``, иначе identity map прятал бы запросы и замер
    сравнивал бы не то.
    """
    plan = ProductionPlan(
        plan_no=plan_no,
        name=f"План {plan_no}",
        status=ProductionPlanStatus.approved,
    )
    session.add(plan)
    await session.flush()

    product = Product(
        sku=f"{plan_no}-SKU",
        name=f"Артикул {plan_no}",
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
    )
    session.add(product)
    await session.flush()

    sections: dict[str, Section] = {}
    for codes in route_sections:
        for index, code in enumerate(codes):
            if code in sections:
                continue
            section = Section(
                code=code,
                name=f"Участок {code}",
                type="production",
                is_active=True,
                sort_order=len(sections) + index,
            )
            session.add(section)
            await session.flush()
            sections[code] = section

    routes: list[ProductionRoute] = []
    for index, codes in enumerate(route_sections):
        route = ProductionRoute(
            name=f"{plan_no}-R{index}", is_active=True, sort_order=index
        )
        session.add(route)
        await session.flush()
        for sequence, code in enumerate(codes, start=1):
            session.add(
                RouteStage(
                    route_id=route.id,
                    sequence=sequence,
                    section_id=sections[code].id,
                    is_final=sequence == len(codes),
                )
            )
        await session.flush()
        routes.append(route)

    def _position(**kwargs) -> PlanPosition:
        fields = {
            "production_plan_id": plan.id,
            "product_id": product.id,
            "source_type": PlanSourceType.manual,
            "source_sku": product.sku,
            "source_name": product.name,
            "quantity": Decimal(10),
            "source_payload": {},
            "status": PlanPositionStatus.approved,
            "validation_status": PlanPositionValidationStatus.valid,
            "validation_errors": [],
            "has_pack_ops": False,
            "route_origin": PlanPositionRouteOrigin.manual_confirmed,
        }
        fields.update(kwargs)
        return PlanPosition(**fields)

    positions: list[PlanPosition] = []
    for route in routes:
        for _ in range(positions_per_route):
            positions.append(_position(route_id=route.id))
    if extras:
        # Пустые ветки: без маршрута и без продукта. Позиция без маршрута на
        # плане с маршрутами уходит в подбор по правилам и может получить
        # маршрут — так же, как в проде; без продукта пропускается сразу.
        positions.append(_position(route_id=None))
        positions.append(_position(product_id=None, route_id=routes[0].id))
    session.add_all(positions)
    await session.flush()

    return plan, sections, routes


SMALL_ROUTES = [["T298-A1", "T298-A2"], ["T298-A1", "T298-A3"]]
LARGE_ROUTES = [
    ["T298-B1", "T298-B2", "T298-B3"],
    ["T298-B1", "T298-B4"],
    ["T298-B2", "T298-B1", "T298-B5"],
    ["T298-B6", "T298-B3"],
    ["T298-B1"],
]


@pytest.mark.parametrize(
    ("plan_no", "route_sections", "positions_per_route"),
    [
        ("P298-SMALL", SMALL_ROUTES, 3),
        ("P298-LARGE", LARGE_ROUTES, 4),
    ],
)
async def test_sql_count_within_ceiling(
    engine,
    session,
    client,
    plan_no: str,
    route_sections: list[list[str]],
    positions_per_route: int,
) -> None:
    """Сводка стоит не больше потолка на любом размере плана."""
    plan, _, _ = await _seed_plan(
        session, plan_no, route_sections, positions_per_route=positions_per_route
    )

    with SqlRecorder(engine) as recorder:
        response = await client.get(f"/api/production-plans/{plan.id}/section-totals")

    assert response.status_code == 200, response.text
    assert recorder.count <= MAX_SELECTS, "\n".join(
        f"{index}: {statement[:160]}" for index, statement in enumerate(recorder.selects)
    )
    forbidden = _forbidden_queries(recorder)
    assert forbidden == [], (
        "сводка материализует ORM-сущности со связями: "
        f"{[s[:100] for s in forbidden]}"
    )


async def test_sql_count_does_not_grow_with_routes_and_sections(
    engine, session, client
) -> None:
    """5 маршрутов/6 участков не добавляют ни одного SELECT'а к 2 маршрутам/3.

    Разница должна быть ровно нулевой: обе выборки — «все этапы маршрутов
    плана одним запросом», а не «по запросу на маршрут».
    """
    small_plan, _, _ = await _seed_plan(
        session, "P298-FLAT-SMALL", SMALL_ROUTES, positions_per_route=3
    )
    large_plan, _, _ = await _seed_plan(
        session, "P298-FLAT-LARGE", LARGE_ROUTES, positions_per_route=4
    )

    with SqlRecorder(engine) as recorder_small:
        small = await client.get(f"/api/production-plans/{small_plan.id}/section-totals")
    with SqlRecorder(engine) as recorder_large:
        large = await client.get(f"/api/production-plans/{large_plan.id}/section-totals")

    assert small.status_code == 200, small.text
    assert large.status_code == 200, large.text
    assert recorder_small.count == recorder_large.count, (
        f"2 маршрута: {recorder_small.count} SQL, "
        f"5 маршрутов: {recorder_large.count} SQL"
    )


async def test_response_sections_aggregates_and_order_unchanged(engine, session, client) -> None:
    """Ответ прежний: участки, агрегаты, порядок; транзитный этап не в счёте.

    Фикстура даёт разные количества по участкам, общий участок у двух
    маршрутов и транзитный этап без ``section_id``: сводка обязана сложить
    позиции по каждому участку, отсортировать по коду и не изобрести строку
    для склада транзита (его отсекает inner join — поведение до правки).
    """
    plan, sections, routes = await _seed_plan(
        session,
        "P298-RESPONSE",
        SMALL_ROUTES,
        positions_per_route=0,
        extras=False,
    )
    transit_storage = Section(
        code="T298-TRANSIT", name="Транзит", type="raw_stock", is_active=True
    )
    session.add(transit_storage)
    await session.flush()
    # Транзитный этап в конце первого маршрута: section_id NULL, есть только
    # storage_section_id. В сводке ему места нет.
    session.add(
        RouteStage(
            route_id=routes[0].id,
            sequence=3,
            section_id=None,
            storage_section_id=transit_storage.id,
            stage_kind="transit",
        )
    )

    def _position(route_id, quantity: int, **kwargs) -> PlanPosition:
        fields = {
            "production_plan_id": plan.id,
            "product_id": None,
            "source_type": PlanSourceType.manual,
            "source_sku": "T298-RESP",
            "source_name": "Позиция",
            "quantity": Decimal(quantity),
            "source_payload": {},
            "status": PlanPositionStatus.approved,
            "validation_status": PlanPositionValidationStatus.valid,
            "validation_errors": [],
            "has_pack_ops": False,
            "route_id": route_id,
            "route_origin": PlanPositionRouteOrigin.manual_confirmed,
        }
        fields.update(kwargs)
        return PlanPosition(**fields)

    product = Product(
        sku="T298-RESP-SKU", name="Артикул ответа", type=ProductType.finished_good, unit="pcs"
    )
    session.add(product)
    await session.flush()
    session.add_all(
        [
            _position(routes[0].id, 10, product_id=product.id),
            _position(routes[0].id, 5, product_id=product.id),
            _position(routes[1].id, 7, product_id=product.id),
            _position(routes[1].id, 1, product_id=product.id),
            # без продукта — пропускается, хотя маршрут есть
            _position(routes[0].id, 500),
        ]
    )
    await session.flush()

    response = await client.get(f"/api/production-plans/{plan.id}/section-totals")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["production_plan_id"] == plan.id
    # Сортировка по коду участка; транзитного склада в ответе нет.
    assert [line["section_code"] for line in body["totals"]] == [
        "T298-A1",
        "T298-A2",
        "T298-A3",
    ]
    totals = {line["section_code"]: line for line in body["totals"]}
    # T298-A1 — этап обоих маршрутов: 4 позиции, 10 + 5 + 7 + 1.
    assert totals["T298-A1"]["section_id"] == sections["T298-A1"].id
    assert totals["T298-A1"]["section_name"] == sections["T298-A1"].name
    assert totals["T298-A1"]["section_type"] == "production"
    assert totals["T298-A1"]["positions_count"] == 4
    assert totals["T298-A1"]["planned_input_quantity"] == "23.000"
    assert totals["T298-A1"]["planned_output_quantity"] == "23.000"
    # T298-A2 — только первый маршрут: 2 позиции, 15.
    assert totals["T298-A2"]["positions_count"] == 2
    assert totals["T298-A2"]["planned_input_quantity"] == "15.000"
    assert totals["T298-A2"]["planned_output_quantity"] == "15.000"
    # T298-A3 — только второй маршрут: 2 позиции, 8.
    assert totals["T298-A3"]["positions_count"] == 2
    assert totals["T298-A3"]["planned_input_quantity"] == "8.000"
    assert totals["T298-A3"]["planned_output_quantity"] == "8.000"

    # Пустой план: прежний короткий ответ.
    empty_plan = ProductionPlan(
        plan_no="P298-EMPTY", name="Пустой", status=ProductionPlanStatus.approved
    )
    session.add(empty_plan)
    await session.flush()
    empty = await client.get(f"/api/production-plans/{empty_plan.id}/section-totals")
    assert empty.status_code == 200, empty.text
    assert empty.json() == {"production_plan_id": empty_plan.id, "totals": []}
