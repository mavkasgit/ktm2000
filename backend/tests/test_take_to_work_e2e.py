"""E2E test: Import → Create positions → Take to work (release to shopfloor).

This test verifies:
1. Excel import creates positions with route_id
2. Positions can be taken to work (released)
3. Release batch positions have valid route_id
4. Route snapshot is correctly serialized
"""
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionRouteMatchQuality,
    PlanPositionRouteOrigin,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.release_batch import ReleaseBatchPosition
from app.models.route import ProductionRoute, RouteStage, RouteOperation
from app.models.section import Section
from app.services.plan_generation import create_release_batch


@pytest.mark.asyncio
async def test_take_position_to_work_with_dynamic_route(session) -> None:
    """E2E: Position with dynamic route can be taken to work (released to shopfloor)."""
    # Setup: Create product
    product = Product(sku="FG-TAKE-WORK", name="Test Product", type=ProductType.finished_good, unit="pcs")
    session.add(product)
    await session.flush()

    component = Product(sku="RAW-TW", name="Raw Material", type=ProductType.component, unit="pcs")
    session.add(component)
    await session.flush()

    await session.commit()

    # Create route with steps
    route = ProductionRoute(name="Test Route for Release", is_active=True)
    session.add(route)
    await session.flush()

    # Create sections
    sections = [
        Section(code="RAW_STOCK", name="Warehouse", sort_order=10, type="raw_stock", is_active=True),
        Section(code="PRESSING", name="Press", sort_order=30, type="production", is_active=True),
        Section(code="PACKING", name="Packing", sort_order=80, type="production", is_active=True),
    ]
    for section in sections:
        session.add(section)
    await session.flush()

    # Create route steps
    steps_data = [
        {"sequence": 1, "section_code": "RAW_STOCK", "op_code": "STOCK_IN", "op_name": "Receive", "is_significant": False},
        {"sequence": 2, "section_code": "PRESSING", "op_code": "PRESS_WINDOW", "op_name": "Press window", "is_significant": True},
        {"sequence": 3, "section_code": "PACKING", "op_code": "PACK_STRETCH", "op_name": "Pack stretch", "is_significant": False},
    ]

    for step_data in steps_data:
        section = (await session.execute(select(Section).where(Section.code == step_data["section_code"]))).scalar_one()
        stage = RouteStage(
            route_id=route.id,
            sequence=step_data["sequence"],
            section_id=section.id,
            is_significant=step_data["is_significant"],
        )
        session.add(stage)
        await session.flush()
        session.add(
            RouteOperation(
                route_stage_id=stage.id,
                sequence=1,
                operation_code=step_data["op_code"],
                operation_name=step_data["op_name"],
            )
        )
    await session.commit()

    # Create plan
    plan = ProductionPlan(plan_no="TEST-PLAN-WORK", name="Test Plan for Release")
    session.add(plan)
    await session.flush()

    # Create position WITH route_id (simulating successful import)
    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.excel_import,
        source_sku=product.sku,
        output_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("500"),
        route_id=route.id,  # CRITICAL: Must have route_id!
        route_origin=PlanPositionRouteOrigin.auto.value,
        route_assigned_at=datetime.now(UTC),
        route_match_quality=PlanPositionRouteMatchQuality.exact.value,
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.valid,
        source_payload={
            "route_name": route.name,
            "route_source": "dynamic_build",
        },
    )
    session.add(position)
    await session.commit()

    # Approve the plan and position (required before release)
    plan.status = ProductionPlanStatus.approved
    position.status = PlanPositionStatus.approved
    position.approved_at = datetime.now(UTC)
    await session.commit()

    # Take position to work (create release batch)
    batch_result = await create_release_batch(
        session,
        production_plan_id=plan.id,
        positions=[{"plan_position_id": position.id, "release_quantity": "500"}],
    )

    # Verify release batch was created
    assert batch_result is not None
    batch_id = batch_result.get("id")
    assert batch_id is not None

    # Verify batch positions have route_id
    batch_positions = await session.execute(
        select(ReleaseBatchPosition).where(ReleaseBatchPosition.release_batch_id == batch_id)
    )
    batch_positions_list = batch_positions.scalars().all()

    assert len(batch_positions_list) == 1
    batch_pos = batch_positions_list[0]

    # CRITICAL: route_id must NOT be null
    assert batch_pos.route_id is not None, "release_batch_positions.route_id MUST NOT be null!"
    assert batch_pos.route_id == route.id

    # Verify route_snapshot contains steps
    assert batch_pos.route_snapshot is not None
    assert "steps" in batch_pos.route_snapshot
    assert len(batch_pos.route_snapshot["steps"]) == 3


@pytest.mark.asyncio
async def test_take_position_to_work_fails_without_route(session) -> None:
    """Позиция без route_id в релиз не уходит: create_release_batch отказывает.

    Сетап доводит план и позицию до состояния «готова к релизу», чтобы
    единственной причиной отказа было отсутствие маршрута. До правки тест
    ничего не утверждал: try/except печатал исход, и тест проходил при любом
    поведении (в т.ч. если бы релиз молча создался).
    """
    product = Product(
        sku="FG-NO-ROUTE-RELEASE",
        name="No Route Product",
        type=ProductType.finished_good,
        unit="pcs",
    )
    session.add(product)

    plan = ProductionPlan(
        plan_no="TEST-NO-ROUTE",
        name="Test Plan No Route",
        status=ProductionPlanStatus.approved,
    )
    session.add(plan)
    await session.flush()

    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        output_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("100"),
        route_id=None,  # NO ROUTE!
        route_assigned_at=None,
        status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid,
    )
    session.add(position)
    await session.flush()

    with pytest.raises(ValueError, match="has no route assigned"):
        await create_release_batch(
            session,
            production_plan_id=plan.id,
            positions=[{"plan_position_id": position.id, "release_quantity": "100"}],
        )
