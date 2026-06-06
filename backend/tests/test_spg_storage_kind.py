import pytest
from sqlalchemy import select

from app.models.spg import SpgSection, SpgStorageKind, StorageProductionGroup
from app.models.product import Product, ProductType
from app.models.section import Section
from app.models.user import User, UserRole


@pytest.mark.asyncio
async def test_spg_default_storage_kind_is_wip(session):
    spg = StorageProductionGroup(code="DEF-KIND", name="Default kind")
    session.add(spg)
    await session.flush()
    assert spg.storage_kind == SpgStorageKind.wip
    assert spg.requires_lot is False


@pytest.mark.asyncio
async def test_spg_storage_kind_round_trip(session):
    spg = StorageProductionGroup(
        code="RT-KIND",
        name="Round-trip",
        storage_kind=SpgStorageKind.quarantine,
        requires_lot=True,
    )
    session.add(spg)
    await session.flush()
    reloaded = await session.get(StorageProductionGroup, spg.id)
    assert reloaded.storage_kind == SpgStorageKind.quarantine
    assert reloaded.requires_lot is True



async def _make_admin(session, email: str = "lot-admin@test.local") -> User:
    user = User(email=email, password_hash="x", full_name="Lot Admin", role=UserRole.admin, is_active=True)
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_spg_with_requires_lot_blocks_negative_remainder(client, session):
    await _make_admin(session)
    product = Product(sku="FG-LOT", name="Lot Product", type=ProductType.finished_good, unit="pcs")
    section = Section(code="LOT-SEC", name="Lot section")
    spg = StorageProductionGroup(code="LOT-SPG", name="Lot SPG", requires_lot=True, storage_kind=SpgStorageKind.quarantine)
    session.add_all([product, section, spg])
    await session.flush()
    session.add(SpgSection(spg_id=spg.id, section_id=section.id, sort_order=0))

    # First in creates a remainder
    in_resp = await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": product.id, "section_id": section.id, "operation_type": "in", "quantity": 5},
    )
    assert in_resp.status_code == 200

    # Trying to take out more than available must be rejected
    out_resp = await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": product.id, "section_id": section.id, "operation_type": "out", "quantity": 7},
    )
    assert out_resp.status_code == 400
    assert "lot" in out_resp.json()["detail"].lower()
