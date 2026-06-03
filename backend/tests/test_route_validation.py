from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.techcard import Techcard, TechcardLine
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionRouteOrigin,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
)

from app.models.route import ProductionRoute, RouteSelectionRule, RouteStage, RouteOperation
from app.models.section import Section
from app.services.route_validation import validate_route_match


async def _make_factory_route(
    session, sku: str, step_defs: list[tuple[str, str, str]]
) -> tuple[Product, ProductionRoute]:
    """Create a product with techcard, sections, and an active route.

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

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(
        TechcardLine(
            techcard_id=techcard.id, component_product_id=component.id, quantity=1, unit="pcs"
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
        name=f"Main-{sku}", is_active=True
    )
    session.add(route)
    await session.flush()

    for index, (logical_code, _kind, op_name) in enumerate(step_defs, start=1):
        section = next(s for s in sections if s.name == logical_code)
        stage = RouteStage(
            route_id=route.id,
            sequence=index,
            section_id=section.id,
            is_final=index == len(step_defs),
        )
        session.add(stage)
        await session.flush()
        session.add(
            RouteOperation(
                route_stage_id=stage.id,
                sequence=1,
                operation_code=logical_code,
                operation_name=op_name,
            )
        )
    await session.flush()
    return product, route


async def _make_plan_position(
    session, product: Product, source_payload: dict, route_id: int
) -> PlanPosition:
    plan = ProductionPlan(
        plan_no=f"PLAN-{product.sku}",
        name=f"Plan {product.sku}",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()
    output_kind_val = source_payload.get("output_kind")
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
        route_id=route_id,
        has_pack_ops=bool(source_payload.get("additional_pack_operations")),
    )
    session.add(position)
    await session.flush()
    return position


async def _section_id(session, sku: str, logical_code: str) -> int:
    section = await session.scalar(select(Section).where(Section.code == f"{sku}-{logical_code}"))
    if section is None:
        section = Section(code=f"{sku}-{logical_code}", name=logical_code, kind="production")
        session.add(section)
        await session.flush()
    return section.id


async def _add_selection_rule(session, sku: str, actions: list[tuple[str, str]]) -> None:
    resolved_actions = []
    for action, logical_code in actions:
        resolved_actions.append({"action": action, "section_id": await _section_id(session, sku, logical_code)})
    session.add(
        RouteSelectionRule(
            code=f"rule-{sku}",
            name=f"Rule {sku}",
            priority=100,
            is_active=True,
            conditions=[],
            actions=resolved_actions,
        )
    )
    await session.flush()


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
        route.id,
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
        route.id,
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
        route.id,
    )

    await _add_selection_rule(
        session,
        "FG-BRANCH",
        [("exclude_section", "INTER"), ("exclude_section", "SAW"), ("exclude_section", "PACK")],
    )

    issues = await validate_route_match(session, position)
    assert any("route_contains_excluded_step" in i for i in issues)


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
        route.id,
    )

    await _add_selection_rule(session, "FG-NO-ANOD", [("require_section", "ANOD")])

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
        route.id,
    )

    await _add_selection_rule(session, "FG-PRESS", [("require_section", "DRILL"), ("exclude_section", "PRESS")])

    issues = await validate_route_match(session, position)
    assert any("route_missing_required_step" in i or "route_contains_excluded_step" in i for i in issues)


@pytest.mark.asyncio
async def test_validate_route_match_skips_for_manual_confirmed(session):
    # Same mismatch scenario as above, but with manual-confirmed route.
    product, route = await _make_factory_route(
        session,
        "FG-MANUAL",
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
        route.id,
    )
    position.route_origin = PlanPositionRouteOrigin.manual_confirmed
    await session.flush()

    issues = await validate_route_match(session, position)
    assert issues == []
