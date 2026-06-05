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
    # 1. Setup user (id=1) to satisfy foreign key constraints
    from sqlalchemy import text
    await session.execute(text(
        "INSERT INTO users (id, email, password_hash, full_name, role, is_active) "
        "OVERRIDING SYSTEM VALUE "
        "VALUES (1, 'system@local', '', 'System User', 'admin', true)"
    ))
    await session.flush()

    # 2. Setup test entities
    spg = StorageProductionGroup(code="SPG-REM", name="Spg for Remainders")
    product = Product(sku="SKU-REM-1", name="Product for Rem", type=ProductType.finished_good, unit="pcs")
    session.add_all([spg, product])
    await session.commit()

    # 3. Prepare Excel
    headers = ["Артикул / SKU", "Количество", "Выполненные стадии"]
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
    # 1. Setup user (id=1)
    from sqlalchemy import text
    await session.execute(text(
        "INSERT INTO users (id, email, password_hash, full_name, role, is_active) "
        "OVERRIDING SYSTEM VALUE "
        "VALUES (1, 'system@local', '', 'System User', 'admin', true)"
    ))
    await session.flush()

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
async def test_import_defects_errors(client, session) -> None:
    # 1. Setup user (id=1)
    from sqlalchemy import text
    await session.execute(text(
        "INSERT INTO users (id, email, password_hash, full_name, role, is_active) "
        "OVERRIDING SYSTEM VALUE "
        "VALUES (1, 'system@local', '', 'System User', 'admin', true)"
    ))
    await session.flush()

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
