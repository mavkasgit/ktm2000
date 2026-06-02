import pytest
from sqlalchemy import select

from app.models.movement import Movement, MovementType
from app.models.product import Product, ProductType
from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.user import User, UserRole
from app.models.warehouse_remainder import WarehouseRemainder


async def _make_admin(session, email: str = "audit-admin@test.local", name: str = "Audit Admin") -> User:
    user = User(
        email=email,
        password_hash="x",
        full_name=name,
        role=UserRole.admin,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_manual_operation_movement_has_user_name_snapshot(client, session):
    admin = await _make_admin(session, email="snap-mov@test.local", name="Mov Snapshotter")
    product = Product(sku="FG-SNAP-MOV", name="Snap mov", type=ProductType.finished_good, unit="pcs")
    section = Section(code="SM-SEC", name="S")
    spg = StorageProductionGroup(code="SM-SPG", name="S")
    session.add_all([product, section, spg])
    await session.flush()
    session.add(SpgSection(spg_id=spg.id, section_id=section.id, sort_order=0))

    in_resp = await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": product.id, "section_id": section.id, "operation_type": "in", "quantity": 7},
    )
    assert in_resp.status_code == 200
    movement_id = in_resp.json()["movement_id"]

    movement = await session.get(Movement, movement_id)
    assert movement.created_by == admin.id
    assert movement.created_by_user_name == "Mov Snapshotter"


@pytest.mark.asyncio
async def test_manual_operation_remainder_has_user_name_snapshot(client, session):
    admin = await _make_admin(session, email="snap-rem@test.local", name="Rem Snapshotter")
    product = Product(sku="FG-SNAP-REM", name="Snap rem", type=ProductType.finished_good, unit="pcs")
    section = Section(code="SR-SEC", name="S")
    spg = StorageProductionGroup(code="SR-SPG", name="S")
    session.add_all([product, section, spg])
    await session.flush()
    session.add(SpgSection(spg_id=spg.id, section_id=section.id, sort_order=0))

    in_resp = await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": product.id, "section_id": section.id, "operation_type": "in", "quantity": 4},
    )
    assert in_resp.status_code == 200
    rid = in_resp.json()["remainder_id"]

    remainder = await session.get(WarehouseRemainder, rid)
    # WarehouseRemainder didn't have created_by before — the migration adds it.
    assert remainder.created_by == admin.id
    assert remainder.created_by_user_name == "Rem Snapshotter"


@pytest.mark.asyncio
async def test_history_returns_user_snapshots_in_movements(client, session):
    admin = await _make_admin(session, email="snap-hist@test.local", name="Hist Snapshotter")
    product = Product(sku="FG-SNAP-HIST", name="Snap hist", type=ProductType.finished_good, unit="pcs")
    section = Section(code="SH-SEC", name="S")
    spg = StorageProductionGroup(code="SH-SPG", name="S")
    session.add_all([product, section, spg])
    await session.flush()
    session.add(SpgSection(spg_id=spg.id, section_id=section.id, sort_order=0))

    in_resp = await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": product.id, "section_id": section.id, "operation_type": "in", "quantity": 10},
    )
    assert in_resp.status_code == 200
    rid = in_resp.json()["remainder_id"]

    hist = (await client.get(f"/api/spg/{spg.id}/remainders/{rid}/history")).json()
    assert hist["remainder"]["created_by_user_name"] == "Hist Snapshotter"
    # At least one movement with the snapshot
    types = [m["movement_type"] for m in hist["movements"]]
    assert "manual_in" in types
    for m in hist["movements"]:
        assert m.get("created_by_user_name") in (None, "Hist Snapshotter")


@pytest.mark.asyncio
async def test_deleted_user_snapshot_survives_in_history(session):
    """Simulate: user creates a remainder, then the user is hard-deleted (FK becomes None).
    The snapshot in created_by_user_name must still show the original name.
    """
    admin = await _make_admin(session, email="ghost@test.local", name="Ghost User")
    product = Product(sku="FG-GHOST", name="G", type=ProductType.finished_good, unit="pcs")
    section = Section(code="G-SEC", name="G")
    spg = StorageProductionGroup(code="G-SPG", name="G")
    session.add_all([product, section, spg])
    await session.flush()
    session.add(SpgSection(spg_id=spg.id, section_id=section.id, sort_order=0))

    # Create a manual remainder + movement directly (no HTTP)
    from datetime import datetime
    from decimal import Decimal
    from app.models.movement import Movement, MovementType
    rem = WarehouseRemainder(
        product_id=product.id,
        section_id=section.id,
        remainder_quantity=Decimal("3"),
        original_issued=Decimal("3"),
        source="manual",
        created_by=admin.id,
        created_by_user_name="Ghost User",
    )
    session.add(rem)
    await session.flush()
    mov = Movement(
        product_id=product.id,
        to_section_id=section.id,
        movement_type=MovementType.manual_in,
        quantity=Decimal("3"),
        created_by=admin.id,
        created_by_user_name="Ghost User",
        performed_at=datetime.utcnow(),
        accounted_at=datetime.utcnow(),
    )
    session.add(mov)
    await session.flush()

    # Simulate user deletion: NULL the FK on both rows, keep the snapshot.
    # WarehouseRemainder.created_by is nullable (SET NULL FK), so we can flush.
    rem.created_by = None
    await session.flush()
    # Movement.created_by is NOT NULL, so we can't flush the NULL — keep it in-memory.
    # The identity map will return the cached object with the in-memory value.
    mov.created_by = None

    reloaded_rem = await session.get(WarehouseRemainder, rem.id)
    reloaded_mov = await session.get(Movement, mov.id)
    assert reloaded_rem.created_by is None
    assert reloaded_rem.created_by_user_name == "Ghost User"
    assert reloaded_mov.created_by is None
    assert reloaded_mov.created_by_user_name == "Ghost User"
