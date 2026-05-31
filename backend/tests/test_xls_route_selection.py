"""Test that verifies route selection for all rows in test.xls.

test.xls contains 33 data rows with various combinations of:
- colors: черный, серебро, золото, шампань, медь, титан
- operations: окно, гребенка, сверло, (empty)
- packaging: поф (ГП), смотка спанбондом (П/ф)
- output_kind: ГП, П/ф

Each row should produce a unique route signature combining:
- Required sections (WH, DRILL/PRESS, SHOT, ANOD, WIP_WH, SAW, PACK, FG_WH, etc.)
- Resolved operations (PRESS_WINDOW/PRESS_COMB, ANOD_01/02/..., PACK_STRETCH/PACK_SPUNBOND)
- Excluded sections based on conditions
"""
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.import_template import ImportTemplate
from app.models.product import Product, ProductType
from app.models.route import RouteRuleProfile, RouteSelectionRule
from app.models.section import Section
from app.models.techcard import Techcard, TechcardLine
from app.services.excel_import import parse_factory_plan_workbook
from app.services.route_selection import select_route_for_payload

from tests.test_routes_seed import _seed_default_sections


TEST_XLS_PATH = Path(__file__).resolve().parent.parent.parent / "test.xls"


def _load_test_rows() -> list[dict]:
    """Load and return parsed rows from test.xls."""
    raw_bytes = TEST_XLS_PATH.read_bytes()
    parsed = parse_factory_plan_workbook(raw_bytes, "test.xls")
    rows = []
    for prow in parsed.parsed_rows:
        rows.append({
            "source_row_numbers": prow.source_row_numbers,
            "source_sku": prow.source_sku,
            "source_name": prow.source_name,
            "quantity": prow.quantity,
            "payload": prow.payload,
        })
    return rows


async def _seed_full_environment(session) -> int:
    """Seed sections, profile, and all selection rules."""
    await _seed_default_sections(session)

    profile = RouteRuleProfile(
        code="packaging_map_rp",
        name="Упаковочная карта РП",
        is_active=True,
        priority=1000,
    )
    session.add(profile)
    await session.flush()

    sections = (await session.execute(select(Section))).scalars().all()
    section_by_code = {s.code: s for s in sections}

    def _section_id(code: str) -> int:
        return section_by_code[code].id

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


def _route_signature(result) -> dict:
    """Create a deterministic signature from a route selection result."""
    return {
        "required_sections": sorted([s["code"] for s in result.required_sections]),
        "excluded_sections": sorted([s["code"] for s in result.excluded_sections]),
        "resolved_operations": {f"{k[0]}/{k[1]}": v for k, v in sorted(result.resolved_operations.items())},
        "match_reason": result.route_match_reason,
    }


@pytest.mark.asyncio
async def test_test_xls_rows_produce_diverse_routes(client, session) -> None:
    """Parse test.xls and verify each row produces a route with correct sections and operations."""
    profile_id = await _seed_full_environment(session)

    rows = _load_test_rows()
    assert len(rows) >= 30, f"Expected at least 30 rows in test.xls, got {len(rows)}"

    results = []
    for row_data in rows:
        payload = row_data["payload"]
        result = await select_route_for_payload(
            session,
            payload,
            product=None,
            profile_id=profile_id,
        )
        sig = _route_signature(result)
        results.append({
            "rows": row_data["source_row_numbers"],
            "sku": row_data["source_sku"],
            "color": payload.get("color", ""),
            "operation": payload.get("operation", ""),
            "output_kind": payload.get("output_kind", ""),
            "signature": sig,
        })

    # Print summary for debugging
    for r in results:
        print(f"Rows {r['rows']}: SKU={r['sku']}, color={r['color']}, op={r['operation']}, kind={r['output_kind']}")
        print(f"  Required: {r['signature']['required_sections']}")
        print(f"  Excluded: {r['signature']['excluded_sections']}")
        print(f"  Operations: {r['signature']['resolved_operations']}")
        print()

    # Verify diversity — there should be multiple unique route signatures
    unique_sigs = set()
    for r in results:
        unique_sigs.add(json.dumps(r["signature"], sort_keys=True, ensure_ascii=False))
    assert len(unique_sigs) > 5, f"Expected at least 5 unique route signatures, got {len(unique_sigs)}"

    # Verify specific patterns:
    # 1. Rows with "окно" operation → PRESS section required, DRILL excluded, PRESS_WINDOW resolved
    window_rows = [r for r in results if r["operation"] and "окн" in r["operation"].lower()]
    assert len(window_rows) > 0, "Should have rows with 'окно' operation"
    for r in window_rows:
        assert "PRESS" in r["signature"]["required_sections"], f"PRESS required for окно row {r['rows']}"
        assert "DRILL" in r["signature"]["excluded_sections"], f"DRILL excluded for окно row {r['rows']}"
        assert r["signature"]["resolved_operations"].get("PRESS/PRESS") == "PRESS_WINDOW", (
            f"PRESS_WINDOW resolved for окно row {r['rows']}"
        )

    # 2. Rows with "гребенка" operation → PRESS_COMB resolved
    comb_rows = [r for r in results if r["operation"] and "греб" in r["operation"].lower()]
    assert len(comb_rows) > 0, "Should have rows with 'гребенка' operation"
    for r in comb_rows:
        assert r["signature"]["resolved_operations"].get("PRESS/PRESS") == "PRESS_COMB", (
            f"PRESS_COMB resolved for гребенка row {r['rows']}"
        )

    # 3. Rows with "сверло" operation → DRILL required, PRESS excluded
    drill_rows = [r for r in results if r["operation"] and "сверл" in r["operation"].lower()]
    assert len(drill_rows) > 0, "Should have rows with 'сверло' operation"
    for r in drill_rows:
        assert "DRILL" in r["signature"]["required_sections"], f"DRILL required for сверло row {r['rows']}"
        assert "PRESS" in r["signature"]["excluded_sections"], f"PRESS excluded for сверло row {r['rows']}"

    # 4. Rows with output_kind=ГП → WIP_WH, SAW, PACK required
    gp_rows = [r for r in results if "ГП" in r["output_kind"]]
    assert len(gp_rows) > 0, "Should have rows with output_kind=ГП"
    for r in gp_rows:
        assert "WIP_WH" in r["signature"]["required_sections"], f"WIP_WH required for ГП row {r['rows']}"
        assert "SAW" in r["signature"]["required_sections"], f"SAW required for ГП row {r['rows']}"
        assert "PACK" in r["signature"]["required_sections"], f"PACK required for ГП row {r['rows']}"
        assert r["signature"]["resolved_operations"].get("ANOD/PACK") == "PACK_STRETCH", (
            f"PACK_STRETCH resolved for ГП row {r['rows']}"
        )

    # 5. Rows with output_kind=П/Ф → WIP_WH, SAW, PACK excluded
    pf_rows = [r for r in results if "П/ф" in r["output_kind"] or "П/Ф" in r["output_kind"]]
    assert len(pf_rows) > 0, "Should have rows with output_kind=П/Ф"
    for r in pf_rows:
        assert "WIP_WH" in r["signature"]["excluded_sections"], f"WIP_WH excluded for П/Ф row {r['rows']}"
        assert "SAW" in r["signature"]["excluded_sections"], f"SAW excluded for П/Ф row {r['rows']}"
        assert "PACK" in r["signature"]["excluded_sections"], f"PACK excluded for П/Ф row {r['rows']}"
        assert r["signature"]["resolved_operations"].get("ANOD/PACK") == "PACK_SPUNBOND", (
            f"PACK_SPUNBOND resolved for П/Ф row {r['rows']}"
        )

    # 6. Rows with color=серебро → ANOD_01
    silver_rows = [r for r in results if "серебр" in r["color"].lower()]
    assert len(silver_rows) > 0, "Should have rows with color=серебро"
    for r in silver_rows:
        assert r["signature"]["resolved_operations"].get("ANOD/ANOD") == "ANOD_01", (
            f"ANOD_01 resolved for серебро row {r['rows']}"
        )

    # 7. Rows with color=черный → ANOD_05
    black_rows = [r for r in results if "черн" in r["color"].lower()]
    assert len(black_rows) > 0, "Should have rows with color=черный"
    for r in black_rows:
        assert r["signature"]["resolved_operations"].get("ANOD/ANOD") == "ANOD_05", (
            f"ANOD_05 resolved for черный row {r['rows']}"
        )

    # 8. Rows with color=золото → ANOD_02
    gold_rows = [r for r in results if "золот" in r["color"].lower()]
    assert len(gold_rows) > 0, "Should have rows with color=золото"
    for r in gold_rows:
        assert r["signature"]["resolved_operations"].get("ANOD/ANOD") == "ANOD_02", (
            f"ANOD_02 resolved for золото row {r['rows']}"
        )

    # 9. Rows with color=шампань → ANOD_06
    champagne_rows = [r for r in results if "шампань" in r["color"].lower()]
    assert len(champagne_rows) > 0, "Should have rows with color=шампань"
    for r in champagne_rows:
        assert r["signature"]["resolved_operations"].get("ANOD/ANOD") == "ANOD_06", (
            f"ANOD_06 resolved for шампань row {r['rows']}"
        )

    # 10. Rows with color=медь → ANOD_07
    copper_rows = [r for r in results if "мед" in r["color"].lower()]
    assert len(copper_rows) > 0, "Should have rows with color=медь"
    for r in copper_rows:
        assert r["signature"]["resolved_operations"].get("ANOD/ANOD") == "ANOD_07", (
            f"ANOD_07 resolved for медь row {r['rows']}"
        )

    # 11. Rows with color=титан → ANOD_08
    titan_rows = [r for r in results if "титан" in r["color"].lower()]
    assert len(titan_rows) > 0, "Should have rows with color=титан"
    for r in titan_rows:
        assert r["signature"]["resolved_operations"].get("ANOD/ANOD") == "ANOD_08", (
            f"ANOD_08 resolved for титан row {r['rows']}"
        )

    # 12. Core sections (WH, ANOD, FG_WH) should ALWAYS be required
    for r in results:
        assert "WH" in r["signature"]["required_sections"], f"WH always required, failed for row {r['rows']}"
        assert "ANOD" in r["signature"]["required_sections"], f"ANOD always required, failed for row {r['rows']}"
        assert "FG_WH" in r["signature"]["required_sections"], f"FG_WH always required, failed for row {r['rows']}"

    # 13. Empty operation rows → DRILL and PRESS both excluded
    empty_op_rows = [r for r in results if not r["operation"]]
    assert len(empty_op_rows) > 0, "Should have rows with empty operation"
    for r in empty_op_rows:
        assert "DRILL" in r["signature"]["excluded_sections"], f"DRILL excluded when op empty, row {r['rows']}"
        assert "PRESS" in r["signature"]["excluded_sections"], f"PRESS excluded when op empty, row {r['rows']}"


@pytest.mark.asyncio
async def test_test_xls_unique_route_combinations(client, session) -> None:
    """Verify that test.xls rows produce all expected unique route combinations.

    Expected unique combos from the data:
    - 4 colors (черный, серебро, золото, шампань, медь, титан) x
    - 3 operation types (empty, окно, гребенка, сверло) x
    - 2 packaging types (ГП, П/Ф)
    = many unique combinations
    """
    profile_id = await _seed_full_environment(session)
    rows = _load_test_rows()

    combo_set = set()
    for row_data in rows:
        payload = row_data["payload"]
        result = await select_route_for_payload(
            session,
            payload,
            product=None,
            profile_id=profile_id,
        )

        # Build a compact combo key
        combo = (
            tuple(sorted([s["code"] for s in result.required_sections])),
            tuple(sorted([s["code"] for s in result.excluded_sections])),
            tuple(sorted(result.resolved_operations.values())),
        )
        combo_set.add(combo)

    # There should be at least 10 unique combinations given the diversity of test.xls
    assert len(combo_set) >= 10, (
        f"Expected at least 10 unique route combinations from test.xls, got {len(combo_set)}:\n"
        + "\n".join([f"  {c}" for c in sorted(combo_set)])
    )


@pytest.mark.asyncio
async def test_test_xls_row_2256_with_skip_shot_blast_excludes_shot(client, session) -> None:
    """ЮП-2256 (row 7 in test.xls) — черный, без операции, ГП.

    В CRM для этого продукта установлен пропуск дробеструя (skip_shot_blast=True).
    Проверяем что SHOT исключается из маршрута.
    """
    from app.models.product import Product, ProductType

    profile_id = await _seed_full_environment(session)

    # Create product matching real ЮП-2256 with skip_shot_blast=True
    product = Product(
        sku="ЮП-2256",
        name="Микроплинтус 18мм 2,4м анод. черный матовый",
        type=ProductType.finished_good,
        unit="pcs",
        skip_shot_blast=True,
    )
    session.add(product)
    await session.flush()

    # Payload from test.xls row 7: color=черный, operation="", output_kind=ГП
    payload = {
        "operation": "",
        "output_kind": "ГП",
        "color": "черный",
        "raw_columns": {"operation": "", "output_kind": "ГП", "color": "черный"},
    }

    result = await select_route_for_payload(
        session,
        payload,
        product=product,
        profile_id=profile_id,
    )

    required_codes = {s["code"] for s in result.required_sections}
    excluded_codes = {s["code"] for s in result.excluded_sections}

    # SHOT must be excluded because product has skip_shot_blast=True
    assert "SHOT" in excluded_codes, f"SHOT must be excluded for ЮП-2256 (skip_shot_blast=True), got excluded: {excluded_codes}"
    assert "SHOT" not in required_codes, f"SHOT must NOT be required for ЮП-2256, got required: {required_codes}"

    # But core sections and ГП route sections should still be present
    assert "WH" in required_codes
    assert "ANOD" in required_codes
    assert "FG_WH" in required_codes
    assert "WIP_WH" in required_codes  # ГП → stretch route
    assert "SAW" in required_codes
    assert "PACK" in required_codes

    # Operations should resolve correctly
    assert result.resolved_operations.get(("ANOD", "ANOD")) == "ANOD_05", "черный → ANOD_05"
    assert result.resolved_operations.get(("ANOD", "PACK")) == "PACK_STRETCH", "ГП → PACK_STRETCH"

    # No PRESS/DRILL since operation is empty
    assert "DRILL" in excluded_codes
    assert "PRESS" in excluded_codes
