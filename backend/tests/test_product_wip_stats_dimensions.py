"""Тикет #97: сводка артикула (модалка) — разбивка по размерам.

Остатки на ГХП и задачи в работе показывают размер каждой строки
(``dimensions``/``dimensions_label``); разные размеры одного SKU не
сводятся в общий итог по артикулу (CONTEXT.md → «Сводка артикула»).
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_plan import InternalPlan, SectionPlanLine
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
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.techcard import Techcard, TechcardLine
from app.models.work_task import WorkTask, WorkTaskStatus
from app.stock import Reason, StockCommand, StockCommandService

pytestmark = pytest.mark.asyncio


async def _make_fixture(session: AsyncSession, sku: str) -> dict:
    """Продукт + маршрут (склад → производство), СПГ на складе."""
    product = Product(sku=sku, name=f"Finished {sku}", type=ProductType.finished_good, unit="pcs")
    stock = Section(code=f"{sku}-STOCK", name="Склад", type="raw_stock", is_active=True, sort_order=0)
    prod = Section(code=f"{sku}-PROD", name="Участок", type="production", is_active=True, sort_order=1)
    session.add_all([product, stock, prod])
    await session.flush()

    spg = StorageProductionGroup(code=f"{sku}-SPG", name=f"СПГ {sku}", is_active=True, sort_order=0)
    session.add(spg)
    await session.flush()
    session.add(SpgSection(spg_id=spg.id, section_id=stock.id, sort_order=0))

    route = ProductionRoute(name=f"Route {sku}", is_active=True)
    session.add(route)
    await session.flush()

    stages: list[RouteStage] = []
    for idx, (section, op_code) in enumerate([(stock, "ISSUE"), (prod, "DRILL")], start=1):
        stage = RouteStage(
            route_id=route.id,
            sequence=idx,
            section_id=section.id,
            is_final=idx == 2,
        )
        session.add(stage)
        await session.flush()
        session.add(
            RouteOperation(route_stage_id=stage.id, sequence=1, operation_code=op_code, operation_name=op_code)
        )
        stages.append(stage)

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(
        TechcardLine(techcard_id=techcard.id, component_product_id=product.id, quantity=Decimal("1"), unit="pcs")
    )

    plan = ProductionPlan(
        plan_no=f"PLAN-{sku}",
        name=f"Plan {sku}",
        status=ProductionPlanStatus.approved,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
    )
    session.add(plan)
    await session.flush()

    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("100"),
        source_payload={},
        period_start=plan.period_start,
        period_end=plan.period_end,
        status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        route_id=route.id,
        route_origin=PlanPositionRouteOrigin.manual_confirmed,
        route_assigned_at=datetime.now(UTC),
        route_manual_confirmed_at=datetime.now(UTC),
    )
    session.add(position)
    await session.flush()

    internal = InternalPlan(production_plan_id=plan.id)
    session.add(internal)
    await session.flush()

    line = SectionPlanLine(
        internal_plan_id=internal.id,
        plan_position_id=position.id,
        section_id=prod.id,
        product_id=product.id,
        route_id=route.id,
        route_stage_id=stages[1].id,
        sequence=1,
        planned_quantity=Decimal("100"),
    )
    session.add(line)
    await session.flush()
    await session.commit()

    return {
        "product": product,
        "stock": stock,
        "prod": prod,
        "spg": spg,
        "line": line,
        "prod_stage": stages[1],
    }


async def _seed_balance(
    session: AsyncSession,
    *,
    location_id: int,
    product_id: int,
    qty: Decimal,
    dimensions: dict | None,
) -> None:
    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=product_id,
            to_location_id=location_id,
            quantity=qty,
            reason=Reason.MANUAL_IN,
            dimensions=dimensions,
            created_by=1,
        ),
    )
    await session.commit()


async def test_wip_stats_remainders_split_by_dimensions(client, session) -> None:
    """Остатки на ГХП разбиваются по размерам: две строки, а не один итог."""
    fx = await _make_fixture(session, "WIP-DIM-1")
    sku = fx["product"].sku
    await _seed_balance(
        session, location_id=fx["stock"].id, product_id=fx["product"].id,
        qty=Decimal("10"), dimensions={"length_mm": 2000},
    )
    await _seed_balance(
        session, location_id=fx["stock"].id, product_id=fx["product"].id,
        qty=Decimal("4"), dimensions={"length_mm": 3000},
    )

    resp = await client.get(f"/api/production-planning/product-wip-stats/{sku}")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert len(data["remainders"]) == 2
    by_len = {r["dimensions"]["length_mm"]: r for r in data["remainders"]}
    assert set(by_len) == {2000, 3000}
    assert by_len[2000]["quantity"] == 10.0
    assert by_len[3000]["quantity"] == 4.0
    assert by_len[2000]["dimensions_label"] == "2 м"
    assert by_len[3000]["dimensions_label"] == "3 м"


async def test_wip_stats_remainders_merge_same_dimension(client, session) -> None:
    """Одинаковые размеры на одной секции складываются в одну строку."""
    fx = await _make_fixture(session, "WIP-DIM-2")
    sku = fx["product"].sku
    await _seed_balance(
        session, location_id=fx["stock"].id, product_id=fx["product"].id,
        qty=Decimal("10"), dimensions={"length_mm": 2000},
    )
    await _seed_balance(
        session, location_id=fx["stock"].id, product_id=fx["product"].id,
        qty=Decimal("4"), dimensions={"length_mm": 2000},
    )

    resp = await client.get(f"/api/production-planning/product-wip-stats/{sku}")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert len(data["remainders"]) == 1
    row = data["remainders"][0]
    assert row["dimensions"] == {"length_mm": 2000}
    assert row["quantity"] == 14.0


async def test_wip_stats_in_work_split_by_dimensions(client, session) -> None:
    """Задачи в работе группируются по размеру задания: две строки."""
    fx = await _make_fixture(session, "WIP-DIM-3")
    sku = fx["product"].sku

    tasks = [
        WorkTask(
            section_plan_line_id=fx["line"].id,
            section_id=fx["prod"].id,
            product_id=fx["product"].id,
            route_stage_id=fx["prod_stage"].id,
            planned_quantity=Decimal("100"),
            dimensions={"length_mm": 2000},
            status=WorkTaskStatus.in_progress,
        ),
        WorkTask(
            section_plan_line_id=fx["line"].id,
            section_id=fx["prod"].id,
            product_id=fx["product"].id,
            route_stage_id=fx["prod_stage"].id,
            planned_quantity=Decimal("100"),
            dimensions={"length_mm": 3000},
            status=WorkTaskStatus.in_progress,
        ),
    ]
    session.add_all(tasks)
    await session.commit()

    resp = await client.get(f"/api/production-planning/product-wip-stats/{sku}")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert len(data["in_work"]) == 2
    by_len = {t["dimensions"]["length_mm"]: t for t in data["in_work"]}
    assert set(by_len) == {2000, 3000}
    assert by_len[2000]["dimensions_label"] == "2 м"
    assert by_len[3000]["dimensions_label"] == "3 м"
    assert by_len[2000]["active_tasks_count"] == 1
    assert by_len[3000]["active_tasks_count"] == 1


async def test_wip_stats_in_work_dimensionless(client, session) -> None:
    """Безразмерные задачи группируются в строку с dimensions=None и «—»."""
    fx = await _make_fixture(session, "WIP-DIM-4")
    sku = fx["product"].sku

    task = WorkTask(
        section_plan_line_id=fx["line"].id,
        section_id=fx["prod"].id,
        product_id=fx["product"].id,
        route_stage_id=fx["prod_stage"].id,
        planned_quantity=Decimal("100"),
        dimensions=None,
        status=WorkTaskStatus.ready,
    )
    session.add(task)
    await session.commit()

    resp = await client.get(f"/api/production-planning/product-wip-stats/{sku}")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert len(data["in_work"]) == 1
    row = data["in_work"][0]
    assert row["dimensions"] is None
    assert row["dimensions_label"] == "—"
