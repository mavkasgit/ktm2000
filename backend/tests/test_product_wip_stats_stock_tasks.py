"""Складские fake-задачи не попадают в «В реальной работе».

Складская ``ready``-задача — это источник для Transfer: её создают
``_get_or_create_stock_fake_task`` (выдача) либо GET-хук экрана «Передачи».
Её ``route_stage_id`` указывает на транзитный этап маршрута, у которого по
контракту нет ``RouteOperation``, поэтому в блоке «В реальной работе на
производственных участках» она печаталась как «Неизвестная операция» с
планом позиции и нулями выдачи/завершения. Остатки по складам отдаёт
левая колонка модалки, поэтому в «в работе» такие строк быть не должно.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
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
from app.models.work_task import WorkTask, WorkTaskStatus
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _make_fixture(session: AsyncSession, sku: str) -> dict:
    """Маршрут склад → производство, где склад — транзитный этап (без операций)."""
    product = Product(sku=sku, name=f"Finished {sku}", type=ProductType.finished_good, unit="pcs")
    stock = Section(code=f"{sku}-PREP", name="Склад подготовки", type="wip_stock", is_active=True, sort_order=0)
    prod = Section(code=f"{sku}-ANOD", name="Анодирование", type="production", is_active=True, sort_order=1)
    session.add_all([product, stock, prod])
    await session.flush()

    route = ProductionRoute(name=f"Route {sku}", is_active=True)
    session.add(route)
    await session.flush()

    # Складской этап: stage_kind=transit, section_id=None, операций нет.
    transit = RouteStage(
        route_id=route.id,
        sequence=1,
        section_id=None,
        stage_kind="transit",
        storage_section_id=stock.id,
    )
    session.add(transit)
    await session.flush()

    prod_stage = RouteStage(
        route_id=route.id, sequence=2, section_id=prod.id, stage_kind="production", is_final=True
    )
    session.add(prod_stage)
    await session.flush()
    session.add(
        RouteOperation(
            route_stage_id=prod_stage.id, sequence=1, operation_code="ANO", operation_name="Анодирование"
        )
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
        quantity=Decimal(159),
        source_payload={},
        period_start=plan.period_start,
        period_end=plan.period_end,
        status=PlanPositionStatus.released,
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

    stock_line = SectionPlanLine(
        internal_plan_id=internal.id,
        plan_position_id=position.id,
        section_id=stock.id,
        product_id=product.id,
        route_id=route.id,
        route_stage_id=transit.id,
        sequence=1,
        planned_quantity=Decimal(159),
    )
    prod_line = SectionPlanLine(
        internal_plan_id=internal.id,
        plan_position_id=position.id,
        section_id=prod.id,
        product_id=product.id,
        route_id=route.id,
        route_stage_id=prod_stage.id,
        sequence=2,
        planned_quantity=Decimal(159),
    )
    session.add_all([stock_line, prod_line])
    await session.flush()

    # Складская fake-задача (источник для Transfer) и реальная производственная.
    session.add_all([
        WorkTask(
            section_plan_line_id=stock_line.id,
            section_id=stock.id,
            product_id=product.id,
            route_stage_id=transit.id,
            planned_quantity=Decimal(159),
            status=WorkTaskStatus.ready,
        ),
        WorkTask(
            section_plan_line_id=prod_line.id,
            section_id=prod.id,
            product_id=product.id,
            route_stage_id=prod_stage.id,
            planned_quantity=Decimal(159),
            status=WorkTaskStatus.in_progress,
        ),
    ])
    await session.commit()

    return {"product": product, "stock": stock, "prod": prod}


async def test_wip_stats_in_work_excludes_stock_tasks(client, session: AsyncSession) -> None:
    """Складская ready-задача не попадает в «в работе», производственная — да."""
    fx = await _make_fixture(session, "WIPSTK")

    resp = await client.get("/api/production-planning/product-wip-stats/WIPSTK")
    assert resp.status_code == 200, resp.text
    in_work = resp.json()["in_work"]

    assert [task["section_code"] for task in in_work] == [fx["prod"].code]
    assert [task["operation_name"] for task in in_work] == ["Анодирование"]
    assert all(task["operation_name"] != "Неизвестная операция" for task in in_work)