"""Занятость по каждому складу (#350).

Свободно/в работе/всего считаются в штуках по складу, а не агрегатом по
продукту. Тесты держат три свойства формулы:

* сумма строк равна итогу (``totals``);
* по каждому складу ``in_work + free == total``;
* пустой склад даёт нули, а не исчезает из ответа.

Занятость — производное от физического остатка (``StockBalance``) и спроса
открытых позиций (``committed_demand_by_product_ids``): второго учёта нет.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.core.security import create_access_token
from app.models.internal_plan import InternalPlan, SectionPlanLine
from app.models.product import Product, ProductType
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
    ReleaseBatchType,
)
from app.models.route import ProductionRoute, RouteStage
from app.models.section import Section
from app.models.user import User, UserRole
from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.warehouse_occupancy import warehouse_occupancy
from app.stock import Reason, StockCommand, StockCommandService

pytestmark = pytest.mark.asyncio


async def _make_user(session) -> User:
    user = User(
        username="occupancy-tester",
        email="occupancy-tester@local",
        full_name="Occupancy Tester",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_product(session, sku: str) -> Product:
    product = Product(
        sku=sku,
        name=sku,
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
    )
    session.add(product)
    await session.flush()
    return product


async def _make_warehouse(
    session, *, code: str, name: str, sort_order: int
) -> Section:
    section = Section(
        code=code,
        name=name,
        type="raw_stock",
        is_active=True,
        sort_order=sort_order,
    )
    session.add(section)
    await session.flush()
    return section


async def _add_stock(session, *, product: Product, warehouse: Section, qty: Decimal) -> None:
    await StockCommandService().record(
        session,
        StockCommand(
            product_id=product.id,
            to_location_id=warehouse.id,
            quantity=qty,
            reason=Reason.MANUAL_IN,
            created_by=1,
        ),
    )
    await session.commit()


async def _seed_open_position(
    session,
    *,
    product: Product,
    quantity: Decimal,
    suffix: str,
    task_status: WorkTaskStatus = WorkTaskStatus.ready,
) -> PlanPosition:
    """Запущенная позиция с открытой задачей — источник «занято» (#207/#350)."""
    plan = ProductionPlan(
        plan_no=f"P-OCC-{suffix}",
        name="Occupancy plan",
        status=ProductionPlanStatus.draft,
    )
    prod = Section(
        code=f"OCC-PROD-{suffix}",
        name=f"Цех {suffix}",
        type="production",
        is_active=True,
        sort_order=100,
    )
    route = ProductionRoute(name=f"R-OCC-{suffix}", is_active=True)
    session.add_all([plan, prod, route])
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

    stage = RouteStage(
        route_id=route.id, sequence=1, section_id=prod.id, is_final=True
    )
    session.add(stage)
    await session.flush()

    batch = ReleaseBatch(
        production_plan_id=plan.id,
        batch_no=f"RB-OCC-{suffix}",
        name="Occupancy batch",
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
            route_snapshot={
                "steps": [
                    {
                        "sequence": 1,
                        "section_id": prod.id,
                        "route_stage_id": stage.id,
                    }
                ]
            },
        )
    )

    internal = InternalPlan(production_plan_id=plan.id, release_batch_id=batch.id)
    session.add(internal)
    await session.flush()

    line = SectionPlanLine(
        internal_plan_id=internal.id,
        plan_position_id=position.id,
        section_id=prod.id,
        product_id=product.id,
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
            section_id=prod.id,
            product_id=product.id,
            route_stage_id=stage.id,
            planned_quantity=quantity,
            status=task_status,
        )
    )
    await session.commit()
    return position


def _by_warehouse(rows, warehouse_id: int):
    return next(row for row in rows.warehouses if row.warehouse_id == warehouse_id)


def _assert_sums(rows) -> None:
    """Итог — сумма строк, и по каждому складу in_work + free == total."""
    assert rows.in_work == sum(row.in_work for row in rows.warehouses)
    assert rows.free == sum(row.free for row in rows.warehouses)
    assert rows.total == sum(row.total for row in rows.warehouses)
    for row in rows.warehouses:
        assert row.in_work + row.free == row.total, row


async def test_open_position_occupies_warehouses_in_plant_order(session) -> None:
    product = await _make_product(session, "OCC-TWO")
    warehouse_a = await _make_warehouse(
        session, code="OCC-A", name="Склад А", sort_order=10
    )
    warehouse_b = await _make_warehouse(
        session, code="OCC-B", name="Склад Б", sort_order=20
    )
    await _add_stock(session, product=product, warehouse=warehouse_a, qty=Decimal(120))
    await _add_stock(session, product=product, warehouse=warehouse_b, qty=Decimal(30))
    await _seed_open_position(
        session, product=product, quantity=Decimal(50), suffix="two"
    )

    rows = await warehouse_occupancy(session)
    _assert_sums(rows)

    a = _by_warehouse(rows, warehouse_a.id)
    b = _by_warehouse(rows, warehouse_b.id)
    # Заявка закрывается первым складом системного порядка — 50 из 120.
    assert (a.in_work, a.free, a.total) == (50, 70, 120)
    # Второй склад не тронут: его остаток целиком свободен.
    assert (b.in_work, b.free, b.total) == (0, 30, 30)
    assert (rows.in_work, rows.free, rows.total) == (50, 100, 150)


async def test_empty_warehouse_returns_zeros(session) -> None:
    product = await _make_product(session, "OCC-EMPTY")
    filled = await _make_warehouse(
        session, code="OCC-FILLED", name="Склад с остатком", sort_order=10
    )
    empty = await _make_warehouse(
        session, code="OCC-EMPTY", name="Пустой склад", sort_order=20
    )
    await _add_stock(session, product=product, warehouse=filled, qty=Decimal(40))

    rows = await warehouse_occupancy(session)
    _assert_sums(rows)

    empty_row = _by_warehouse(rows, empty.id)
    assert (empty_row.in_work, empty_row.free, empty_row.total) == (0, 0, 0)


async def test_demand_bigger_than_stock_leaves_no_free_and_no_phantom(session) -> None:
    product = await _make_product(session, "OCC-SHORT")
    warehouse_a = await _make_warehouse(
        session, code="OCC-SA", name="Склад А", sort_order=10
    )
    warehouse_b = await _make_warehouse(
        session, code="OCC-SB", name="Склад Б", sort_order=20
    )
    await _add_stock(session, product=product, warehouse=warehouse_a, qty=Decimal(20))
    await _add_stock(session, product=product, warehouse=warehouse_b, qty=Decimal(10))
    await _seed_open_position(
        session, product=product, quantity=Decimal(100), suffix="short"
    )

    rows = await warehouse_occupancy(session)
    _assert_sums(rows)

    a = _by_warehouse(rows, warehouse_a.id)
    b = _by_warehouse(rows, warehouse_b.id)
    assert (a.in_work, a.free, a.total) == (20, 0, 20)
    assert (b.in_work, b.free, b.total) == (10, 0, 10)
    assert (rows.in_work, rows.free, rows.total) == (30, 0, 30)


async def test_occupancy_sums_across_products_per_warehouse(session) -> None:
    """Строка — склад, а не продукт: два артикула на одном складе складываются."""
    first = await _make_product(session, "OCC-P1")
    second = await _make_product(session, "OCC-P2")
    warehouse = await _make_warehouse(
        session, code="OCC-MIX", name="Общий склад", sort_order=10
    )
    await _add_stock(session, product=first, warehouse=warehouse, qty=Decimal(100))
    await _add_stock(session, product=second, warehouse=warehouse, qty=Decimal(50))
    await _seed_open_position(
        session, product=first, quantity=Decimal(40), suffix="mix-1"
    )
    await _seed_open_position(
        session, product=second, quantity=Decimal(50), suffix="mix-2"
    )

    rows = await warehouse_occupancy(session)
    _assert_sums(rows)

    row = _by_warehouse(rows, warehouse.id)
    assert (row.in_work, row.free, row.total) == (90, 60, 150)


async def test_closed_task_does_not_occupy(session) -> None:
    product = await _make_product(session, "OCC-CLOSED")
    warehouse = await _make_warehouse(
        session, code="OCC-CLOSED-WH", name="Склад", sort_order=10
    )
    await _add_stock(session, product=product, warehouse=warehouse, qty=Decimal(80))
    await _seed_open_position(
        session,
        product=product,
        quantity=Decimal(30),
        suffix="closed",
        task_status=WorkTaskStatus.completed,
    )

    rows = await warehouse_occupancy(session)
    _assert_sums(rows)

    row = _by_warehouse(rows, warehouse.id)
    assert (row.in_work, row.free, row.total) == (0, 80, 80)


async def test_api_returns_warehouse_rows_and_totals(client, session) -> None:
    user = await _make_user(session)
    client.headers["Authorization"] = f"Bearer {create_access_token(subject=user.email)}"

    product = await _make_product(session, "OCC-API")
    warehouse = await _make_warehouse(
        session, code="OCC-API-WH", name="Склад API", sort_order=10
    )
    await _add_stock(session, product=product, warehouse=warehouse, qty=Decimal(25))
    await _seed_open_position(
        session, product=product, quantity=Decimal(10), suffix="api"
    )

    response = await client.get("/api/stock/occupancy")
    assert response.status_code == 200, response.text

    data = response.json()
    row = next(item for item in data["warehouses"] if item["warehouse_id"] == warehouse.id)
    assert row["warehouse"] == "Склад API"
    assert row["warehouse_code"] == "OCC-API-WH"
    assert (row["in_work"], row["free"], row["total"]) == (10, 15, 25)
    assert data["totals"]["in_work"] == sum(
        item["in_work"] for item in data["warehouses"]
    )
    assert data["totals"]["total"] == sum(item["total"] for item in data["warehouses"])
