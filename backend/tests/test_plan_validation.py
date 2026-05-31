from datetime import date
from decimal import Decimal

import pytest

from app.models.techcard import Techcard, TechcardLine
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
)
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
from app.services.plan_validation import validate_plan_position


async def _make_ready_product(session, sku: str = "FG-1") -> tuple[Product, list[Section], ProductionRoute]:
    product = Product(sku=sku, name=f"Finished {sku}", type=ProductType.finished_good, unit="pcs")
    component = Product(sku=f"{sku}-RAW", name=f"Raw {sku}", type=ProductType.component, unit="pcs")
    sections = [
        Section(code=f"{sku}-CUT", name="Cut"),
        Section(code=f"{sku}-COLOR", name="Color"),
        Section(code=f"{sku}-PACK", name="Pack"),
    ]
    session.add_all([product, component, *sections])
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(TechcardLine(techcard_id=techcard.id, component_product_id=component.id, quantity=1, unit="pcs"))

    route = ProductionRoute(name="Main", is_active=True)
    session.add(route)
    await session.flush()
    for index, section in enumerate(sections, start=1):
        session.add(
            RouteStep(
                route_id=route.id,
                sequence=index,
                section_id=section.id,
                operation_name=f"Step {index}",
                is_final=index == len(sections),
            )
        )
    await session.flush()
    return product, sections, route


async def _make_plan_position(
    session,
    product: Product,
    quantity: Decimal = Decimal("100"),
    **kwargs,
) -> tuple[ProductionPlan, PlanPosition]:
    plan = ProductionPlan(
        plan_no=f"PLAN-{product.sku}",
        name=f"Plan {product.sku}",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()
    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=quantity,
        source_payload={},
        period_start=plan.period_start,
        period_end=plan.period_end,
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
        **kwargs,
    )
    session.add(position)
    await session.flush()
    return plan, position


@pytest.mark.asyncio
async def test_validate_position_fails_on_inactive_product(session) -> None:
    product = Product(
        sku="INACTIVE-1",
        name="Inactive Product",
        type=ProductType.finished_good,
        unit="pcs",
        is_active=False,
    )
    session.add(product)
    await session.flush()

    plan = ProductionPlan(plan_no="PLAN-TEST", name="Test Plan")
    session.add(plan)
    await session.flush()

    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("10"),
        source_payload={},
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
    )
    session.add(position)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "product_inactive" in errors


@pytest.mark.asyncio
async def test_validate_position_fails_on_duplicate_sku_due_date(session) -> None:
    product, _, _ = await _make_ready_product(session, "FG-DUP")
    plan = ProductionPlan(plan_no="PLAN-DUP", name="Dup Plan")
    session.add(plan)
    await session.flush()

    position1 = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("10"),
        due_date=date(2026, 5, 15),
        source_payload={},
        source_fingerprint="fp-duplicate-sku",
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
    )
    session.add(position1)
    await session.flush()

    position2 = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("20"),
        due_date=date(2026, 5, 15),
        source_payload={},
        source_fingerprint="fp-duplicate-sku",
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
    )
    session.add(position2)
    await session.flush()

    errors = await validate_plan_position(session, position2)
    assert "duplicate_sku_due_date" in errors


@pytest.mark.asyncio
async def test_validate_position_ignores_cancelled_duplicate(session) -> None:
    product, _, _ = await _make_ready_product(session, "FG-DUP-CAN")
    plan = ProductionPlan(plan_no="PLAN-DUP-CAN", name="Dup Plan Cancelled")
    session.add(plan)
    await session.flush()

    position1 = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("10"),
        due_date=date(2026, 5, 15),
        source_payload={},
        source_fingerprint="fp-dup-cancelled",
        status=PlanPositionStatus.cancelled,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
    )
    session.add(position1)
    await session.flush()

    position2 = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("20"),
        due_date=date(2026, 5, 15),
        source_payload={},
        source_fingerprint="fp-dup-cancelled",
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
    )
    session.add(position2)
    await session.flush()

    errors = await validate_plan_position(session, position2)
    assert "duplicate_sku_due_date" not in errors


@pytest.mark.asyncio
async def test_validate_position_passes_on_valid_position(session) -> None:
    product, _, route = await _make_ready_product(session, "FG-OK")
    plan, position = await _make_plan_position(session, product, route_id=route.id)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert errors == []


@pytest.mark.asyncio
async def test_validate_position_detects_product_not_found(session) -> None:
    plan = ProductionPlan(plan_no="PLAN-NO-PROD", name="No Product Plan")
    session.add(plan)
    await session.flush()

    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=None,
        source_type=PlanSourceType.manual,
        source_sku="MISSING",
        source_name="Missing",
        quantity=Decimal("10"),
        source_payload={},
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
    )
    session.add(position)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "product_not_found" in errors
    assert "product_inactive" not in errors


@pytest.mark.asyncio
async def test_validate_position_detects_missing_techcard(session) -> None:
    product = Product(sku="FG-NO-TECHCARD", name="No Techcard", type=ProductType.finished_good, unit="pcs")
    session.add(product)
    await session.flush()

    plan, position = await _make_plan_position(session, product)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "active_techcard_not_found" in errors


@pytest.mark.asyncio
async def test_validate_position_detects_empty_techcard(session) -> None:
    product = Product(sku="FG-EMPTY-TECHCARD", name="Empty Techcard", type=ProductType.finished_good, unit="pcs")
    session.add(product)
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()

    plan, position = await _make_plan_position(session, product)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "active_techcard_has_no_lines" in errors


@pytest.mark.asyncio
async def test_validate_position_detects_missing_route(session) -> None:
    product = Product(sku="FG-NO-ROUTE", name="No Route", type=ProductType.finished_good, unit="pcs")
    component = Product(sku="FG-NO-ROUTE-RAW", name="Raw", type=ProductType.component, unit="pcs")
    session.add_all([product, component])
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(TechcardLine(techcard_id=techcard.id, component_product_id=component.id, quantity=1, unit="pcs"))
    await session.flush()

    

    plan, position = await _make_plan_position(
        session,
        product,
        has_pack_ops=False,
    )
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "no_route_candidate" in errors


@pytest.mark.asyncio
async def test_validate_position_detects_empty_route(session) -> None:
    product = Product(sku="FG-EMPTY-ROUTE", name="Empty Route", type=ProductType.finished_good, unit="pcs")
    component = Product(sku="FG-EMPTY-ROUTE-RAW", name="Raw", type=ProductType.component, unit="pcs")
    session.add_all([product, component])
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(TechcardLine(techcard_id=techcard.id, component_product_id=component.id, quantity=1, unit="pcs"))

    route = ProductionRoute(name="Main", is_active=True)
    session.add(route)
    await session.flush()

    plan, position = await _make_plan_position(session, product, route_id=route.id)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "active_route_has_no_steps" in errors


@pytest.mark.asyncio
async def test_validate_position_detects_inactive_section(session) -> None:
    product = Product(sku="FG-INACT-SEC", name="Inactive Section", type=ProductType.finished_good, unit="pcs")
    component = Product(sku="FG-INACT-SEC-RAW", name="Raw", type=ProductType.component, unit="pcs")
    section = Section(code="CUT", name="Cut", is_active=False)
    session.add_all([product, component, section])
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(TechcardLine(techcard_id=techcard.id, component_product_id=component.id, quantity=1, unit="pcs"))

    route = ProductionRoute(name="Main", is_active=True)
    session.add(route)
    await session.flush()
    session.add(RouteStep(route_id=route.id, sequence=1, section_id=section.id, operation_name="Cut", is_final=True))
    await session.flush()

    plan, position = await _make_plan_position(session, product, route_id=route.id)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "route_contains_inactive_section" in errors
