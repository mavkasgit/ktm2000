import pytest
from app.models.product import Product, ProductType
from app.models.section import Section
from app.models.spg import SpgSection, SpgStorageKind, StorageProductionGroup
from app.models.user import User, UserRole


@pytest.mark.asyncio
async def test_availability_returns_sum_and_requires_lot(client, session):
    user = User(email="avail@test.local", password_hash="x", full_name="A", role=UserRole.admin, is_active=True)
    session.add(user)

    product = Product(sku="FG-AVAIL", name="A", type=ProductType.finished_good, unit="pcs")
    section = Section(code="AVAIL-SEC", name="A section")
    spg = StorageProductionGroup(
        code="AVAIL-SPG",
        name="A SPG",
        requires_lot=True,
        storage_kind=SpgStorageKind.quarantine,
    )
    session.add_all([product, section, spg])
    await session.flush()
    session.add(SpgSection(spg_id=spg.id, section_id=section.id, sort_order=0))

    # Two remainders: +5 and +3 → available = 8
    await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": product.id, "section_id": section.id, "operation_type": "in", "quantity": 5},
    )
    await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": product.id, "section_id": section.id, "operation_type": "in", "quantity": 3},
    )

    resp = await client.get(
        f"/api/spg/{spg.id}/availability",
        params={"product_id": product.id, "section_id": section.id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] == 8.0
    assert body["requires_lot"] is True
    assert body["spg_id"] == spg.id
    assert body["product_id"] == product.id
    assert body["section_id"] == section.id


@pytest.mark.asyncio
async def test_availability_404_when_spg_missing(client, session):
    user = User(email="avail-404@test.local", password_hash="x", full_name="A", role=UserRole.admin, is_active=True)
    session.add(user)
    resp = await client.get(
        "/api/spg/99999/availability",
        params={"product_id": 1, "section_id": 1},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_availability_400_when_section_not_in_spg(client, session):
    user = User(email="avail-400@test.local", password_hash="x", full_name="A", role=UserRole.admin, is_active=True)
    session.add(user)

    product = Product(sku="FG-AVAIL-X", name="X", type=ProductType.finished_good, unit="pcs")
    section_a = Section(code="AVAIL-A", name="A")
    section_b = Section(code="AVAIL-B", name="B")
    spg = StorageProductionGroup(code="AVAIL-SPG-X", name="X")
    session.add_all([product, section_a, section_b, spg])
    await session.flush()
    session.add(SpgSection(spg_id=spg.id, section_id=section_a.id, sort_order=0))
    # section_b is in a different SPG

    resp = await client.get(
        f"/api/spg/{spg.id}/availability",
        params={"product_id": product.id, "section_id": section_b.id},
    )
    assert resp.status_code == 400
    assert "does not belong" in resp.json()["detail"].lower()
