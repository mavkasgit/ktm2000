import pytest
from io import BytesIO
from openpyxl import Workbook
from decimal import Decimal
from sqlalchemy import select

from app.models.product import Product, ProductType
from app.models.section import Section
from app.models.spg import StorageProductionGroup, SpgSection
from app.models.spg_remainder import SpgRemainder
from app.models.defect import Defect, DefectItem
from app.models.user import User, UserRole
from app.models.route import ProductionRoute, RouteStage, SectionOperation


def create_excel_file(headers: list[str], rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out.getvalue()


@pytest.mark.asyncio
async def test_import_remainders_success(client, session) -> None:
    # 1. Setup user (seeded globally in conftest.py)

    # 2. Setup test entities
    spg = StorageProductionGroup(code="SPG-REM", name="Spg for Remainders")
    product = Product(sku="SKU-REM-1", name="Product for Rem", type=ProductType.finished_good, unit="pcs")
    session.add_all([spg, product])
    await session.commit()

    # 3. Prepare Excel
    headers = ["Артикул / SKU", "Количество", "Выполненные операции"]
    rows = [
        ["SKU-REM-1", 15.5, ""],
    ]
    file_bytes = create_excel_file(headers, rows)

    # 4. Post import request
    resp = await client.post(
        f"/api/spg/{spg.id}/remainders/import",
        files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["imported_count"] == 1
    assert len(data["errors"]) == 0

    # 5. Verify DB record
    remainders = (await session.execute(
        select(SpgRemainder).where(SpgRemainder.spg_id == spg.id)
    )).scalars().all()
    assert len(remainders) == 1
    assert remainders[0].product_id == product.id
    assert remainders[0].remainder_quantity == Decimal("15.500")
    assert remainders[0].source == "manual"


@pytest.mark.asyncio
async def test_import_defects_success(client, session) -> None:
    # 1. Setup user (seeded globally in conftest.py)

    # 2. Setup test entities
    spg = StorageProductionGroup(code="SPG-DEF", name="Spg for Defects")
    section = Section(code="SEC-DEF-1", name="Defect Section")
    product = Product(sku="SKU-DEF-1", name="Product for Def", type=ProductType.finished_good, unit="pcs")
    session.add_all([spg, section, product])
    await session.flush()

    # Link section to SPG
    session.add(SpgSection(spg_id=spg.id, section_id=section.id, sort_order=10))
    await session.commit()

    # 3. Prepare Excel
    headers = ["Артикул / SKU", "Количество", "Участок", "Комментарий"]
    rows = [
        ["SKU-DEF-1", 3.0, "Defect Section", "Брак при сверловке"],
    ]
    file_bytes = create_excel_file(headers, rows)

    # 4. Post import request
    resp = await client.post(
        f"/api/spg/{spg.id}/defects/import",
        files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["imported_count"] == 1
    assert len(data["errors"]) == 0

    # 5. Verify DB record
    defects = (await session.execute(
        select(Defect).where(Defect.section_id == section.id)
    )).scalars().all()
    assert len(defects) == 1
    assert defects[0].product_id == product.id
    assert defects[0].comment == "Брак при сверловке"

    items = (await session.execute(
        select(DefectItem).where(DefectItem.defect_id == defects[0].id)
    )).scalars().all()
    assert len(items) == 1
    assert items[0].quantity == Decimal("3.000")


@pytest.mark.asyncio
async def test_download_remainders_template(client, session) -> None:
    spg = StorageProductionGroup(code="SPG-TMP", name="Spg for Template")
    session.add(spg)
    await session.commit()

    resp = await client.get(f"/api/spg/{spg.id}/remainders/import/template")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "filename*=UTF-8''%D0%A8%D0%B0%D0%B1%D0%BB%D0%BE%D0%BD%20%D0%B8%D0%BC%D0%BF%D0%BE%D1%80%D1%82%D0%B0%20%D0%BE%D1%81%D1%82%D0%B0%D1%82%D0%BA%D0%BE%D0%B2.xlsx" in resp.headers["content-disposition"]


@pytest.mark.asyncio
async def test_import_remainders_preview_and_atomic(client, session) -> None:
    spg = StorageProductionGroup(code="SPG-REM-PREV", name="Spg for Preview")
    product1 = Product(sku="ALS-1289", name="Product 1289", type=ProductType.finished_good, unit="pcs")
    product2 = Product(sku="ЮП-2630", name="Product 2630", type=ProductType.finished_good, unit="pcs")
    session.add_all([spg, product1, product2])
    await session.commit()

    # Excel with 3 rows:
    # Row 2: ALS-1289, 100, PRESS, ANOD
    # Row 3: ЮП-2630, 200, PRESS
    # Row 4: SKU-NOT-EXIST, 300
    headers = ["Артикул", "Количество", "Стадия 1", "Стадия 2"]
    rows = [
        ["ALS-1289", 100, "PRESS", "ANOD"],
        ["ЮП-2630", 200, "PRESS"],
        ["SKU-NOT-EXIST", 300, ""],
    ]
    file_bytes = create_excel_file(headers, rows)

    # 1. Preview (without saving)
    resp = await client.post(
        f"/api/spg/{spg.id}/remainders/import/preview",
        files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_rows"] == 4  # header + 3 rows
    assert data["summary"]["total"] == 3
    assert data["summary"]["valid"] == 2
    assert data["summary"]["invalid"] == 1
    assert len(data["items"]) == 3
    
    # Assert stages resolved
    assert data["items"][0]["sku"] == "ALS-1289"
    assert data["items"][0]["status"] == "pending"
    assert data["items"][2]["sku"] == "SKU-NOT-EXIST"
    assert data["items"][2]["status"] == "invalid"

    # Verify no remainders added in DB yet
    remainders = (await session.execute(
        select(SpgRemainder).where(SpgRemainder.spg_id == spg.id)
    )).scalars().all()
    assert len(remainders) == 0

    # 2. Atomic import without skip_invalid: should fail due to SKU-NOT-EXIST
    resp = await client.post(
        f"/api/spg/{spg.id}/remainders/import",
        files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"skip_invalid": "false"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert len(data["errors"]) > 0

    # Verify no remainders added in DB (atomic transaction fail check)
    remainders = (await session.execute(
        select(SpgRemainder).where(SpgRemainder.spg_id == spg.id)
    )).scalars().all()
    assert len(remainders) == 0

    # 3. Import with skip_invalid: should succeed and import only 2 rows
    resp = await client.post(
        f"/api/spg/{spg.id}/remainders/import",
        files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"skip_invalid": "true"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["imported_count"] == 2

    # Verify 2 remainders added in DB
    remainders = (await session.execute(
        select(SpgRemainder).where(SpgRemainder.spg_id == spg.id)
    )).scalars().all()
    assert len(remainders) == 2


@pytest.mark.asyncio
async def test_import_remainders_clear_existing(client, session) -> None:
    spg = StorageProductionGroup(code="SPG-REM-CLEAR", name="Spg for Clear")
    product = Product(sku="ALS-1289", name="Product 1289", type=ProductType.finished_good, unit="pcs")
    session.add_all([spg, product])
    await session.flush()

    # Pre-add a remainder
    old_rem = SpgRemainder(
        product_id=product.id,
        spg_id=spg.id,
        remainder_quantity=Decimal("50.0"),
        original_issued=Decimal("50.0"),
        source="manual",
    )
    session.add(old_rem)
    await session.commit()

    headers = ["Артикул", "Количество"]
    rows = [
        ["ALS-1289", 75.0],
    ]
    file_bytes = create_excel_file(headers, rows)

    # Import with clear_existing
    resp = await client.post(
        f"/api/spg/{spg.id}/remainders/import",
        files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"clear_existing": "true"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["imported_count"] == 1

    # Verify DB: old remainder (50) is gone, only new remainder (75) exists
    remainders = (await session.execute(
        select(SpgRemainder).where(SpgRemainder.spg_id == spg.id)
    )).scalars().all()
    assert len(remainders) == 1
    assert remainders[0].remainder_quantity == Decimal("75.000")


@pytest.mark.asyncio
async def test_import_defects_errors(client, session) -> None:
    # 1. Setup user (seeded globally in conftest.py)

    # 2. Setup entities
    spg = StorageProductionGroup(code="SPG-ERR", name="Spg for Errors")
    section_linked = Section(code="SEC-LNK", name="Linked Section")
    section_unlinked = Section(code="SEC-UNLNK", name="Unlinked Section")
    product = Product(sku="SKU-ERR-1", name="Product for Err", type=ProductType.finished_good, unit="pcs")
    session.add_all([spg, section_linked, section_unlinked, product])
    await session.flush()

    session.add(SpgSection(spg_id=spg.id, section_id=section_linked.id, sort_order=10))
    await session.commit()

    # Excel containing errors:
    # 1. Non-existent SKU
    # 2. Section not linked to SPG
    headers = ["Артикул / SKU", "Количество", "Участок"]
    rows = [
        ["SKU-NON-EXISTENT", 2.0, "Linked Section"],
        ["SKU-ERR-1", 4.0, "Unlinked Section"],
    ]
    file_bytes = create_excel_file(headers, rows)

    resp = await client.post(
        f"/api/spg/{spg.id}/defects/import",
        files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["imported_count"] == 0
    assert len(data["errors"]) == 2
    assert "продукт с sku 'sku-non-existent' не найден" in data["errors"][0].lower()
    assert "участок 'unlinked section' не привязан к данной гхп" in data["errors"][1].lower()


@pytest.mark.asyncio
async def test_import_remainders_with_ops_first_row(client, session) -> None:
    # 1. Setup entities
    spg = StorageProductionGroup(code="SPG-OPS-1ST", name="Spg with ops on 1st row")
    section = Section(code="SEC-OPS-1ST", name="Ops 1st Row Section")
    product = Product(sku="SKU-OPS-1", name="Product Ops 1", type=ProductType.finished_good, unit="pcs")
    session.add_all([spg, section, product])
    await session.flush()

    # Link section to SPG
    session.add(SpgSection(spg_id=spg.id, section_id=section.id, sort_order=10))
    
    # Create SectionOperation
    sec_op = SectionOperation(
        section_id=section.id,
        operation_code="OP-OPS-1",
        operation_name="Дробеструй",
        is_significant=True,
        group_code="GRP-1"
    )
    session.add(sec_op)
    
    # Create Route and RouteStage
    route = ProductionRoute(name="Route for Product Ops 1", is_active=True)
    session.add(route)
    await session.flush()
    
    route_stage = RouteStage(
        route_id=route.id,
        sequence=1,
        section_id=section.id,
        is_significant=True,
    )
    session.add(route_stage)
    await session.flush()
    
    from app.models.route import RouteOperation
    route_op = RouteOperation(
        route_stage_id=route_stage.id,
        sequence=1,
        operation_code="OP-OPS-1",
        operation_name="Дробеструй",
    )
    session.add(route_op)
    await session.commit()

    # 2. Prepare Excel where 1st row is ops dictionary and 2nd row is headers
    wb = Workbook()
    ws = wb.active
    ws.append(["Доступные операции: Дробеструй"])
    ws.append(["Артикул", "Количество", "Выполненные операции"])
    ws.append(["SKU-OPS-1", 10.0, "Дробеструй"])
    
    out = BytesIO()
    wb.save(out)
    out.seek(0)
    file_bytes = out.getvalue()

    # 3. Post preview request
    resp = await client.post(
        f"/api/spg/{spg.id}/remainders/import/preview",
        files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_rows"] == 3  # ops row + headers row + data row
    assert data["summary"]["total"] == 1
    assert data["summary"]["valid"] == 1
    
    # Check that completed stage was successfully parsed!
    item = data["items"][0]
    assert item["sku"] == "SKU-OPS-1"
    assert len(item["completed_stages"]) == 1
    assert item["completed_stages"][0]["operation_name"] == "Дробеструй"
    assert item["completed_stages"][0]["section_id"] == section.id
