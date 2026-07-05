"""Тесты свободного остатка (available_remainder_quantity)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

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
from app.models.release_batch import ReleaseBatch, ReleaseBatchPosition, ReleaseBatchStatus
from app.models.route import ProductionRoute, RouteStage
from app.models.section import Section
from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.position_remainders import compute_available_remainder_quantities
from app.stock import Reason, StockCommand, StockCommandService

pytestmark = pytest.mark.asyncio


async def _seed_product_stock(session, *, sku: str, stock_qty: Decimal) -> tuple[Product, Section]:
    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    stock = Section(code=f"{sku}-STK", name="Склад", type="raw_stock", is_active=True, sort_order=0)
    session.add_all([product, stock])
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
    return product, stock


async def _seed_released_position(
    session,
    *,
    product: Product,
    route: ProductionRoute,
    stock_section: Section,
    prod_section: Section,
    quantity: Decimal,
) -> PlanPosition:
    plan = ProductionPlan(plan_no="P-REM", name="Remainder plan", status=ProductionPlanStatus.draft)
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
        batch_no="RB-1",
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


async def test_available_is_physical_stock_without_committed(session) -> None:
    product, _ = await _seed_product_stock(session, sku="REM-FREE", stock_qty=Decimal("5000"))

    available = await compute_available_remainder_quantities(session, {product.id})

    assert available[product.id] == 5000.0


async def test_available_subtracts_released_open_positions(session) -> None:
    product, stock = await _seed_product_stock(session, sku="REM-COMMIT", stock_qty=Decimal("5000"))
    prod = Section(code="REM-PROD", name="Цех", type="production", is_active=True, sort_order=1)
    route = ProductionRoute(name="R-REM", is_active=True)
    session.add_all([prod, route])
    await session.flush()

    await _seed_released_position(
        session,
        product=product,
        route=route,
        stock_section=stock,
        prod_section=prod,
        quantity=Decimal("1200"),
    )

    available = await compute_available_remainder_quantities(session, {product.id})

    assert available[product.id] == 3800.0


async def test_available_ignores_completed_positions(session) -> None:
    product, stock = await _seed_product_stock(session, sku="REM-DONE", stock_qty=Decimal("5000"))
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
        quantity=Decimal("1200"),
    )

    task = await session.scalar(select(WorkTask).join(SectionPlanLine).where(SectionPlanLine.plan_position_id == position.id))
    assert task is not None
    task.status = WorkTaskStatus.completed
    await session.commit()

    available = await compute_available_remainder_quantities(session, {product.id})

    assert available[product.id] == 5000.0