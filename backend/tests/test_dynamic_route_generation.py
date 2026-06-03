"""Tests for dynamic route generation during import.

Verifies that:
1. Dynamic routes are created as real ProductionRoute entities
2. Routes are reused by name + template_id within same import
3. Route steps are correctly created
4. route_assigned_at is set properly
"""
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.import_template import ImportTemplate
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanChangeItem,
    PlanChangeItemStatus,
    PlanChangeSet,
    PlanPosition,
    PlanPositionRouteOrigin,
    PlanPositionRouteMatchQuality,
    PlanPositionStatus,
    PlanSourceType,
    ProductionPlan,
)
from app.models.route import ProductionRoute, RouteRuleProfile, RouteSelectionRule, RouteStage, RouteOperation, SectionOperation
from app.models.section import Section
from app.models.techcard import Techcard, TechcardLine
from app.services.plan_import_service import _make_change_items


DEFAULT_SECTIONS = [
    {"code": "WH", "name": "Склад сырья", "sort_order": 10, "kind": "raw_stock"},
    {"code": "DRILL", "name": "Сверловка", "sort_order": 20, "kind": "production"},
    {"code": "PRESS", "name": "Пресс", "sort_order": 30, "kind": "production"},
    {"code": "ANOD", "name": "Анодирование", "sort_order": 50, "kind": "production"},
    {"code": "PACK", "name": "Упаковка", "sort_order": 80, "kind": "production"},
    {"code": "FG_WH", "name": "Склад готовой продукции", "sort_order": 90, "kind": "finished_stock"},
]


async def _seed_sections(session) -> None:
    for item in DEFAULT_SECTIONS:
        section = Section(
            code=item["code"],
            name=item["name"],
            sort_order=item["sort_order"],
            kind=item["kind"],
            is_active=True,
        )
        session.add(section)
    await session.flush()

    # Add SectionOperation for ANOD section
    anod_section = (await session.execute(select(Section).where(Section.code == "ANOD"))).scalar_one()
    session.add(SectionOperation(
        section_id=anod_section.id,
        operation_code="ANOD_01",
        operation_name="Анодирование серебро",
        group_code="ANOD",
        group_name="Анодирование",
        is_significant=True,
        sort_order=1,
    ))
    session.add(SectionOperation(
        section_id=anod_section.id,
        operation_code="ANOD_05",
        operation_name="Анодирование чёрный",
        group_code="ANOD",
        group_name="Анодирование",
        is_significant=True,
        sort_order=2,
    ))

    # Add SectionOperation for PACK section
    pack_section = (await session.execute(select(Section).where(Section.code == "PACK"))).scalar_one()
    session.add(SectionOperation(
        section_id=pack_section.id,
        operation_code="PACK_STRETCH",
        operation_name="Упаковка стрейч",
        group_code="PACK",
        group_name="Упаковка",
        is_significant=False,
        sort_order=1,
    ))
    session.add(SectionOperation(
        section_id=pack_section.id,
        operation_code="PACK_SPUNBOND",
        operation_name="Упаковка спанбонд",
        group_code="PACK",
        group_name="Упаковка",
        is_significant=False,
        sort_order=2,
    ))

    await session.commit()


async def _make_product_with_techcard(session, sku: str = "FG-TEST") -> Product:
    product = Product(
        sku=sku,
        name=f"Test Product {sku}",
        type=ProductType.finished_good,
        unit="pcs",
    )
    session.add(product)
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()

    component = Product(sku=f"{sku}-RAW", name=f"Raw {sku}", type=ProductType.component, unit="pcs")
    session.add(component)
    await session.flush()

    session.add(TechcardLine(
        techcard_id=techcard.id,
        component_product_id=component.id,
        quantity=1,
        unit="pcs",
    ))
    await session.commit()
    return product


async def _make_template(session) -> ImportTemplate:
    template = ImportTemplate(
        code="test_template",
        name="Test Template",
        is_active=True,
    )
    session.add(template)
    await session.commit()
    return template


async def _make_profile_with_rules(session, template_id: int | None = None) -> int:
    profile = RouteRuleProfile(
        code="test_profile",
        name="Test Profile",
        is_active=True,
        priority=1000,
        import_template_id=template_id,
        route_sections=["WH", "ANOD", "PACK", "FG_WH"],
    )
    session.add(profile)
    await session.flush()

    # Core sections rule
    session.add(RouteSelectionRule(
        code="core",
        name="Core sections",
        profile_id=profile.id,
        priority=1000,
        phase="route_select",
        conditions=[],
        actions=[
            {"action": "require_section", "section_code": "WH"},
            {"action": "require_section", "section_code": "ANOD"},
            {"action": "require_section", "section_code": "PACK"},
            {"action": "require_section", "section_code": "FG_WH"},
        ],
    ))

    # Pack type rule
    session.add(RouteSelectionRule(
        code="pack_type",
        name="Pack type",
        profile_id=profile.id,
        priority=100,
        phase="resolve_operations",
        conditions=[
            {"source": "payload", "field_path": "output_kind", "operator": "not_empty", "value": None},
        ],
        actions=[
            {
                "action": "set_operation_by_mapping",
                "section_code": "ANOD",
                "group_code": "ANOD",
                "lookup_field": "color",
                "mapping": [
                    {"keyword": "черн", "operation_code": "ANOD_05"},
                    {"keyword": "серебр", "operation_code": "ANOD_01"},
                ],
            },
            {
                "action": "set_operation_by_mapping",
                "section_code": "PACK",
                "group_code": "PACK",
                "lookup_field": "output_kind",
                "mapping": [
                    {"keyword": "ГП", "operation_code": "PACK_STRETCH"},
                    {"keyword": "П/Ф", "operation_code": "PACK_SPUNBOND"},
                ],
            },
        ],
    ))

    await session.commit()
    return profile.id


class ParsedRow:
    """Minimal mock for ParsedPlanRow."""
    def __init__(self, sku: str, name: str, quantity: Decimal, payload: dict):
        self.source_sku = sku
        self.source_name = name
        self.quantity = quantity
        self.payload = payload
        self.source_row_number = 1
        self.source_row_numbers = [1]
        self.source_ref = None
        self.source_fingerprint = f"{sku}_{name}_{quantity}"
        self.source_row_hash = f"hash_{sku}"
        self.warnings = []
        self.errors = []


@pytest.mark.asyncio
async def test_dynamic_route_creates_real_production_route(session) -> None:
    """Verify that dynamic route import creates a real ProductionRoute with steps."""
    await _seed_sections(session)
    product = await _make_product_with_techcard(session, sku="FG-ROUTE-TEST")
    template = await _make_template(session)
    profile_id = await _make_profile_with_rules(session, template_id=template.id)

    parsed_rows = [
        ParsedRow(
            sku=product.sku,
            name=product.name,
            quantity=Decimal("100"),
            payload={
                "color": "черный",
                "output_kind": "ГП",
                "operation": "",
            },
        ),
    ]

    products_by_sku = {product.sku.lower(): product}

    # change_set_id=1 simulates real import (not preview)
    items, diagnostics = await _make_change_items(
        session,
        change_set_id=1,
        parsed_rows=parsed_rows,
        products_by_sku=products_by_sku,
        mode=None,
        existing_positions=[],
        rule_profile_id=profile_id,
        template_id=template.id,
    )

    assert len(items) == 1
    item = items[0]
    # Status may be warning due to hanger_quantity not set
    assert item.status in (PlanChangeItemStatus.pending, PlanChangeItemStatus.warning)

    # Verify route_id is set
    route_id = item.after_data.get("route_id")
    assert route_id is not None, "route_id should be set for dynamic route"

    # Verify the route exists in DB
    route = await session.get(ProductionRoute, route_id)
    assert route is not None
    assert route.import_template_id == template.id
    assert route.is_active is True

    # Verify route stages were created
    stages_result = await session.execute(
        select(RouteStage).where(RouteStage.route_id == route_id).order_by(RouteStage.sequence)
    )
    stages = stages_result.scalars().all()
    assert len(stages) > 0, "Route should have stages"

    # Verify route_assigned_at is set
    assert item.after_data.get("route_assigned_at") is not None
    assert item.after_data.get("route_source") == "dynamic_build"
    assert item.after_data.get("route_match_quality") == PlanPositionRouteMatchQuality.exact.value


@pytest.mark.asyncio
async def test_dynamic_route_reuses_same_route_within_import(session) -> None:
    """Verify that identical routes are reused within same import."""
    await _seed_sections(session)
    product = await _make_product_with_techcard(session, sku="FG-REUSE-TEST")
    template = await _make_template(session)
    profile_id = await _make_profile_with_rules(session, template_id=template.id)

    # Two identical rows should produce same route
    parsed_rows = [
        ParsedRow(
            sku=product.sku,
            name=product.name,
            quantity=Decimal("100"),
            payload={"color": "черный", "output_kind": "ГП", "operation": ""},
        ),
        ParsedRow(
            sku=product.sku,
            name=product.name,
            quantity=Decimal("200"),
            payload={"color": "черный", "output_kind": "ГП", "operation": ""},
        ),
    ]

    products_by_sku = {product.sku.lower(): product}

    items, diagnostics = await _make_change_items(
        session,
        change_set_id=2,
        parsed_rows=parsed_rows,
        products_by_sku=products_by_sku,
        mode=None,
        existing_positions=[],
        rule_profile_id=profile_id,
        template_id=template.id,
    )

    assert len(items) == 2

    route_id_1 = items[0].after_data.get("route_id")
    route_id_2 = items[1].after_data.get("route_id")

    assert route_id_1 is not None
    assert route_id_2 is not None
    assert route_id_1 == route_id_2, "Identical routes should be reused (same route_id)"

    # Only one route should exist in DB
    routes_result = await session.execute(select(ProductionRoute))
    routes = routes_result.scalars().all()
    assert len(routes) == 1, "Only one route should be created for identical signatures"


@pytest.mark.asyncio
async def test_different_routes_created_for_different_signatures(session) -> None:
    """Verify that different route signatures create separate ProductionRoute entities."""
    await _seed_sections(session)
    product = await _make_product_with_techcard(session, sku="FG-DIFF-TEST")
    template = await _make_template(session)
    profile_id = await _make_profile_with_rules(session, template_id=template.id)

    parsed_rows = [
        ParsedRow(
            sku=product.sku,
            name=product.name,
            quantity=Decimal("100"),
            payload={"color": "черный", "output_kind": "ГП", "operation": ""},
        ),
        ParsedRow(
            sku=product.sku,
            name=product.name,
            quantity=Decimal("150"),
            payload={"color": "серебро", "output_kind": "П/Ф", "operation": ""},
        ),
    ]

    products_by_sku = {product.sku.lower(): product}

    items, diagnostics = await _make_change_items(
        session,
        change_set_id=3,
        parsed_rows=parsed_rows,
        products_by_sku=products_by_sku,
        mode=None,
        existing_positions=[],
        rule_profile_id=profile_id,
        template_id=template.id,
    )

    assert len(items) == 2

    route_id_1 = items[0].after_data.get("route_id")
    route_id_2 = items[1].after_data.get("route_id")

    assert route_id_1 is not None
    assert route_id_2 is not None
    assert route_id_1 != route_id_2, "Different signatures should create different routes"

    # Two routes should exist in DB
    routes_result = await session.execute(select(ProductionRoute))
    routes = routes_result.scalars().all()
    assert len(routes) == 2


@pytest.mark.asyncio
async def test_preview_does_not_create_routes(session) -> None:
    """Verify that preview (change_set_id=0) does not persist routes to DB."""
    await _seed_sections(session)
    product = await _make_product_with_techcard(session, sku="FG-PREVIEW-TEST")
    template = await _make_template(session)
    profile_id = await _make_profile_with_rules(session, template_id=template.id)

    parsed_rows = [
        ParsedRow(
            sku=product.sku,
            name=product.name,
            quantity=Decimal("50"),
            payload={"color": "черный", "output_kind": "ГП", "operation": ""},
        ),
    ]

    products_by_sku = {product.sku.lower(): product}

    # change_set_id=0 means preview
    items, diagnostics = await _make_change_items(
        session,
        change_set_id=0,
        parsed_rows=parsed_rows,
        products_by_sku=products_by_sku,
        mode=None,
        existing_positions=[],
        rule_profile_id=profile_id,
        template_id=template.id,
    )

    assert len(items) == 1
    item = items[0]

    # Preview should NOT have route_id (no DB persistence)
    assert item.after_data.get("route_id") is None

    # But route_name should be set for display
    assert item.after_data.get("route_name") is not None
    assert item.after_data.get("route_source") == "dynamic_build"

    # No routes should exist in DB
    routes_result = await session.execute(select(ProductionRoute))
    routes = routes_result.scalars().all()
    assert len(routes) == 0, "Preview should not create routes in DB"
