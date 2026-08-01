"""Acceptance test: multi-factory support (#21).

Verifies that the system works with a completely different seed configuration —
a factory WITHOUT anodizing and sawing sections. This proves the core is
factory-agnostic: deploying to another factory requires only a different seed
set, with zero code changes.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.product import Product, ProductType
from app.models.route import RouteRuleProfile, RouteSelectionRule, SectionOperation
from app.models.section import Section
from app.services.route_selection import select_route_for_payload
from app.services.route_builder import build_route_from_profile


# ─── Minimal factory seed: no ANODIZING, no SAWING ────────────────────────────

FACTORY_B_SECTIONS = [
    {"code": "RAW_STOCK", "name": "Склад сырья", "sort_order": 10, "type": "raw_stock"},
    {"code": "DRILLING", "name": "Сверловка", "sort_order": 20, "type": "production"},
    {"code": "PRESSING", "name": "Пресс", "sort_order": 30, "type": "production"},
    {"code": "PACKING", "name": "Упаковка", "sort_order": 40, "type": "production"},
    {"code": "FINISHED_STOCK", "name": "Склад ГП", "sort_order": 50, "type": "finished_stock"},
]

FACTORY_B_SECTION_OPS = {
    "RAW_STOCK": [("RAW_STOCK", "Выдача сырья", 10, "ISSUE_RAW", "Выдача сырья", False, "transport")],
    "DRILLING": [("DRILLING", "Сверловка", 10, "DRILL", "Сверловка", True, "production")],
    "PRESSING": [("PRESSING", "Пресс", 10, "PRESS_WINDOW", "Окно", True, "production")],
    "PACKING": [("PACKING", "Упаковка", 10, "PACK_BOX", "Коробка", True, "production")],
    "FINISHED_STOCK": [("FINISHED_STOCK", "Приёмка", 10, "RECEIVE_FG", "Приёмка ГП", False, "transport")],
}

FACTORY_B_ROUTE_SECTIONS = ["RAW_STOCK", "DRILLING", "PRESSING", "PACKING", "FINISHED_STOCK"]


async def _seed_factory_b(session) -> int:
    """Seed a minimal factory without anodizing/sawing. Returns profile.id."""
    sections_map: dict[str, Section] = {}
    for data in FACTORY_B_SECTIONS:
        section = Section(**data)
        session.add(section)
        await session.flush()
        sections_map[section.code] = section

    for section_code, ops in FACTORY_B_SECTION_OPS.items():
        section = sections_map[section_code]
        for group_code, group_name, sort_order, op_code, op_name, is_sig, op_type in ops:
            session.add(SectionOperation(
                section_id=section.id,
                operation_code=op_code,
                operation_name=op_name,
                is_significant=is_sig,
                group_code=group_code,
                group_name=group_name,
                sort_order=sort_order,
                operation_type=op_type,
            ))
    await session.flush()

    # Create route rule profile
    profile = RouteRuleProfile(
        code="factory_b_profile",
        name="Завод Б (без анодирования и пилы)",
        is_active=True,
        priority=100,
        route_sections=FACTORY_B_ROUTE_SECTIONS,
    )
    session.add(profile)
    await session.flush()

    # Minimal selection rules: drill operation → require DRILLING
    rules = [
        {
            "code": "drill_op",
            "name": "Сверловка",
            "priority": 500,
            "is_active": True,
            "phase": "route_select",
            "conditions": [
                {"source": "payload", "field_path": "operation", "operator": "contains", "value": "сверл"},
            ],
            "actions": [
                {"action": "require_section", "section_id": sections_map["DRILLING"].id},
            ],
        },
        {
            "code": "no_drill",
            "name": "Без сверловки — исключить",
            "priority": 490,
            "is_active": True,
            "phase": "route_select",
            "conditions": [
                {"source": "payload", "field_path": "operation", "operator": "empty", "value": None},
            ],
            "actions": [
                {"action": "exclude_section", "section_id": sections_map["DRILLING"].id},
            ],
        },
    ]
    for rd in rules:
        session.add(RouteSelectionRule(
            profile_id=profile.id,
            code=rd["code"],
            name=rd["name"],
            priority=rd["priority"],
            is_active=rd["is_active"],
            phase=rd["phase"],
            conditions=rd["conditions"],
            actions=rd["actions"],
        ))

    await session.commit()
    return profile.id


@pytest.mark.asyncio
async def test_factory_b_route_selection_no_anodizing_no_sawing(client, session) -> None:
    """Route selection on factory B never includes ANODIZING or SAWING."""
    profile_id = await _seed_factory_b(session)

    result = await select_route_for_payload(
        session,
        {"operation": "сверловка", "output_kind": "ГП", "raw_columns": {"operation": "сверловка"}},
        profile_id=profile_id,
    )

    required_codes = {s["code"] for s in result.required_sections}
    excluded_codes = {s["code"] for s in result.excluded_sections}

    # Drill rule fires
    assert "DRILLING" in required_codes

    # No anodizing or sawing anywhere (they don't exist in this factory)
    assert "ANODIZING" not in required_codes
    assert "SAWING" not in required_codes
    assert "ANODIZING" not in excluded_codes
    assert "SAWING" not in excluded_codes


@pytest.mark.asyncio
async def test_factory_b_route_builder_produces_valid_route(client, session) -> None:
    """Route builder produces a complete route with only factory B sections."""
    profile_id = await _seed_factory_b(session)
    profile = await session.get(RouteRuleProfile, profile_id)

    route = await build_route_from_profile(
        session,
        profile,
        source_payload={"operation": "сверловка", "output_kind": "ГП"},
    )

    assert route.error is None, f"Route build failed: {route.error}"
    assert route.route_sections

    # All sections must be from factory B
    allowed = set(FACTORY_B_ROUTE_SECTIONS)
    for code in route.route_sections:
        assert code in allowed, f"Unexpected section {code} in factory B route"

    # No anodizing or sawing
    assert "ANODIZING" not in route.route_sections
    assert "SAWING" not in route.route_sections


@pytest.mark.asyncio
async def test_factory_b_product_without_flags_works(client, session) -> None:
    """Products work normally on factory B without processing flags."""
    profile_id = await _seed_factory_b(session)

    product = Product(
        sku="FB-001",
        name="Завод Б продукт",
        type=ProductType.finished_good,
        unit="pcs",
        length_mm=3000.0,
        quantity_per_hanger=20,
    )
    session.add(product)
    await session.flush()
    await session.refresh(product, attribute_names=["processing_flags"])

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "raw_columns": {"operation": ""}},
        product=product,
        profile_id=profile_id,
    )

    # Should work without errors — no skip_shot_blast flag needed
    # DRILLING excluded because operation is empty
    excluded_codes = {s["code"] for s in result.excluded_sections}
    assert "DRILLING" in excluded_codes

    # No anodizing/sawing in any result
    required_codes = {s["code"] for s in result.required_sections}
    assert "ANODIZING" not in required_codes
    assert "SAWING" not in required_codes

    # Verify attributes JSONB works
    assert product.length_mm == 3000.0
    assert product.quantity_per_hanger == 20
    assert product.attributes["length_mm"] == 3000.0
