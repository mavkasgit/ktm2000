import pytest
from app.models.product import Product, ProductType
from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.user import User, UserRole


@pytest.mark.asyncio
async def test_snapshot_reports_negative_remainder_indicator(client, session):
    user = User(email="neg-ind@test.local", password_hash="x", full_name="N", role=UserRole.admin, is_active=True)
    session.add(user)

    product = Product(sku="FG-NEG-IDX", name="Negative indicator", type=ProductType.finished_good, unit="pcs")
    section = Section(code="NEG-SEC", name="NEG section")
    spg = StorageProductionGroup(code="NEG-SPG", name="Negative SPG")
    session.add_all([product, section, spg])
    await session.flush()
    session.add(SpgSection(spg_id=spg.id, section_id=section.id, sort_order=0))

    # Out without prior in → creates a -5 remainder
    out_resp = await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": product.id, "section_id": section.id, "operation_type": "out", "quantity": 5},
    )
    assert out_resp.status_code == 200

    snap = (await client.get(f"/api/spg/{spg.id}/snapshot")).json()
    assert snap["totals"]["spg_available"] == -5
    assert snap["totals"]["negative_total"] == -5
    assert snap["totals"]["negative_remainder_count"] == 1


@pytest.mark.asyncio
async def test_snapshot_row_includes_per_product_negative_count(client, session):
    user = User(email="row-neg@test.local", password_hash="x", full_name="R", role=UserRole.admin, is_active=True)
    session.add(user)

    product_a = Product(sku="FG-A", name="A", type=ProductType.finished_good, unit="pcs")
    product_b = Product(sku="FG-B", name="B", type=ProductType.finished_good, unit="pcs")
    section = Section(code="RN-SEC", name="RN section")
    spg = StorageProductionGroup(code="RN-SPG", name="RN SPG")
    session.add_all([product_a, product_b, section, spg])
    await session.flush()
    session.add(SpgSection(spg_id=spg.id, section_id=section.id, sort_order=0))

    # Product A goes negative (-3)
    await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": product_a.id, "section_id": section.id, "operation_type": "out", "quantity": 3},
    )
    # Product B has a +1 remainder (zero negatives)
    await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": product_b.id, "section_id": section.id, "operation_type": "in", "quantity": 1},
    )
    snap = (await client.get(f"/api/spg/{spg.id}/snapshot")).json()
    by_sku = {r["sku"]: r for r in snap["rows"]}
    assert by_sku["FG-A"]["negative_remainder_count"] == 1
    assert by_sku["FG-B"]["negative_remainder_count"] == 0
