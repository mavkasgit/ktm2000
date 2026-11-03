"""Тесты свободного остатка (available_remainder_quantity)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.models.internal_plan import InternalPlan, SectionPlanLine
from app.models.product import Product, ProductPair, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.release_batch import (
    ReleaseBatch,
    ReleaseBatchPosition,
    ReleaseBatchStatus,
)
from app.models.route import ProductionRoute, RouteStage
from app.models.section import Section
from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.position_remainders import compute_position_stock_figures
from app.stock import Reason, StockCommand, StockCommandService
from sqlalchemy import event, select

pytestmark = pytest.mark.asyncio


def _count_sql(session):
    """Счётчик SQL на время блока с ``try/finally`` — по образцу тестов #290."""
    counter = {"n": 0}
    sync_engine = session.bind.sync_engine

    def _count(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(sync_engine, "before_cursor_execute", _count)
    return counter, lambda: event.remove(sync_engine, "before_cursor_execute", _count)

pytestmark = pytest.mark.asyncio


async def _add_stock(
    session,
    *,
    product: Product,
    stock_qty: Decimal,
    code: str,
) -> Section:
    """Положить остаток продукта на новый склад-хранилище."""
    stock = Section(code=code, name="Склад", type="raw_stock", is_active=True, sort_order=0)
    session.add(stock)
    await session.flush()

    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=product.id,
            to_location_id=stock.id,
            quantity=stock_qty,
            reason=Reason.MANUAL_IN,
            created_by=1,
        ),
    )
    await session.commit()
    return stock


async def _seed_product_stock(session, *, sku: str, stock_qty: Decimal) -> tuple[Product, Section]:
    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()
    stock = await _add_stock(
        session,
        product=product,
        stock_qty=stock_qty,
        code=f"{sku}-STK",
    )
    return product, stock


async def _seed_released_position(
    session,
    *,
    product: Product,
    route: ProductionRoute,
    stock_section: Section,
    prod_section: Section,
    quantity: Decimal,
    suffix: str = "",
) -> PlanPosition:
    plan = ProductionPlan(
        plan_no=f"P-REM{suffix}",
        name="Remainder plan",
        status=ProductionPlanStatus.draft,
    )
    session.add(plan)
    await session.flush()

    position = PlanPosition(
        production_plan_id=plan.id,
        source_type=PlanSourceType.excel_import,
        source_sku=product.sku,
        output_sku=product.sku,
        source_name=product.name,
        quantity=quantity,
        product_id=product.id,
        route_id=route.id,
        status=PlanPositionStatus.released,
        validation_status=PlanPositionValidationStatus.valid,
    )
    session.add(position)
    await session.flush()

    stage = RouteStage(route_id=route.id, sequence=1, section_id=prod_section.id, is_final=True)
    session.add(stage)
    await session.flush()

    from app.models.release_batch import ReleaseBatchType

    batch = ReleaseBatch(
        production_plan_id=plan.id,
        batch_no=f"RB-1{suffix}",
        name="Batch 1",
        batch_type=ReleaseBatchType.manual,
        status=ReleaseBatchStatus.released,
        created_by=1,
    )
    session.add(batch)
    await session.flush()
    session.add(
        ReleaseBatchPosition(
            release_batch_id=batch.id,
            plan_position_id=position.id,
            release_quantity=quantity,
            route_id=route.id,
            route_snapshot={"steps": [{"sequence": 1, "section_id": prod_section.id, "route_stage_id": stage.id}]},
        )
    )

    internal = InternalPlan(production_plan_id=plan.id, release_batch_id=batch.id)
    session.add(internal)
    await session.flush()

    line = SectionPlanLine(
        internal_plan_id=internal.id,
        plan_position_id=position.id,
        section_id=prod_section.id,
        product_id=product.id,
        route_id=route.id,
        route_stage_id=stage.id,
        sequence=1,
        planned_quantity=quantity,
    )
    session.add(line)
    await session.flush()

    task = WorkTask(
        section_plan_line_id=line.id,
        section_id=prod_section.id,
        product_id=product.id,
        route_stage_id=stage.id,
        planned_quantity=quantity,
        status=WorkTaskStatus.ready,
    )
    session.add(task)
    await session.commit()
    return position


async def _seed_released_pair_positions(
    session,
    *,
    product_a: Product,
    product_b: Product,
    quantity: Decimal,
    count: int,
    suffix: str,
) -> list[PlanPosition]:
    """Запущенные позиции пары: ``product_id`` пуст, резолв — по SKU.

    Строки плана несут один компонент (как в импорте пары), а спрос
    разложения должен лечь на оба: иначе проверка остатка была бы
    половинной — один компонент уменьшился бы, второй нет.
    """
    plan = ProductionPlan(
        plan_no=f"P-REMP-{suffix}", name="Pair remainder plan", status=ProductionPlanStatus.draft
    )
    session.add(plan)
    await session.flush()

    from app.models.release_batch import ReleaseBatchType

    batch = ReleaseBatch(
        production_plan_id=plan.id,
        batch_no=f"RB-PAIR-{suffix}",
        name="Pair batch",
        batch_type=ReleaseBatchType.manual,
        status=ReleaseBatchStatus.released,
        created_by=1,
    )
    session.add(batch)
    await session.flush()
    internal = InternalPlan(production_plan_id=plan.id, release_batch_id=batch.id)
    session.add(internal)
    await session.flush()

    # Свой маршрут и участок на каждый вызов: два вызова подряд в одном тесте
    # не должны делить stage (у него уникальный (route_id, sequence)).
    prod_section = Section(
        code=f"REMP-PROD-{suffix}",
        name="Цех",
        type="production",
        is_active=True,
        sort_order=1,
    )
    route = ProductionRoute(name=f"R-REMP-{suffix}", is_active=True)
    session.add_all([prod_section, route])
    await session.flush()
    stage = RouteStage(
        route_id=route.id, sequence=1, section_id=prod_section.id, is_final=True
    )
    session.add(stage)
    await session.flush()

    positions: list[PlanPosition] = []
    for index in range(count):
        position = PlanPosition(
            production_plan_id=plan.id,
            product_id=None,
            source_type=PlanSourceType.excel_import,
            source_sku=f"PAIR-{index}",
            quantity=quantity,
            route_id=route.id,
            status=PlanPositionStatus.released,
            validation_status=PlanPositionValidationStatus.valid,
            source_payload={
                "components": [{"sku": product_a.sku}, {"sku": product_b.sku}]
            },
        )
        session.add(position)
        await session.flush()
        session.add(
            ReleaseBatchPosition(
                release_batch_id=batch.id,
                plan_position_id=position.id,
                release_quantity=quantity,
                route_id=route.id,
                route_snapshot={
                    "steps": [
                        {
                            "sequence": 1,
                            "section_id": prod_section.id,
                            "route_stage_id": stage.id,
                        }
                    ]
                },
            )
        )
        line = SectionPlanLine(
            internal_plan_id=internal.id,
            plan_position_id=position.id,
            section_id=prod_section.id,
            product_id=product_a.id,
            route_id=route.id,
            route_stage_id=stage.id,
            sequence=1,
            planned_quantity=quantity,
        )
        session.add(line)
        await session.flush()
        session.add(
            WorkTask(
                section_plan_line_id=line.id,
                section_id=prod_section.id,
                product_id=product_a.id,
                route_stage_id=stage.id,
                planned_quantity=quantity,
                status=WorkTaskStatus.ready,
            )
        )
        positions.append(position)
    await session.commit()
    return positions


async def test_free_stock_is_physical_without_committed(session) -> None:
    product, _ = await _seed_product_stock(session, sku="REM-FREE", stock_qty=Decimal(5000))

    figures = await compute_position_stock_figures(session, [(1, [product.id], 100.0)])

    assert figures[1].free_stock == 5000.0
    assert figures[1].available_for_position == 5000.0
    assert figures[1].deficit == 0.0


async def test_other_released_position_lowers_available_but_not_free(session) -> None:
    """Чужая открытая позиция уменьшает «доступно», но не «свободно на складах»."""
    product, stock = await _seed_product_stock(session, sku="REM-COMMIT", stock_qty=Decimal(5000))
    prod = Section(code="REM-PROD", name="Цех", type="production", is_active=True, sort_order=1)
    route = ProductionRoute(name="R-REM", is_active=True)
    session.add_all([prod, route])
    await session.flush()

    neighbour = await _seed_released_position(
        session,
        product=product,
        route=route,
        stock_section=stock,
        prod_section=prod,
        quantity=Decimal(1200),
    )

    # Индикатор для позиции, которой здесь нет: её собственного спроса в
    # агрегате тоже нет, поэтому видно ровно чужую заявку — 5000 − 1200.
    figures = await compute_position_stock_figures(session, [(1, [product.id], 0.0)])

    assert figures[1].free_stock == 5000.0
    assert figures[1].available_for_position == 3800.0
    # Та же позиция, для которой посчитан индикатор, свой спрос не вычитает.
    own = await compute_position_stock_figures(
        session, [(neighbour, [product.id], 1200.0)]
    )
    assert own[neighbour].available_for_position == 5000.0


async def test_available_ignores_completed_positions(session) -> None:
    product, stock = await _seed_product_stock(session, sku="REM-DONE", stock_qty=Decimal(5000))
    prod = Section(code="REM-DONE-PROD", name="Цех", type="production", is_active=True, sort_order=1)
    route = ProductionRoute(name="R-DONE", is_active=True)
    session.add_all([prod, route])
    await session.flush()

    position = await _seed_released_position(
        session,
        product=product,
        route=route,
        stock_section=stock,
        prod_section=prod,
        quantity=Decimal(1200),
    )

    task = await session.scalar(select(WorkTask).join(SectionPlanLine).where(SectionPlanLine.plan_position_id == position.id))
    assert task is not None
    task.status = WorkTaskStatus.completed
    await session.commit()

    figures = await compute_position_stock_figures(
        session, [(position.id, [product.id], 1200.0)]
    )

    assert figures[position.id].available_for_position == 5000.0


async def _pair_setup(session, pairs: int = 1):
    """N пар артикулов и столько же строк в справочнике пар."""
    made: list[tuple[Product, Product]] = []
    for index in range(pairs):
        product_a = Product(
            sku=f"REMP-{index}-A", name=f"REMP-{index}-A",
            type=ProductType.component, unit="pcs", is_active=True,
        )
        product_b = Product(
            sku=f"REMP-{index}-B", name=f"REMP-{index}-B",
            type=ProductType.component, unit="pcs", is_active=True,
        )
        session.add_all([product_a, product_b])
        await session.flush()
        session.add(ProductPair(product_a_id=product_a.id, product_b_id=product_b.id))
        made.append((product_a, product_b))
    await session.commit()
    return made


async def test_pair_position_commits_demand_to_both_components(session) -> None:
    """Запущенная позиция пары занимает оба компонента, а не один.

    Строки позиции несут только ``product_a`` — второй компонент
    разворачивается резолвом пары. Если бы развёртки не было, «доступно»
    для второго компонента осталось бы полным.
    """
    from app.services.position_remainders import committed_demand_by_product_ids

    (product_a, product_b) = (await _pair_setup(session))[0]
    await _seed_released_pair_positions(
        session,
        product_a=product_a,
        product_b=product_b,
        quantity=Decimal(300),
        count=2,
        suffix="both",
    )

    demand = await committed_demand_by_product_ids(
        session, {product_a.id, product_b.id}
    )

    assert demand[product_a.id] == 600.0
    assert demand[product_b.id] == 600.0


async def test_pair_demand_sql_does_not_grow_with_distinct_pairs(session) -> None:
    """Справочник пар читается один раз, а не на каждую разную пару.

    Проверка именно на РАЗНЫХ парах: для повторов одной пары старый
    локальный мемо по ``pair_component_key`` тоже отсекал бы повтор, и такой
    тест прошёл бы и на старом коде. Разные пары — тот случай, где
    справочник раньше перечитывался целиком на каждой.
    """
    from app.services.position_remainders import committed_demand_by_product_ids

    pairs = await _pair_setup(session, pairs=3)
    all_products = {product.id for pair in pairs for product in pair}
    first_a, first_b = pairs[0]
    await _seed_released_pair_positions(
        session,
        product_a=first_a,
        product_b=first_b,
        quantity=Decimal(100),
        count=1,
        suffix="one",
    )
    counter, remove = _count_sql(session)
    try:
        one = await committed_demand_by_product_ids(session, all_products)
    finally:
        remove()

    for index, (product_a, product_b) in enumerate(pairs[1:], start=1):
        await _seed_released_pair_positions(
            session,
            product_a=product_a,
            product_b=product_b,
            quantity=Decimal(100),
            count=1,
            suffix=f"pair-{index}",
        )
    counter_many, remove_many = _count_sql(session)
    try:
        many = await committed_demand_by_product_ids(session, all_products)
    finally:
        remove_many()

    assert counter_many["n"] == counter["n"], (
        f"три разные пары дали {counter_many['n']} SQL против {counter['n']} у одной"
    )
    for product_a, product_b in pairs:
        assert many[product_a.id] == 100.0
        assert many[product_b.id] == 100.0
    # Первый замер сделан, когда позиция была только у первой пары, поэтому
    # `one` содержит лишь её артикулы — равенство с `many` здесь неверно.
    assert one == {pairs[0][0].id: 100.0, pairs[0][1].id: 100.0}


async def _new_production_route(session, suffix: str) -> tuple[Section, ProductionRoute]:
    """Свой участок и маршрут — две позиции одного теста не делят stage."""
    prod_section = Section(
        code=f"REM-{suffix}-PROD",
        name="Цех",
        type="production",
        is_active=True,
        sort_order=1,
    )
    route = ProductionRoute(name=f"R-REM-{suffix}", is_active=True)
    session.add_all([prod_section, route])
    await session.flush()
    return prod_section, route


async def test_alias_group_pool_adds_equivalent_stock_and_foreign_demand(
    session,
) -> None:
    """Остаток эквивалента входит в пул, чужая позиция любого члена его занимает.

    Позиция на A видит остаток B; чужая открытая позиция на B уменьшает
    «доступно», а собственная позиция себя не вычитает.
    """
    product_a, stock_a = await _seed_product_stock(
        session, sku="REM-POOL-A", stock_qty=Decimal(100)
    )
    product_b, stock_b = await _seed_product_stock(
        session, sku="REM-POOL-B", stock_qty=Decimal(250)
    )
    product_a.aliases = [product_b.sku]
    await session.commit()

    prod_a, route_a = await _new_production_route(session, "POOL-OWN")
    prod_b, route_b = await _new_production_route(session, "POOL-FOREIGN")
    own = await _seed_released_position(
        session,
        product=product_a,
        route=route_a,
        stock_section=stock_a,
        prod_section=prod_a,
        quantity=Decimal(50),
        suffix="-POOL-OWN",
    )
    await _seed_released_position(
        session,
        product=product_b,
        route=route_b,
        stock_section=stock_b,
        prod_section=prod_b,
        quantity=Decimal(120),
        suffix="-POOL-FOREIGN",
    )

    figures = await compute_position_stock_figures(
        session, [(own.id, [product_a.id], 50.0)]
    )

    # 100 + 250 — одна куча; 50 своей позиции не вычитаются, 120 чужой — да.
    assert figures[own.id].free_stock == 350.0
    assert figures[own.id].available_for_position == 230.0
    assert figures[own.id].deficit == 0.0


async def test_free_stock_breakdown_lists_group_skus_and_sums_to_free(
    session,
) -> None:
    product_a, _ = await _seed_product_stock(
        session, sku="REM-BD-A", stock_qty=Decimal(100)
    )
    product_b, _ = await _seed_product_stock(
        session, sku="REM-BD-B", stock_qty=Decimal(250)
    )
    product_a.aliases = [product_b.sku]
    await session.commit()

    figures = await compute_position_stock_figures(
        session, [(1, [product_a.id], 0.0)]
    )
    fields = figures[1].as_fields()

    assert fields["free_stock_quantity"] == 350.0
    assert fields["free_stock_breakdown"] == [
        {"product_id": product_a.id, "sku": "REM-BD-A", "quantity": 100.0},
        {"product_id": product_b.id, "sku": "REM-BD-B", "quantity": 250.0},
    ]
    assert sum(
        row["quantity"] for row in fields["free_stock_breakdown"]
    ) == fields["free_stock_quantity"]


async def test_no_group_is_none_but_group_without_balance_is_zero(session) -> None:
    """«Нет данных» и «действительно ноль» остаются разными ответами."""
    product = Product(
        sku="REM-ZERO",
        name="REM-ZERO",
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
    )
    session.add(product)
    await session.commit()

    zero = await compute_position_stock_figures(
        session, [(1, [product.id], 10.0)]
    )
    assert zero[1].free_stock == 0.0
    assert zero[1].available_for_position == 0.0
    assert zero[1].deficit == 10.0
    assert zero[1].as_fields()["free_stock_breakdown"] == []

    missing = await compute_position_stock_figures(
        session, [(2, [2_000_000_000], 10.0)]
    )
    assert missing[2].free_stock is None
    assert missing[2].available_for_position is None
    assert missing[2].deficit is None
    assert missing[2].as_fields()["free_stock_breakdown"] == []


async def test_pair_in_one_group_needs_two_quantities(session) -> None:
    """Пара внутри одной группы занимает ``2Q`` этой группы, а не ``Q``."""
    product_a, product_b = (await _pair_setup(session))[0]
    product_a.aliases = [product_b.sku]
    await session.commit()
    await _add_stock(
        session,
        product=product_a,
        stock_qty=Decimal(400),
        code="REM-SAME-GROUP-A-STK",
    )
    positions = await _seed_released_pair_positions(
        session,
        product_a=product_a,
        product_b=product_b,
        quantity=Decimal(300),
        count=1,
        suffix="same-group",
    )

    figures = await compute_position_stock_figures(
        session,
        [(positions[0].id, [product_a.id, product_b.id], 300.0)],
    )

    assert figures[positions[0].id].free_stock == 400.0
    assert figures[positions[0].id].available_for_position == 400.0
    assert figures[positions[0].id].deficit == 200.0


async def test_pair_in_different_groups_binds_to_weakest_group(session) -> None:
    """Пара в разных группах связывает минимум, дефицит — максимум по группам."""
    product_a, product_b = (await _pair_setup(session))[0]
    await _add_stock(
        session,
        product=product_a,
        stock_qty=Decimal(500),
        code="REM-DIFF-GROUP-A-STK",
    )
    await _add_stock(
        session,
        product=product_b,
        stock_qty=Decimal(100),
        code="REM-DIFF-GROUP-B-STK",
    )
    positions = await _seed_released_pair_positions(
        session,
        product_a=product_a,
        product_b=product_b,
        quantity=Decimal(200),
        count=1,
        suffix="diff-group",
    )

    figures = await compute_position_stock_figures(
        session,
        [(positions[0].id, [product_a.id, product_b.id], 200.0)],
    )
    position = figures[positions[0].id]

    # A: 500 свободно, нужно 200 — не связывает. B: 100 — связывает и по
    # свободному, и по доступному; дефицит B — 200 − 100.
    assert position.free_stock == 100.0
    assert position.available_for_position == 100.0
    assert position.deficit == 100.0
    assert position.as_fields()["free_stock_breakdown"] == [
        {"product_id": product_b.id, "sku": product_b.sku, "quantity": 100.0}
    ]

