"""Tests for dynamic route stages and operations in import preview."""
from io import BytesIO

from decimal import Decimal

import pytest
from openpyxl import Workbook

from app.core.config import settings
from app.models.import_template import ImportTemplate
from app.models.product import Product, ProductType
from app.models.route import ProductionRoute, RouteRuleProfile, RouteStage, RouteOperation, SectionOperation
from app.models.section import Section
from app.models.techcard import Techcard, TechcardLine
from app.seeds.selection_rules import SELECTION_RULES
from app.seeds.seeders.selection_rules_seeder import seed_selection_rules


def _workbook_with_row(
    sku: str = "TEST-001",
    name: str = "Test Product",
    color: str = "серебро",
    operation: str = "",
    packaging: str = "спанбонд",
) -> bytes:
    """Create minimal workbook with one data row."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Plan"
    # Header row
    ws.append([
        "Артикул", "Наименование", "Цвет", "Пробивка/сверловка",
        "Упаковка", "Кол-во",
    ])
    # Data row
    ws.append([sku, name, color, operation, packaging, 100])
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


async def _make_section(session, code: str, name: str, kind: str = "standard", sort_order: int = 0) -> Section:
    section = Section(code=code, name=name, kind=kind, is_active=True, sort_order=sort_order)
    session.add(section)
    await session.flush()
    return section


async def _make_section_operation(
    session,
    section_id: int,
    operation_code: str,
    operation_name: str,
    group_code: str,
    group_name: str,
    sort_order: int = 0,
    is_significant: bool = False,
) -> SectionOperation:
    sop = SectionOperation(
        section_id=section_id,
        operation_code=operation_code,
        operation_name=operation_name,
        group_code=group_code,
        group_name=group_name,
        sort_order=sort_order,
        is_significant=is_significant,
    )
    session.add(sop)
    await session.flush()
    return sop


async def _make_template(session) -> ImportTemplate:
    template = ImportTemplate(
        name="Route Stages Test",
        code="route-stages-test",
        is_active=True,
        column_mapping={
            "sku": {"header": "Артикул", "column": "A"},
            "name": {"header": "Наименование", "column": "B"},
            "color": {"header": "Цвет", "column": "C"},
            "operation": {"header": "Пробивка/сверловка", "column": "D"},
            "packaging": {"header": "Упаковка", "column": "E"},
            "quantity": {"header": "Кол-во", "column": "F"},
        },
    )
    session.add(template)
    await session.flush()
    return template


async def _make_profile(session, template_id: int) -> RouteRuleProfile:
    profile = RouteRuleProfile(
        name="Route Stages Test Profile",
        code="packaging_map_rp",  # Use the actual profile code from seeds
        import_template_id=template_id,
        is_active=True,
        route_sections=["WH", "SHOT", "ANOD", "FG_WH", "SHIPMENT", "SENT"],
    )
    session.add(profile)
    await session.flush()
    return profile


async def _seed_infrastructure(session, profile: RouteRuleProfile):
    """Seed sections, section_operations, and selection rules."""
    # Create sections
    sections = {
        "WH": ("Склад заготовок", "warehouse", 1),
        "DRILL": ("Сверловка", "processing", 2),
        "PRESS": ("Пресс", "processing", 3),
        "SHOT": ("Дробеструй", "processing", 4),
        "ANOD": ("Анодирование", "processing", 5),
        "WIP_WH": ("Склад промежуточной продукции", "warehouse", 6),
        "SAW": ("Пила", "processing", 7),
        "PACK": ("Упаковка", "processing", 8),
        "FG_WH": ("Склад готовой продукции", "warehouse", 9),
        "SHIPMENT": ("Отгрузка", "processing", 10),
        "SENT": ("Отправлено", "final", 11),
    }
    
    section_map = {}
    for code, (name, kind, order) in sections.items():
        section = await _make_section(session, code, name, kind, order)
        section_map[code] = section
    
    # Create ANOD section operations (ANOD group)
    await _make_section_operation(
        session, section_map["ANOD"].id,
        "ANOD_01", "Анод: Серебро",
        group_code="ANOD", group_name="Анодирование",
        sort_order=1, is_significant=True,
    )
    await _make_section_operation(
        session, section_map["ANOD"].id,
        "ANOD_05", "Анод: Чёрный",
        group_code="ANOD", group_name="Анодирование",
        sort_order=2, is_significant=True,
    )
    await _make_section_operation(
        session, section_map["ANOD"].id,
        "ANOD_06", "Анод: Шампань",
        group_code="ANOD", group_name="Анодирование",
        sort_order=3, is_significant=True,
    )
    
    # Seed selection rules
    await seed_selection_rules(session, SELECTION_RULES, profile)
    
    # Create product + techcard + route so route resolution works
    product = Product(sku="TEST-001", name="Test Product", type=ProductType.finished_good, unit="pcs")
    session.add(product)
    await session.flush()
    
    route = ProductionRoute(name="Test Route", is_active=True)
    session.add(route)
    await session.flush()
    
    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(TechcardLine(techcard_id=techcard.id, component_product_id=product.id, quantity=Decimal("1"), unit="pcs"))
    
    # Create route stages and operations for each section in profile's route_sections
    stage_ops = ["ISSUE_RAW", "SHOT_BLAST", "ANOD", "MOVE_TO_FG", "SHIPMENT", "SENT"]
    for idx, (section_code, op_code) in enumerate(zip(profile.route_sections, stage_ops, strict=True), start=1):
        section = section_map[section_code]
        session.add(
            RouteStage(
                route_id=route.id,
                sequence=idx,
                section_id=section.id,
                is_final=idx == len(profile.route_sections),
                operations=[
                    RouteOperation(
                        sequence=1,
                        operation_code=op_code,
                        operation_name=op_code,
                    )
                ]
            )
        )
    
    await session.commit()


@pytest.mark.asyncio
async def test_preview_includes_route_stages_for_resolved_route(client, session, tmp_path, monkeypatch) -> None:
    """Verify that preview response includes route stages and operations when route is resolved."""
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    # Setup template, profile, and infrastructure
    template = await _make_template(session)
    profile = await _make_profile(session, template.id)
    await _seed_infrastructure(session, profile)

    response = await client.post(
        f"/api/imports/excel/preview?template_id={template.id}",
        files={
            "file": (
                "plan.xlsx",
                _workbook_with_row(sku="TEST-001", color="серебро"),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1

    item = body["items"][0]
    after_data = item["after_data"]

    # Route should be resolved
    assert after_data["route_id"] is not None
    assert after_data["route_name"] is not None

    # route stages should be present
    assert "route_steps" in after_data
    route_stages = after_data["route_steps"]
    assert isinstance(route_stages, list)
    assert len(route_stages) > 0

    # Verify structure of route stages
    first_stage = route_stages[0]
    assert "sequence" in first_stage
    assert "section_code" in first_stage
    assert "section_name" in first_stage
    assert "operation_code" in first_stage
    assert "operation_name" in first_stage
    assert "is_significant" in first_stage
    assert "combined_op_group" in first_stage


@pytest.mark.asyncio
async def test_preview_route_stages_resolves_anod_operation_by_color(
    client, session, tmp_path, monkeypatch
) -> None:
    """Verify that route stages resolve ANOD operation based on color."""
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    template = await _make_template(session)
    profile = await _make_profile(session, template.id)
    await _seed_infrastructure(session, profile)

    # Test with black color
    response = await client.post(
        f"/api/imports/excel/preview?template_id={template.id}",
        files={
            "file": (
                "plan.xlsx",
                _workbook_with_row(color="чёрный"),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    item = body["items"][0]
    route_stages = item["after_data"]["route_steps"]

    # Find ANOD stage
    anod_stage = next((s for s in route_stages if s["section_code"] == "ANOD"), None)
    assert anod_stage is not None

    # Should resolve to ANOD_05 (black)
    assert "ANOD_05" in (anod_stage["operation_code"] or "")


@pytest.mark.asyncio
async def test_preview_route_stages_excludes_sections_for_empty_operation(
    client, session, tmp_path, monkeypatch
) -> None:
    """Verify that route stages exclude DRILL and PRESS when operation is empty."""
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    template = await _make_template(session)
    profile = await _make_profile(session, template.id)
    await _seed_infrastructure(session, profile)

    response = await client.post(
        f"/api/imports/excel/preview?template_id={template.id}",
        files={
            "file": (
                "plan.xlsx",
                _workbook_with_row(operation=""),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    item = body["items"][0]
    route_stages = item["after_data"]["route_steps"]

    # Should not contain DRILL or PRESS sections
    section_codes = [s["section_code"] for s in route_stages]
    assert "DRILL" not in section_codes
    assert "PRESS" not in section_codes


@pytest.mark.asyncio
async def test_preview_no_route_stages_when_route_not_found(
    client, session, tmp_path, monkeypatch
) -> None:
    """Verify that route stages are not present when route cannot be resolved."""
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    # Create template WITHOUT profile - route won't be resolved
    template = await _make_template(session)
    await session.commit()

    response = await client.post(
        f"/api/imports/excel/preview?template_id={template.id}",
        files={
            "file": (
                "plan.xlsx",
                _workbook_with_row(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    item = body["items"][0]
    after_data = item["after_data"]

    # Route should not be resolved
    assert after_data["route_id"] is None

    # route stages should not be present
    assert "route_steps" not in after_data
