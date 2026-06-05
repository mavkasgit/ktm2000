from decimal import Decimal
from io import BytesIO
import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.models.product import Product, ProductType
from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.spg_remainder import SpgRemainder
from app.models.route import ProductionRoute, RouteStage, RouteOperation, RouteRuleProfile
from app.models.defect import Defect, DefectItem, DefectStatus, DefectDecisionType
from app.models.user import User, UserRole


async def _make_admin(session, email: str = "admin-def@test.local") -> User:
    user = User(
        email=email,
        password_hash="x",
        full_name="Defect Admin",
        role=UserRole.admin,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_product(session, sku: str) -> Product:
    product = Product(
        sku=sku,
        name=f"Product {sku}",
        type=ProductType.component,
        unit="pcs",
        profile_type="universal",
    )
    session.add(product)
    await session.flush()
    return product


async def _setup_route_with_stages(session) -> ProductionRoute:
    # 1. Create RouteRuleProfile
    profile = RouteRuleProfile(
        code="packaging_map_rp",
        name="Упаковочная карта РП",
        is_active=True,
        priority=1000,
        route_sections=["DRILL", "SAW", "SENT"],
    )
    session.add(profile)
    await session.flush()

    # 2. Create ProductionRoute
    route = ProductionRoute(
        code="dynamic_packaging_map_rp",
        name="Dynamic: Упаковочная карта РП",
        is_active=True,
        sort_order=1000,
    )
    session.add(route)
    await session.flush()

    # 3. Create stages and operations
    sec_drill = Section(code="DRILL", name="Сверловка", is_active=True)
    sec_saw = Section(code="SAW", name="Резка", is_active=True)
    sec_sent = Section(code="SENT", name="Отправлено", is_active=True)
    session.add(sec_drill)
    session.add(sec_saw)
    session.add(sec_sent)
    await session.flush()

    # Stage 1: DRILL
    stage1 = RouteStage(route_id=route.id, sequence=1, section_id=sec_drill.id)
    session.add(stage1)
    await session.flush()
    op1 = RouteOperation(route_stage_id=stage1.id, sequence=1, operation_code="DRILL_OP", operation_name="Сверление отверстий")
    session.add(op1)

    # Stage 2: SAW
    stage2 = RouteStage(route_id=route.id, sequence=2, section_id=sec_saw.id)
    session.add(stage2)
    await session.flush()
    op2 = RouteOperation(route_stage_id=stage2.id, sequence=1, operation_code="SAW_OP", operation_name="Поперечный распил")
    session.add(op2)

    await session.flush()
    return route


@pytest.mark.asyncio
async def test_get_product_route_stages(client, session):
    await _make_admin(session)
    product = await _make_product(session, "FG-STAGES-TEST")
    await _setup_route_with_stages(session)

    resp = await client.get(f"/api/products/{product.id}/route-stages")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 2
    assert data[0]["section_code"] == "DRILL"
    assert data[0]["operations"][0]["operation_code"] == "DRILL_OP"
    assert data[1]["section_code"] == "SAW"
    assert data[1]["operations"][0]["operation_code"] == "SAW_OP"


@pytest.mark.asyncio
async def test_import_remainders_excel(client, session):
    await _make_admin(session)
    product = await _make_product(session, "FG-IMPORT-TEST")
    route = await _setup_route_with_stages(session)
    
    # Create SPG
    spg = StorageProductionGroup(code="WIP", name="WIP SPG")
    session.add(spg)
    await session.flush()

    # Link section to SPG
    drill_sec = await session.scalar(select(Section).where(Section.code == "DRILL"))
    session.add(SpgSection(spg_id=spg.id, section_id=drill_sec.id))
    await session.flush()

    # Generate Excel in memory
    wb = Workbook()
    ws = wb.active
    ws.append(["Артикул", "Количество", "Выполненные операции"])
    ws.append(["FG-IMPORT-TEST", 120, "Сверление отверстий"])
    
    out = BytesIO()
    wb.save(out)
    excel_bytes = out.getvalue()

    resp = await client.post(
        f"/api/spg/{spg.id}/remainders/import",
        files={"file": ("import.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True
    assert data["imported_count"] == 1
    assert len(data["errors"]) == 0

    # Verify remainder exists in DB with completed stage
    remainder = await session.scalar(
        select(SpgRemainder).where(SpgRemainder.product_id == product.id, SpgRemainder.spg_id == spg.id)
    )
    assert remainder is not None
    assert remainder.remainder_quantity == Decimal("120")
    assert len(remainder.completed_stages_json) == 1
    assert remainder.completed_stages_json[0]["operation_code"] == "DRILL_OP"


@pytest.mark.asyncio
async def test_manual_defect_registration_and_scrap_decision(client, session):
    await _make_admin(session)
    product = await _make_product(session, "FG-DEFECT-TEST")
    route = await _setup_route_with_stages(session)
    
    # Create SPG
    spg = StorageProductionGroup(code="WIP2", name="WIP SPG 2")
    session.add(spg)
    await session.flush()

    drill_sec = await session.scalar(select(Section).where(Section.code == "DRILL"))
    stage = await session.scalar(select(RouteStage).where(RouteStage.route_id == route.id).limit(1))

    # Create remainder
    remainder = SpgRemainder(
        product_id=product.id,
        spg_id=spg.id,
        remainder_quantity=Decimal("50.000"),
        original_issued=Decimal("50.000"),
        completed_stages_json=[],
        source="manual",
    )
    session.add(remainder)
    await session.flush()

    # Register defect manually
    resp = await client.post(
        "/api/shopfloor/defects",
        json={
            "product_id": product.id,
            "section_id": drill_sec.id,
            "route_stage_id": stage.id,
            "spg_remainder_id": remainder.id,
            "quantity": 10,
            "reason": "Царапины",
            "comment": "Вручную обнаружено на СПГ"
        }
    )
    assert resp.status_code == 200, resp.text
    defect_id = resp.json()["defect_id"]

    # Verify defect was created
    defect = await session.scalar(select(Defect).where(Defect.id == defect_id))
    assert defect is not None
    assert defect.task_id is None
    assert defect.spg_remainder_id == remainder.id
    assert defect.route_stage_id == stage.id

    # Decide scrap decision on this defect
    dec_resp = await client.post(
        f"/api/shopfloor/defects/{defect_id}/decisions",
        json={
            "decision_type": DefectDecisionType.scrap.value,
            "quantity": 10,
            "comment": "Списание брака на СПГ"
        }
    )
    assert dec_resp.status_code == 200, dec_resp.text

    # Verify remainder quantity has been decreased
    await session.refresh(remainder)
    assert remainder.remainder_quantity == Decimal("40")
    assert remainder.consumed_at is None

    # Decide scrap for remaining 40 to verify consumed_at is set
    dec_resp2 = await client.post(
        f"/api/shopfloor/defects/{defect_id}/decisions",
        json={
            "decision_type": DefectDecisionType.scrap.value,
            "quantity": 40,
            "comment": "Списание всего остатка"
        }
    )
    assert dec_resp2.status_code == 200, dec_resp2.text
    await session.refresh(remainder)
    assert remainder.remainder_quantity == Decimal("0")
    assert remainder.consumed_at is not None


@pytest.mark.asyncio
async def test_manual_defect_invalid_rework_decision(client, session):
    await _make_admin(session, "defect-invalid-rework@test.local")
    product = await _make_product(session, "FG-REWORK-ERR")
    await _setup_route_with_stages(session)
    
    spg = StorageProductionGroup(code="WIP_ERR", name="WIP SPG ERR")
    session.add(spg)
    await session.flush()

    drill_sec = await session.scalar(select(Section).where(Section.code == "DRILL"))
    stage = await session.scalar(select(RouteStage).limit(1))

    # 1. Register defect manually (no task_id)
    resp = await client.post(
        "/api/shopfloor/defects",
        json={
            "product_id": product.id,
            "section_id": drill_sec.id,
            "route_stage_id": stage.id,
            "quantity": 5,
            "reason": "scratches",
            "comment": "manual defect"
        }
    )
    assert resp.status_code == 200, resp.text
    defect_id = resp.json()["defect_id"]

    # 2. Try to decide rework_current (which should fail with 400 Bad Request)
    dec_resp = await client.post(
        f"/api/shopfloor/defects/{defect_id}/decisions",
        json={
            "decision_type": "rework_current",
            "quantity": 5,
            "comment": "rework manual defect"
        }
    )
    assert dec_resp.status_code == 400, dec_resp.text
    assert "Rework decisions require an associated work task" in dec_resp.json()["detail"]


@pytest.mark.asyncio
async def test_manual_defect_invalid_stage_or_remainder(client, session):
    await _make_admin(session, "defect-invalid-refs@test.local")
    product = await _make_product(session, "FG-INVALID-REFS")
    drill_sec = Section(code="DRILL_X", name="Сверловка X", is_active=True)
    session.add(drill_sec)
    await session.flush()

    # Test nonexistent remainder
    resp1 = await client.post(
        "/api/shopfloor/defects",
        json={
            "product_id": product.id,
            "section_id": drill_sec.id,
            "spg_remainder_id": 99999,
            "quantity": 5,
        }
    )
    assert resp1.status_code == 400, resp1.text
    assert "SpgRemainder 99999 not found" in resp1.json()["detail"]

    # Test nonexistent route stage
    resp2 = await client.post(
        "/api/shopfloor/defects",
        json={
            "product_id": product.id,
            "section_id": drill_sec.id,
            "route_stage_id": 99999,
            "quantity": 5,
        }
    )
    assert resp2.status_code == 400, resp2.text
    assert "RouteStage 99999 not found" in resp2.json()["detail"]


@pytest.mark.asyncio
async def test_import_remainders_excel_edge_cases(client, session):
    await _make_admin(session, "excel-edge@test.local")
    product = await _make_product(session, "FG-VALID-SKU")
    
    spg = StorageProductionGroup(code="WIP_EXCEL_EDGE", name="WIP SPG Excel Edge")
    session.add(spg)
    await session.flush()

    # Generate Excel containing some valid and some invalid rows in memory
    wb = Workbook()
    ws = wb.active
    ws.append(["Артикул", "Количество"])
    ws.append(["FG-VALID-SKU", 100])
    ws.append(["FG-NONEXISTENT", 50])  # Non-existent SKU
    ws.append(["FG-VALID-SKU", -10])    # Negative quantity
    ws.append(["FG-VALID-SKU", "abc"])  # Invalid quantity format
    
    out = BytesIO()
    wb.save(out)
    excel_bytes = out.getvalue()

    resp = await client.post(
        f"/api/spg/{spg.id}/remainders/import",
        files={"file": ("import_edge.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True
    assert data["imported_count"] == 1  # Only the first row is valid
    assert len(data["errors"]) == 3
    assert "FG-NONEXISTENT" in data["errors"][0] and "не найден" in data["errors"][0]
    assert "Неверное количество" in data["errors"][1] and "-10" in data["errors"][1]
    assert "Неверное количество" in data["errors"][2] and "abc" in data["errors"][2]


@pytest.mark.asyncio
async def test_manual_defect_scrap_exceeding_remainder_quantity(client, session):
    await _make_admin(session, "defect-exceed-scrap@test.local")
    product = await _make_product(session, "FG-EXCEED-TEST")
    await _setup_route_with_stages(session)
    
    spg = StorageProductionGroup(code="WIP3", name="WIP SPG 3")
    session.add(spg)
    await session.flush()

    drill_sec = await session.scalar(select(Section).where(Section.code == "DRILL"))
    stage = await session.scalar(select(RouteStage).limit(1))

    # Create remainder with quantity 15
    remainder = SpgRemainder(
        product_id=product.id,
        spg_id=spg.id,
        remainder_quantity=Decimal("15.000"),
        original_issued=Decimal("15.000"),
        completed_stages_json=[],
        source="manual",
    )
    session.add(remainder)
    await session.flush()

    # Register defect with quantity 20 (which is larger than 15)
    resp = await client.post(
        "/api/shopfloor/defects",
        json={
            "product_id": product.id,
            "section_id": drill_sec.id,
            "route_stage_id": stage.id,
            "spg_remainder_id": remainder.id,
            "quantity": 20,
            "reason": "scratches",
            "comment": "manual defect larger than remainder"
        }
    )
    assert resp.status_code == 200, resp.text
    defect_id = resp.json()["defect_id"]

    # Decide scrap for 20
    dec_resp = await client.post(
        f"/api/shopfloor/defects/{defect_id}/decisions",
        json={
            "decision_type": DefectDecisionType.scrap.value,
            "quantity": 20,
            "comment": "Списание брака больше остатка"
        }
    )
    assert dec_resp.status_code == 200, dec_resp.text

    # Verify remainder quantity has gone negative (-5) and consumed_at was set
    await session.refresh(remainder)
    assert remainder.remainder_quantity == Decimal("-5")
    assert remainder.consumed_at is not None

