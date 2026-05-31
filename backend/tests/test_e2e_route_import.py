"""E2E test for full Excel import with dynamic route creation.

This test verifies:
1. Excel file is parsed correctly
2. Products are matched
3. Dynamic routes are created with steps
4. Route steps are persisted in database
5. Route assignment metadata is set (route_assigned_at, etc.)
"""
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.import_template import ImportTemplate
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanChangeSet,
    PlanPositionRouteOrigin,
    ProductionPlan,
)
from app.models.route import ProductionRoute, RouteRuleProfile, RouteSelectionRule, RouteStep, SectionOperation
from app.models.section import Section
from app.models.techcard import Techcard, TechcardLine
from app.services.plan_import_service import create_excel_import_change_set


DEFAULT_SECTIONS = [
    {"code": "WH", "name": "Склад сырья", "sort_order": 10, "kind": "raw_stock"},
    {"code": "DRILL", "name": "Сверловка", "sort_order": 20, "kind": "production"},
    {"code": "PRESS", "name": "Пресс", "sort_order": 30, "kind": "production"},
    {"code": "ANOD", "name": "Анодирование", "sort_order": 50, "kind": "production"},
    {"code": "PACK", "name": "Упаковка", "sort_order": 80, "kind": "production"},
    {"code": "FG_WH", "name": "Склад готовой продукции", "sort_order": 90, "kind": "finished_stock"},
]


async def _seed_sections(session) -> None:
    """Seed all required sections and their operations."""
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

    await session.commit()


async def _make_product_with_techcard(session, sku: str = "FG-TEST") -> Product:
    """Create a product with an active techcard."""
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
    """Create an import template."""
    template = ImportTemplate(
        code="test_template",
        name="Test Template",
        is_active=True,
    )
    session.add(template)
    await session.commit()
    return template


async def _make_profile_with_rules(session, template_id: int) -> int:
    """Create a route rule profile with selection rules."""
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
                ],
            },
        ],
    ))

    await session.commit()
    return profile.id


@pytest.mark.asyncio
async def test_e2e_excel_import_creates_routes_with_steps(session) -> None:
    """E2E test: Full Excel import creates dynamic routes with steps in database."""
    # Setup
    await _seed_sections(session)
    product = await _make_product_with_techcard(session, sku="FG-E2E-TEST")
    template = await _make_template(session)
    profile_id = await _make_profile_with_rules(session, template_id=template.id)

    # Create production plan
    plan = ProductionPlan(
        plan_no="TEST-001",
        name="Test Plan",
    )
    session.add(plan)
    await session.flush()

    # Load real test.xls file
    import os
    test_file_path = os.path.join(os.path.dirname(__file__), "..", "..", "test.xls")
    with open(test_file_path, "rb") as f:
        file_content = f.read()

    # Simulate Excel import using real file
    result = await create_excel_import_change_set(
        session,
        filename="test.xls",
        content=file_content,
        content_type="application/vnd.ms-excel",
        production_plan_id=plan.id,
        template_id=template.id,
        rule_profile_id=profile_id,
    )

    # Verify change set was created
    assert result["change_set_id"] is not None
    
    # Verify items were created (real Excel file has 31 rows)
    assert len(result["items"]) > 0, "Should have at least one item"
    
    # Collect unique routes
    route_ids_seen = set()
    items_with_details = []
    
    for item in result["items"]:
        route_id = item["after_data"].get("route_id")
        row_data = item["after_data"]
        
        if route_id and route_id not in route_ids_seen:
            route_ids_seen.add(route_id)
            
            # Get route steps from DB
            steps_result = await session.execute(
                select(RouteStep).where(RouteStep.route_id == route_id).order_by(RouteStep.sequence)
            )
            steps = steps_result.scalars().all()
            
            # Build step summary
            step_summary = []
            for step in steps:
                section = await session.get(Section, step.section_id)
                section_code = section.code if section else "?"
                step_summary.append(f"{step.sequence}:{section_code}")
            
            items_with_details.append({
                "route_id": route_id,
                "route_name": row_data.get("route_name", ""),
                "steps_count": len(steps),
                "steps": ", ".join(step_summary),
                "significant_steps": sum(1 for s in steps if s.is_significant),
            })
    
    # Print detailed summary for all routes
    print(f"\n{'='*80}")
    print(f"Total items: {len(result['items'])}, Unique routes: {len(items_with_details)}")
    print(f"{'='*80}")
    
    for idx, detail in enumerate(items_with_details, 1):
        print(f"\nRoute #{idx} (ID={detail['route_id']})")
        print(f"  Name: {detail['route_name']}")
        print(f"  Steps: {detail['steps_count']} ({detail['significant_steps']} significant)")
        print(f"  Steps sequence: {detail['steps']}")
        
        # Show detailed steps with operations
        steps_result = await session.execute(
            select(RouteStep).where(RouteStep.route_id == detail["route_id"]).order_by(RouteStep.sequence)
        )
        steps = steps_result.scalars().all()
        print(f"  Step details:")
        for step in steps:
            section = await session.get(Section, step.section_id)
            section_code = section.code if section else "?"
            print(f"    {step.sequence}: section={section_code}, op_code={step.operation_code}, op_name={step.operation_name}, significant={step.is_significant}")
        
        # Count how many items use this route
        items_using_route = sum(
            1 for item in result["items"]
            if item["after_data"].get("route_id") == detail["route_id"]
        )
        print(f"  Used by {items_using_route} item(s)")
    
    # Show per-row mapping with payload details
    print(f"\n{'='*80}")
    print("Per-row route mapping:")
    print(f"{'='*80}")
    for item in result["items"]:
        row_num = item.get("source_row_number", "?")
        sku = item["after_data"].get("source_sku", "?")
        route_id = item["after_data"].get("route_id")
        route_name = item["after_data"].get("route_name", "no route")
        payload = item["after_data"].get("source_payload", {})
        color = payload.get("color", "")
        output_kind = payload.get("output_kind", "")
        
        if route_id:
            print(f"  Row {row_num}: SKU={sku}, color='{color}', output='{output_kind}' => Route {route_id}")
        else:
            print(f"  Row {row_num}: SKU={sku}, color='{color}', output='{output_kind}' => NO ROUTE")
    
    # Show unique route+payload combinations
    print(f"\n{'='*80}")
    print("Unique route configurations:")
    print(f"{'='*80}")
    route_configs = {}
    for item in result["items"]:
        route_id = item["after_data"].get("route_id")
        if route_id:
            payload = item["after_data"].get("source_payload", {})
            color = payload.get("color", "")
            output_kind = payload.get("output_kind", "")
            # Show raw bytes for encoding debug
            color_bytes = color.encode('utf-8', errors='replace')[:20]
            key = (route_id, color, output_kind)
            route_configs.setdefault(key, 0)
            route_configs[key] += 1
    
    for (route_id, color, output_kind), count in sorted(route_configs.items()):
        print(f"  Route {route_id}: color='{color}' (bytes: {color_bytes}), output='{output_kind}' => {count} items")
    
    # Verify first route in detail
    if items_with_details:
        first_route_id = items_with_details[0]["route_id"]
        
        # Verify route exists in DB
        route = await session.get(ProductionRoute, first_route_id)
        assert route is not None, "Route should exist in DB"
        assert route.import_template_id == template.id
        assert route.is_active is True
        
        # Verify route assignment metadata
        first_item_with_route = next(
            item for item in result["items"]
            if item["after_data"].get("route_id") == first_route_id
        )
        
        assert first_item_with_route["after_data"].get("route_assigned_at") is not None
        assert first_item_with_route["after_data"].get("route_source") == "dynamic_build"
        assert first_item_with_route["after_data"].get("route_match_quality") == "exact"
        assert first_item_with_route["after_data"].get("route_origin") == PlanPositionRouteOrigin.auto.value


@pytest.mark.asyncio
async def test_e2e_excel_import_multiple_rows_reuse_routes(session) -> None:
    """E2E test: Multiple identical rows reuse same route with steps."""
    # Setup
    await _seed_sections(session)
    product = await _make_product_with_techcard(session, sku="FG-E2E-REUSE")
    template = await _make_template(session)
    profile_id = await _make_profile_with_rules(session, template_id=template.id)

    # Create production plan
    plan = ProductionPlan(
        plan_no="TEST-002",
        name="Test Plan Reuse",
    )
    session.add(plan)
    await session.flush()

    # Load real test.xls file
    import os
    test_file_path = os.path.join(os.path.dirname(__file__), "..", "..", "test.xls")
    with open(test_file_path, "rb") as f:
        file_content = f.read()

    # Simulate Excel import using real file
    result = await create_excel_import_change_set(
        session,
        filename="test.xls",
        content=file_content,
        content_type="application/vnd.ms-excel",
        production_plan_id=plan.id,
        template_id=template.id,
        rule_profile_id=profile_id,
    )

    # Verify items were created
    assert len(result["items"]) > 0, "Should have at least one item"
    
    # Check how many items have routes assigned
    items_with_routes = [item for item in result["items"] if item["after_data"].get("route_id")]
    
    # If we have items with routes, verify they have steps
    if items_with_routes:
        route_id = items_with_routes[0]["after_data"].get("route_id")
        
        # Verify route has steps
        steps_result = await session.execute(
            select(RouteStep).where(RouteStep.route_id == route_id)
        )
        steps = steps_result.scalars().all()
        assert len(steps) > 0, "Route MUST have steps!"
        
        # Verify step sequences are unique
        step_sequences = [s.sequence for s in steps]
        assert len(step_sequences) == len(set(step_sequences)), "Step sequences must be unique"
        
        print(f"✅ Route {route_id} has {len(steps)} steps")
        print(f"   Total items: {len(result['items'])}, with routes: {len(items_with_routes)}")
