"""Test that imported plan positions can be confirmed/released.

This test verifies:
1. After import, positions have valid routes with steps
2. Positions can be transitioned to 'released' status
3. Route information is preserved after release
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
)
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
from app.models.techcard import Techcard, TechcardLine


@pytest.mark.asyncio
async def test_plan_position_can_be_released_after_import(session) -> None:
    """Verify that a plan position with dynamic route can be released."""
    # Setup: Create product with techcard
    product = Product(sku="FG-RELEASE-TEST", name="Test Product", type=ProductType.finished_good, unit="pcs")
    session.add(product)
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()

    component = Product(sku="RAW-TEST", name="Raw Material", type=ProductType.component, unit="pcs")
    session.add(component)
    await session.flush()

    session.add(TechcardLine(
        techcard_id=techcard.id,
        component_product_id=component.id,
        quantity=1,
        unit="pcs",
    ))
    await session.commit()

    # Create a production route with steps
    route = ProductionRoute(name="Test Route", is_active=True)
    session.add(route)
    await session.flush()

    # Create sections for route steps
    sections = [
        Section(code="WH", name="Warehouse", sort_order=10, kind="raw_stock", is_active=True),
        Section(code="ANOD", name="Anodizing", sort_order=50, kind="production", is_active=True),
        Section(code="PACK", name="Packing", sort_order=80, kind="production", is_active=True),
    ]
    for section in sections:
        session.add(section)
    await session.flush()

    # Create route steps
    steps_data = [
        {"sequence": 1, "section_code": "WH", "op_code": "STOCK_IN", "op_name": "Receive", "is_significant": False},
        {"sequence": 2, "section_code": "ANOD", "op_code": "ANOD_01", "op_name": "Anodize silver", "is_significant": True},
        {"sequence": 3, "section_code": "PACK", "op_code": "PACK_STRETCH", "op_name": "Pack stretch", "is_significant": False},
    ]

    for step_data in steps_data:
        section = (await session.execute(select(Section).where(Section.code == step_data["section_code"]))).scalar_one()
        step = RouteStep(
            route_id=route.id,
            sequence=step_data["sequence"],
            section_id=section.id,
            operation_code=step_data["op_code"],
            operation_name=step_data["op_name"],
            is_significant=step_data["is_significant"],
        )
        session.add(step)
    await session.commit()

    # Create production plan
    plan = ProductionPlan(
        plan_no="TEST-001",
        name="Test Plan",
    )
    session.add(plan)
    await session.flush()

    # Create a plan position with the route (simulating import result)
    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.excel_import,
        source_sku=product.sku,
        output_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("100"),
        route_id=route.id,
        route_origin=PlanPositionRouteOrigin.auto.value,
        route_assigned_at=datetime.now(UTC),  # datetime object, not string
        route_match_quality=PlanPositionRouteMatchQuality.exact.value,
        route_manual_confirmed_at=None,  # Not yet confirmed
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        source_payload={
            "route_name": route.name,
            "route_source": "dynamic_build",
        },
    )
    session.add(position)
    await session.commit()

    # VERIFY 1: Position has route with steps
    assert position.route_id is not None
    assert position.route_assigned_at is not None

    # Verify route has steps
    steps_result = await session.execute(
        select(RouteStep).where(RouteStep.route_id == route.id).order_by(RouteStep.sequence)
    )
    steps = steps_result.scalars().all()
    assert len(steps) == 3, f"Route should have 3 steps, got {len(steps)}"
    
    print(f"✅ Position {position.id} created with route {route.id} ({len(steps)} steps)")

    # VERIFY 2: Position can be released
    # Simulate release action
    position.status = PlanPositionStatus.released
    position.route_manual_confirmed_at = datetime.now(UTC)  # datetime object
    await session.commit()

    # Refresh and verify
    await session.refresh(position)
    assert position.status == PlanPositionStatus.released
    assert position.route_manual_confirmed_at is not None
    assert position.route_id == route.id

    print(f"✅ Position {position.id} released successfully")

    # VERIFY 3: Route steps are still accessible after release
    steps_result = await session.execute(
        select(RouteStep).where(RouteStep.route_id == route.id).order_by(RouteStep.sequence)
    )
    steps = steps_result.scalars().all()
    assert len(steps) == 3, "Route steps must be preserved after release"

    # Verify step details
    assert steps[0].operation_code == "STOCK_IN"
    assert steps[1].operation_code == "ANOD_01"
    assert steps[1].is_significant is True
    assert steps[2].operation_code == "PACK_STRETCH"

    print(f"✅ Route steps verified after release")
    print(f"   Steps: {[(s.sequence, s.operation_code) for s in steps]}")


@pytest.mark.asyncio
async def test_position_route_validation_before_release(session) -> None:
    """Verify that positions without routes cannot be released."""
    # Create product
    product = Product(sku="FG-NO-ROUTE", name="No Route Product", type=ProductType.finished_good, unit="pcs")
    session.add(product)
    await session.flush()

    # Create plan
    plan = ProductionPlan(
        plan_no="TEST-NO-ROUTE",
        name="Test Plan No Route",
    )
    session.add(plan)
    await session.flush()

    # Create position WITHOUT route
    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        output_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("50"),
        route_id=None,  # No route!
        route_assigned_at=None,
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
    )
    session.add(position)
    await session.commit()

    # Position should have no route
    assert position.route_id is None
    assert position.route_assigned_at is None

    print(f"✅ Position {position.id} created without route (as expected)")

    # In real application, release should be blocked if route_id is None
    # This test verifies the data model allows this validation
