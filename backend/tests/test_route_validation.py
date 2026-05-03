from datetime import date
from decimal import Decimal

import pytest

from app.models.bom import BOM, BOMLine
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
from app.services.route_validation import validate_route_match


async def _make_factory_route(
    session, sku: str, step_defs: list[tuple[str, str, str]]
) -> tuple[Product, ProductionRoute]:
    """Create a product with BOM, sections, and an active route.

    step_defs: list of (logical_code, section_kind, operation_name)
    """
    product = Product(
        sku=sku, name=f"Finished {sku}", type=ProductType.finished_good, unit="pcs"
    )
    component = Product(
        sku=f"{sku}-RAW", name=f"Raw {sku}", type=ProductType.component, unit="pcs"
    )
    session.add_all([product, component])
    await session.flush()

    bom = BOM(product_id=product.id, version="v1", is_active=True)
    session.add(bom)
    await session.flush()
    session.add(
        BOMLine(
            bom_id=bom.id, component_product_id=component.id, quantity=1, unit="pcs"
        )
    )

    sections = []
    for logical_code, kind, op_name in step_defs:
        sections.append(
            Section(code=f"{sku}-{logical_code}", name=logical_code, kind=kind)
        )
    session.add_all(sections)
    await session.flush()

    route = ProductionRoute(
        product_id=product.id, name="Main", version="v1", is_active=True
    )
    session.add(route)
    await session.flush()

    for index, (logical_code, _kind, op_name) in enumerate(step_defs, start=1):
        section = next(s for s in sections if s.name == logical_code)
        session.add(
            RouteStep(
                route_id=route.id,
                sequence=index,
                section_id=section.id,
                operation_name=op_name,
                is_final=index == len(step_defs),
            )
        )
    await session.flush()
    return product, route


async def _make_plan_position(
    session, product: Product, source_payload: dict
) -> PlanPosition:
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
        source_type=PlanSourceType.excel_import,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("100"),
        source_payload=source_payload,
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
    )
    session.add(position)
    await session.flush()
    return position


@pytest.mark.asyncio
async def test_validate_route_match_valid(session):
    product, route = await _make_factory_route(
        session,
        "FG-OK",
        [
            ("ISSUE", "raw_stock", "Выдача"),
            ("DRILL", "production", "Сверло"),
            ("SHOT", "production", "Дробеструй"),
            ("ANOD", "production", "Анод"),
            ("INTER", "wip_stock", "Пром.склад"),
            ("SAW", "production", "Пила"),
            ("PACK", "production", "Упаковка"),
            ("FINAL", "finished_stock", "Сдача"),
        ],
    )
    position = await _make_plan_position(
        session,
        product,
        {
            "operation_code": "DRILL",
            "output_kind": "finished_good",
            "additional_pack_operations": [],
            "paired_profile": False,
        },
    )

    issues = await validate_route_match(session, position)
    assert issues == []


@pytest.mark.asyncio
async def test_validate_route_match_pack_glue_as_attribute(session):
    product, route = await _make_factory_route(
        session,
        "FG-NO-GLUE",
        [
            ("ISSUE", "raw_stock", "Выдача"),
            ("DRILL", "production", "Сверло"),
            ("SHOT", "production", "Дробеструй"),
            ("ANOD", "production", "Анод"),
            ("INTER", "wip_stock", "Пром.склад"),
            ("SAW", "production", "Пила"),
            ("PACK", "production", "Упаковка"),
            ("FINAL", "finished_stock", "Сдача"),
        ],
    )
    position = await _make_plan_position(
        session,
        product,
        {
            "operation_code": "DRILL",
            "output_kind": "finished_good",
            "additional_pack_operations": [{"operation_code": "PACK_GLUE"}],
            "paired_profile": False,
        },
    )

    issues = await validate_route_match(session, position)
    assert issues == []


@pytest.mark.asyncio
async def test_validate_route_match_wrong_branch(session):
    # Expected semi_finished (direct to FINAL after ANOD),
    # but active route has WIP/INTER after ANOD
    product, route = await _make_factory_route(
        session,
        "FG-BRANCH",
        [
            ("ISSUE", "raw_stock", "Выдача"),
            ("DRILL", "production", "Сверло"),
            ("SHOT", "production", "Дробеструй"),
            ("ANOD", "production", "Анод"),
            ("INTER", "wip_stock", "Пром.склад"),
            ("SAW", "production", "Пила"),
            ("PACK", "production", "Упаковка"),
            ("FINAL", "finished_stock", "Сдача"),
        ],
    )
    position = await _make_plan_position(
        session,
        product,
        {
            "operation_code": "DRILL",
            "output_kind": "semi_finished_shipment",
            "additional_pack_operations": [],
            "paired_profile": False,
        },
    )

    issues = await validate_route_match(session, position)
    assert any("route_not_matching_import_signature" in i for i in issues)


@pytest.mark.asyncio
async def test_validate_route_match_missing_anod(session):
    product, route = await _make_factory_route(
        session,
        "FG-NO-ANOD",
        [
            ("ISSUE", "raw_stock", "Выдача"),
            ("DRILL", "production", "Сверло"),
            ("SHOT", "production", "Дробеструй"),
            ("INTER", "wip_stock", "Пром.склад"),
            ("SAW", "production", "Пила"),
            ("PACK", "production", "Упаковка"),
            ("FINAL", "finished_stock", "Сдача"),
        ],
    )
    position = await _make_plan_position(
        session,
        product,
        {
            "operation_code": "DRILL",
            "output_kind": "finished_good",
            "additional_pack_operations": [],
            "paired_profile": False,
        },
    )

    issues = await validate_route_match(session, position)
    assert any("route_missing_required_step" in i for i in issues)


@pytest.mark.asyncio
async def test_validate_route_match_primary_operation_mismatch(session):
    # Expected DRILL, but active route has PRESS_WINDOW
    product, route = await _make_factory_route(
        session,
        "FG-PRESS",
        [
            ("ISSUE", "raw_stock", "Выдача"),
            ("PRESS", "production", "PRESS_WINDOW"),
            ("SHOT", "production", "Дробеструй"),
            ("ANOD", "production", "Анод"),
            ("INTER", "wip_stock", "Пром.склад"),
            ("SAW", "production", "Пила"),
            ("PACK", "production", "Упаковка"),
            ("FINAL", "finished_stock", "Сдача"),
        ],
    )
    position = await _make_plan_position(
        session,
        product,
        {
            "operation_code": "DRILL",
            "output_kind": "finished_good",
            "additional_pack_operations": [],
            "paired_profile": False,
        },
    )

    issues = await validate_route_match(session, position)
    assert any("route_primary_operation_mismatch" in i for i in issues)
