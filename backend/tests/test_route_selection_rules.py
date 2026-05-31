"""Comprehensive tests for route selection rules system.

Covers:
- product_skip_shot / product_with_shot rules (SHOT section exclusion)
- set_operation_by_mapping resolution (press_types, anod_colors, pack_types)
- Phase ordering and priority handling
- Condition evaluation for product, payload, and excel sources
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.product import Product, ProductType
from app.models.route import RouteRuleProfile, RouteSelectionRule
from app.models.section import Section
from app.services.route_selection import select_route_for_payload

from tests.test_routes_seed import DEFAULT_SECTIONS, _seed_default_sections


DEFAULT_SECTIONS_CODES = {s["code"] for s in DEFAULT_SECTIONS}


async def _seed_profile_and_rules(session) -> int:
    """Seed sections, route rule profile, and selection rules via the seed endpoint pattern."""
    await _seed_default_sections(session)

    # Create profile
    profile = RouteRuleProfile(
        code="packaging_map_rp",
        name="Упаковочная карта РП",
        is_active=True,
        priority=1000,
    )
    session.add(profile)
    await session.flush()

    # Build section code->id map
    sections = (await session.execute(select(Section))).scalars().all()
    section_by_code = {s.code: s for s in sections}

    def _section_id(code: str) -> int:
        return section_by_code[code].id

    # Seed selection rules matching selection_rules.py
    rules_data = [
        {
            "code": "core_sections",
            "name": "Базовые участки маршрута",
            "priority": 1000,
            "phase": "route_select",
            "conditions": [],
            "actions": [
                {"action": "require_section", "section_id": _section_id("WH")},
                {"action": "require_section", "section_id": _section_id("ANOD")},
                {"action": "require_section", "section_id": _section_id("FG_WH")},
            ],
        },
        {
            "code": "drill",
            "name": "Операция сверловки",
            "priority": 900,
            "phase": "route_select",
            "conditions": [
                {"source": "payload", "field_path": "operation", "operator": "contains", "value": "сверл", "case_sensitive": False},
            ],
            "actions": [
                {"action": "require_section", "section_id": _section_id("DRILL")},
                {"action": "exclude_section", "section_id": _section_id("PRESS")},
            ],
        },
        {
            "code": "press_types",
            "name": "Пресс: определение типа",
            "priority": 200,
            "phase": "resolve_operations",
            "conditions": [
                {"source": "payload", "field_path": "operation", "operator": "not_empty", "value": None},
            ],
            "actions": [
                {"action": "require_section", "section_code": "PRESS"},
                {"action": "exclude_section", "section_code": "DRILL"},
                {
                    "action": "set_operation_by_mapping",
                    "section_code": "PRESS",
                    "group_code": "PRESS",
                    "lookup_field": "operation",
                    "mapping": [
                        {"keyword": "окн", "operation_code": "PRESS_WINDOW"},
                        {"keyword": "греб", "operation_code": "PRESS_COMB"},
                    ],
                },
            ],
        },
        {
            "code": "empty_primary",
            "name": "Без первичной операции",
            "priority": 800,
            "phase": "route_select",
            "conditions": [
                {"source": "payload", "field_path": "operation", "operator": "empty", "value": None},
            ],
            "actions": [
                {"action": "exclude_section", "section_id": _section_id("DRILL")},
                {"action": "exclude_section", "section_id": _section_id("PRESS")},
            ],
        },
        {
            "code": "pack_stretch_branch",
            "name": "Стрейч упаковка — полный маршрут (ГП)",
            "priority": 700,
            "phase": "route_select",
            "conditions": [
                {"source": "payload", "field_path": "output_kind", "operator": "contains", "value": "ГП"},
            ],
            "actions": [
                {"action": "require_section", "section_id": _section_id("WIP_WH")},
                {"action": "require_section", "section_id": _section_id("SAW")},
                {"action": "require_section", "section_id": _section_id("PACK")},
            ],
        },
        {
            "code": "pack_spunbond_branch",
            "name": "Спанбонд упаковка — без промежуточных этапов (П/Ф)",
            "priority": 700,
            "phase": "route_select",
            "conditions": [
                {"source": "payload", "field_path": "output_kind", "operator": "contains", "value": "П/Ф"},
            ],
            "actions": [
                {"action": "exclude_section", "section_id": _section_id("WIP_WH")},
                {"action": "exclude_section", "section_id": _section_id("SAW")},
                {"action": "exclude_section", "section_id": _section_id("PACK")},
            ],
        },
        {
            "code": "product_skip_shot",
            "name": "Продукт без дробеструя",
            "priority": 600,
            "phase": "route_select",
            "conditions": [
                {"source": "product", "field_path": "skip_shot_blast", "operator": "equals", "value": True},
            ],
            "actions": [
                {"action": "exclude_section", "section_id": _section_id("SHOT")},
            ],
        },
        {
            "code": "product_with_shot",
            "name": "Продукт с дробеструем",
            "priority": 590,
            "phase": "route_select",
            "conditions": [
                {"source": "product", "field_path": "skip_shot_blast", "operator": "not_equals", "value": True},
            ],
            "actions": [
                {"action": "require_section", "section_id": _section_id("SHOT")},
            ],
        },
        {
            "code": "anod_colors",
            "name": "Анод: определение цвета",
            "priority": 100,
            "phase": "resolve_operations",
            "conditions": [
                {"source": "payload", "field_path": "color", "operator": "not_empty", "value": None},
            ],
            "actions": [
                {
                    "action": "set_operation_by_mapping",
                    "section_code": "ANOD",
                    "group_code": "ANOD",
                    "lookup_field": "color",
                    "mapping": [
                        {"keyword": "серебр", "operation_code": "ANOD_01"},
                        {"keyword": "золот", "operation_code": "ANOD_02"},
                        {"keyword": "бронз", "operation_code": "ANOD_03"},
                        {"keyword": "чёрн", "operation_code": "ANOD_05"},
                        {"keyword": "черн", "operation_code": "ANOD_05"},
                        {"keyword": "шампань", "operation_code": "ANOD_06"},
                        {"keyword": "мед", "operation_code": "ANOD_07"},
                        {"keyword": "титан", "operation_code": "ANOD_08"},
                    ],
                },
            ],
        },
        {
            "code": "pack_types",
            "name": "Упаковка: определение типа",
            "priority": 100,
            "phase": "resolve_operations",
            "conditions": [
                {"source": "payload", "field_path": "output_kind", "operator": "not_empty", "value": None},
            ],
            "actions": [
                {
                    "action": "set_operation_by_mapping",
                    "section_code": "ANOD",
                    "group_code": "PACK",
                    "lookup_field": "output_kind",
                    "mapping": [
                        {"keyword": "ГП", "operation_code": "PACK_STRETCH"},
                        {"keyword": "П/Ф", "operation_code": "PACK_SPUNBOND"},
                    ],
                },
            ],
        },
    ]

    for rd in rules_data:
        rule = RouteSelectionRule(
            code=rd["code"],
            name=rd["name"],
            profile_id=profile.id,
            priority=rd["priority"],
            is_active=True,
            phase=rd["phase"],
            conditions=rd["conditions"],
            actions=rd["actions"],
        )
        session.add(rule)

    await session.commit()
    return profile.id


@pytest.mark.asyncio
async def test_product_skip_shot_excludes_shot_section(client, session) -> None:
    """When product has skip_shot_blast=True, SHOT section must be excluded."""
    profile_id = await _seed_profile_and_rules(session)

    product = Product(
        sku="TEST-SKIP-SHOT-001",
        name="Тест без дробеструя",
        type=ProductType.finished_good,
        unit="pcs",
        skip_shot_blast=True,
    )
    session.add(product)
    await session.flush()

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "color": "серебро", "raw_columns": {"operation": "", "output_kind": "ГП"}},
        product=product,
        profile_id=profile_id,
    )

    excluded_codes = {s["code"] for s in result.excluded_sections}
    assert "SHOT" in excluded_codes, f"SHOT should be excluded when skip_shot_blast=True, got: {excluded_codes}"

    # SHOT should NOT be in required sections
    required_codes = {s["code"] for s in result.required_sections}
    assert "SHOT" not in required_codes, f"SHOT should NOT be required when skip_shot_blast=True, got: {required_codes}"


@pytest.mark.asyncio
async def test_product_with_shot_requires_shot_section(client, session) -> None:
    """When product has skip_shot_blast=False, SHOT section must be required."""
    profile_id = await _seed_profile_and_rules(session)

    product = Product(
        sku="TEST-WITH-SHOT-001",
        name="Тест с дробеструем",
        type=ProductType.finished_good,
        unit="pcs",
        skip_shot_blast=False,
    )
    session.add(product)
    await session.flush()

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "color": "серебро", "raw_columns": {"operation": "", "output_kind": "ГП"}},
        product=product,
        profile_id=profile_id,
    )

    required_codes = {s["code"] for s in result.required_sections}
    assert "SHOT" in required_codes, f"SHOT should be required when skip_shot_blast=False, got: {required_codes}"

    # SHOT should NOT be in excluded sections
    excluded_codes = {s["code"] for s in result.excluded_sections}
    assert "SHOT" not in excluded_codes, f"SHOT should NOT be excluded when skip_shot_blast=False, got: {excluded_codes}"


@pytest.mark.asyncio
async def test_product_skip_shot_default_false_requires_shot(client, session) -> None:
    """When product has skip_shot_blast=None (default), SHOT should be required (not_equals True fires)."""
    profile_id = await _seed_profile_and_rules(session)

    product = Product(
        sku="TEST-DEFAULT-SHOT-001",
        name="Тест без флага",
        type=ProductType.finished_good,
        unit="pcs",
        # skip_shot_blast not set — defaults to None/False
    )
    session.add(product)
    await session.flush()

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "raw_columns": {"operation": "", "output_kind": "ГП"}},
        product=product,
        profile_id=profile_id,
    )

    required_codes = {s["code"] for s in result.required_sections}
    assert "SHOT" in required_codes, f"SHOT should be required by default, got: {required_codes}"


@pytest.mark.asyncio
async def test_press_types_resolve_window_operation(client, session) -> None:
    """set_operation_by_mapping for press_types should resolve PRESS_WINDOW when operation contains 'окн'."""
    profile_id = await _seed_profile_and_rules(session)

    result = await select_route_for_payload(
        session,
        {"operation": "пробивка окна", "output_kind": "ГП", "raw_columns": {"operation": "пробивка окна", "output_kind": "ГП"}},
        profile_id=profile_id,
    )

    assert result.resolved_operations.get(("PRESS", "PRESS")) == "PRESS_WINDOW", (
        f"Expected PRESS_WINDOW, got: {result.resolved_operations}"
    )


@pytest.mark.asyncio
async def test_press_types_resolve_comb_operation(client, session) -> None:
    """set_operation_by_mapping for press_types should resolve PRESS_COMB when operation contains 'греб'."""
    profile_id = await _seed_profile_and_rules(session)

    result = await select_route_for_payload(
        session,
        {"operation": "гребёнка профиль", "output_kind": "ГП", "raw_columns": {"operation": "гребёнка профиль", "output_kind": "ГП"}},
        profile_id=profile_id,
    )

    assert result.resolved_operations.get(("PRESS", "PRESS")) == "PRESS_COMB", (
        f"Expected PRESS_COMB, got: {result.resolved_operations}"
    )


@pytest.mark.asyncio
async def test_press_types_no_match_when_empty_operation(client, session) -> None:
    """When operation is empty, press_types condition should not match — no PRESS operation resolved."""
    profile_id = await _seed_profile_and_rules(session)

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "raw_columns": {"operation": "", "output_kind": "ГП"}},
        profile_id=profile_id,
    )

    assert ("PRESS", "PRESS") not in result.resolved_operations, (
        f"PRESS should not be resolved when operation is empty, got: {result.resolved_operations}"
    )


@pytest.mark.asyncio
async def test_anod_colors_resolve_silver(client, session) -> None:
    """anod_colors rule should resolve ANOD_01 when color contains 'серебр'."""
    profile_id = await _seed_profile_and_rules(session)

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "color": "серебро", "raw_columns": {"operation": "", "color": "серебро"}},
        profile_id=profile_id,
    )

    assert result.resolved_operations.get(("ANOD", "ANOD")) == "ANOD_01", (
        f"Expected ANOD_01 for 'серебро', got: {result.resolved_operations}"
    )


@pytest.mark.asyncio
async def test_anod_colors_resolve_gold(client, session) -> None:
    """anod_colors rule should resolve ANOD_02 when color contains 'золот'."""
    profile_id = await _seed_profile_and_rules(session)

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "color": "золотистый", "raw_columns": {"operation": "", "color": "золотистый"}},
        profile_id=profile_id,
    )

    assert result.resolved_operations.get(("ANOD", "ANOD")) == "ANOD_02", (
        f"Expected ANOD_02 for 'золотистый', got: {result.resolved_operations}"
    )


@pytest.mark.asyncio
async def test_anod_colors_resolve_black_cyrillic(client, session) -> None:
    """anod_colors should match 'чёрн' (with ё) for ANOD_05."""
    profile_id = await _seed_profile_and_rules(session)

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "color": "чёрный", "raw_columns": {"operation": "", "color": "чёрный"}},
        profile_id=profile_id,
    )

    assert result.resolved_operations.get(("ANOD", "ANOD")) == "ANOD_05", (
        f"Expected ANOD_05 for 'чёрный', got: {result.resolved_operations}"
    )


@pytest.mark.asyncio
async def test_anod_colors_resolve_black_without_yo(client, session) -> None:
    """anod_colors should also match 'черн' (without ё) for ANOD_05."""
    profile_id = await _seed_profile_and_rules(session)

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "color": "черный матовый", "raw_columns": {"operation": "", "color": "черный матовый"}},
        profile_id=profile_id,
    )

    assert result.resolved_operations.get(("ANOD", "ANOD")) == "ANOD_05", (
        f"Expected ANOD_05 for 'черный', got: {result.resolved_operations}"
    )


@pytest.mark.asyncio
async def test_anod_colors_resolve_titan(client, session) -> None:
    """anod_colors should resolve ANOD_08 when color contains 'титан'."""
    profile_id = await _seed_profile_and_rules(session)

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "color": "титан", "raw_columns": {"operation": "", "color": "титан"}},
        profile_id=profile_id,
    )

    assert result.resolved_operations.get(("ANOD", "ANOD")) == "ANOD_08", (
        f"Expected ANOD_08 for 'титан', got: {result.resolved_operations}"
    )


@pytest.mark.asyncio
async def test_anod_colors_no_match_when_empty(client, session) -> None:
    """When color is empty, anod_colors condition should not match."""
    profile_id = await _seed_profile_and_rules(session)

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "raw_columns": {"operation": "", "output_kind": "ГП"}},
        profile_id=profile_id,
    )

    assert ("ANOD", "ANOD") not in result.resolved_operations, (
        f"ANOD should not be resolved when color is empty, got: {result.resolved_operations}"
    )


@pytest.mark.asyncio
async def test_pack_types_resolve_stretch_for_gp(client, session) -> None:
    """pack_types should resolve PACK_STRETCH when output_kind contains 'ГП'."""
    profile_id = await _seed_profile_and_rules(session)

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "raw_columns": {"operation": "", "output_kind": "ГП"}},
        profile_id=profile_id,
    )

    assert result.resolved_operations.get(("ANOD", "PACK")) == "PACK_STRETCH", (
        f"Expected PACK_STRETCH for ГП, got: {result.resolved_operations}"
    )


@pytest.mark.asyncio
async def test_pack_types_resolve_spunbond_for_pf(client, session) -> None:
    """pack_types should resolve PACK_SPUNBOND when output_kind contains 'П/Ф'."""
    profile_id = await _seed_profile_and_rules(session)

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "П/Ф", "raw_columns": {"operation": "", "output_kind": "П/Ф"}},
        profile_id=profile_id,
    )

    assert result.resolved_operations.get(("ANOD", "PACK")) == "PACK_SPUNBOND", (
        f"Expected PACK_SPUNBOND for П/Ф, got: {result.resolved_operations}"
    )


@pytest.mark.asyncio
async def test_multiple_operations_resolved_simultaneously(client, session) -> None:
    """When both color and output_kind are present, both ANOD and PACK operations should be resolved."""
    profile_id = await _seed_profile_and_rules(session)

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "color": "золото", "raw_columns": {"operation": "", "output_kind": "ГП", "color": "золото"}},
        profile_id=profile_id,
    )

    assert ("ANOD", "ANOD") in result.resolved_operations, f"ANOD operation should be resolved, got: {result.resolved_operations}"
    assert ("ANOD", "PACK") in result.resolved_operations, f"PACK operation should be resolved, got: {result.resolved_operations}"
    assert result.resolved_operations[("ANOD", "ANOD")] == "ANOD_02"
    assert result.resolved_operations[("ANOD", "PACK")] == "PACK_STRETCH"


@pytest.mark.asyncio
async def test_drill_rule_requires_drill_excludes_press(client, session) -> None:
    """When operation contains 'сверл', DRILL should be required and PRESS excluded."""
    profile_id = await _seed_profile_and_rules(session)

    result = await select_route_for_payload(
        session,
        {"operation": "сверловка", "output_kind": "ГП", "raw_columns": {"operation": "сверловка", "output_kind": "ГП"}},
        profile_id=profile_id,
    )

    required_codes = {s["code"] for s in result.required_sections}
    excluded_codes = {s["code"] for s in result.excluded_sections}

    assert "DRILL" in required_codes, f"DRILL should be required, got: {required_codes}"
    assert "PRESS" in excluded_codes, f"PRESS should be excluded, got: {excluded_codes}"


@pytest.mark.asyncio
async def test_empty_primary_excludes_drill_and_press(client, session) -> None:
    """When operation is empty, DRILL and PRESS should both be excluded."""
    profile_id = await _seed_profile_and_rules(session)

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "raw_columns": {"operation": "", "output_kind": "ГП"}},
        profile_id=profile_id,
    )

    excluded_codes = {s["code"] for s in result.excluded_sections}
    assert "DRILL" in excluded_codes, f"DRILL should be excluded when operation is empty, got: {excluded_codes}"
    assert "PRESS" in excluded_codes, f"PRESS should be excluded when operation is empty, got: {excluded_codes}"


@pytest.mark.asyncio
async def test_gp_route_requires_wip_wh_saw_pack(client, session) -> None:
    """When output_kind is 'ГП', WIP_WH, SAW, PACK should be required."""
    profile_id = await _seed_profile_and_rules(session)

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "raw_columns": {"operation": "", "output_kind": "ГП"}},
        profile_id=profile_id,
    )

    required_codes = {s["code"] for s in result.required_sections}
    assert "WIP_WH" in required_codes, f"WIP_WH should be required for ГП, got: {required_codes}"
    assert "SAW" in required_codes, f"SAW should be required for ГП, got: {required_codes}"
    assert "PACK" in required_codes, f"PACK should be required for ГП, got: {required_codes}"


@pytest.mark.asyncio
async def test_pf_route_excludes_wip_wh_saw_pack(client, session) -> None:
    """When output_kind is 'П/Ф', WIP_WH, SAW, PACK should be excluded."""
    profile_id = await _seed_profile_and_rules(session)

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "П/Ф", "raw_columns": {"operation": "", "output_kind": "П/Ф"}},
        profile_id=profile_id,
    )

    excluded_codes = {s["code"] for s in result.excluded_sections}
    assert "WIP_WH" in excluded_codes, f"WIP_WH should be excluded for П/Ф, got: {excluded_codes}"
    assert "SAW" in excluded_codes, f"SAW should be excluded for П/Ф, got: {excluded_codes}"
    assert "PACK" in excluded_codes, f"PACK should be excluded for П/Ф, got: {excluded_codes}"


@pytest.mark.asyncio
async def test_core_sections_always_required(client, session) -> None:
    """core_sections rule (priority 1000, no conditions) should always require WH, ANOD, FG_WH."""
    profile_id = await _seed_profile_and_rules(session)

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "raw_columns": {"operation": "", "output_kind": "ГП"}},
        profile_id=profile_id,
    )

    required_codes = {s["code"] for s in result.required_sections}
    assert "WH" in required_codes, f"WH should always be required, got: {required_codes}"
    assert "ANOD" in required_codes, f"ANOD should always be required, got: {required_codes}"
    assert "FG_WH" in required_codes, f"FG_WH should always be required, got: {required_codes}"


@pytest.mark.asyncio
async def test_matched_rule_ids_includes_all_phases(client, session) -> None:
    """matched_rule_ids should contain rules from all 3 phases that matched."""
    profile_id = await _seed_profile_and_rules(session)

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "color": "серебро", "raw_columns": {"operation": "", "output_kind": "ГП", "color": "серебро"}},
        profile_id=profile_id,
    )

    # Fetch rule codes by ID to verify which phases matched
    rule_ids = set(result.matched_rule_ids)
    assert len(rule_ids) > 0, "At least some rules should match"

    # core_sections (route_select, no conditions) should always match
    core_rule = await session.scalar(select(RouteSelectionRule).where(RouteSelectionRule.code == "core_sections"))
    assert core_rule.id in rule_ids, "core_sections rule should always match"

    # anod_colors (resolve_operations) should match when color is present
    anod_rule = await session.scalar(select(RouteSelectionRule).where(RouteSelectionRule.code == "anod_colors"))
    assert anod_rule.id in rule_ids, "anod_colors rule should match when color is present"

    # pack_types (resolve_operations) should match when output_kind is present
    pack_rule = await session.scalar(select(RouteSelectionRule).where(RouteSelectionRule.code == "pack_types"))
    assert pack_rule.id in rule_ids, "pack_types rule should match when output_kind is present"


@pytest.mark.asyncio
async def test_priority_ordering_within_route_select_phase(client, session) -> None:
    """Higher priority rules should be evaluated first within a phase.

    drill (900) > empty_primary (800) > pack_stretch/pack_spunbond (700) > product_skip_shot (600) > product_with_shot (590)
    When operation='сверловка', drill fires (excludes PRESS), empty_primary does NOT fire.
    """
    profile_id = await _seed_profile_and_rules(session)

    result = await select_route_for_payload(
        session,
        {"operation": "сверловка", "output_kind": "ГП", "raw_columns": {"operation": "сверловка", "output_kind": "ГП"}},
        profile_id=profile_id,
    )

    excluded_codes = {s["code"] for s in result.excluded_sections}
    required_codes = {s["code"] for s in result.required_sections}

    # drill rule fired — PRESS excluded, DRILL required
    assert "PRESS" in excluded_codes
    assert "DRILL" in required_codes


@pytest.mark.asyncio
async def test_skip_shot_combined_with_gp_route(client, session) -> None:
    """Integration test: product with skip_shot_blast=True + output_kind='ГП'.

    Expected: SHOT excluded, WIP_WH/SAW/PACK required, core sections required.
    """
    profile_id = await _seed_profile_and_rules(session)

    product = Product(
        sku="TEST-COMBO-001",
        name="Комбо тест",
        type=ProductType.finished_good,
        unit="pcs",
        skip_shot_blast=True,
    )
    session.add(product)
    await session.flush()

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "color": "титан", "raw_columns": {"operation": "", "output_kind": "ГП", "color": "титан"}},
        product=product,
        profile_id=profile_id,
    )

    excluded_codes = {s["code"] for s in result.excluded_sections}
    required_codes = {s["code"] for s in result.required_sections}

    assert "SHOT" in excluded_codes, f"SHOT should be excluded, got: {excluded_codes}"
    assert "WIP_WH" in required_codes, f"WIP_WH should be required for ГП, got: {required_codes}"
    assert "SAW" in required_codes, f"SAW should be required for ГП, got: {required_codes}"
    assert "PACK" in required_codes, f"PACK should be required for ГП, got: {required_codes}"
    assert "WH" in required_codes, f"WH should be required, got: {required_codes}"
    assert "ANOD" in required_codes, f"ANOD should be required, got: {required_codes}"

    # Operations should also be resolved
    assert result.resolved_operations.get(("ANOD", "ANOD")) == "ANOD_08", "Titanium color should resolve"
    assert result.resolved_operations.get(("ANOD", "PACK")) == "PACK_STRETCH", "ГП should resolve PACK_STRETCH"


@pytest.mark.asyncio
async def test_case_insensitive_keyword_matching(client, session) -> None:
    """set_operation_by_mapping should match keywords case-insensitively."""
    profile_id = await _seed_profile_and_rules(session)

    # Lowercase color
    result_lower = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "color": "серебро", "raw_columns": {"operation": "", "color": "серебро"}},
        profile_id=profile_id,
    )

    # Uppercase color
    result_upper = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "color": "СЕРЕБРО", "raw_columns": {"operation": "", "color": "СЕРЕБРО"}},
        profile_id=profile_id,
    )

    assert result_lower.resolved_operations.get(("ANOD", "ANOD")) == "ANOD_01"
    assert result_upper.resolved_operations.get(("ANOD", "ANOD")) == "ANOD_01", (
        f"Case-insensitive match failed, got: {result_upper.resolved_operations}"
    )


@pytest.mark.asyncio
async def test_no_product_uses_default_shot_behavior(client, session) -> None:
    """When no product is passed, skip_shot_blast defaults to None — product_with_shot rule fires (not_equals True)."""
    profile_id = await _seed_profile_and_rules(session)

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "ГП", "raw_columns": {"operation": "", "output_kind": "ГП"}},
        product=None,
        profile_id=profile_id,
    )

    required_codes = {s["code"] for s in result.required_sections}
    assert "SHOT" in required_codes, f"SHOT should be required when no product passed, got: {required_codes}"
