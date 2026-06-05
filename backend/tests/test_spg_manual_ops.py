"""Tests for SPG manual stock operations and remainder history endpoint."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.movement import Movement, MovementType
from app.models.product import Product, ProductType
from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.user import User, UserRole
from app.models.spg_remainder import SpgRemainder


async def _make_admin(session, email: str = "admin-spg@test.local") -> User:
    user = User(
        email=email,
        password_hash="x",
        full_name="SPG Admin",
        role=UserRole.admin,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_product(session, sku: str = "FG-MANUAL") -> Product:
    product = Product(
        sku=sku,
        name=f"Product {sku}",
        type=ProductType.finished_good,
        unit="pcs",
    )
    session.add(product)
    await session.flush()
    return product


async def _make_spg_with_sections(session, code: str, *section_codes: str) -> tuple[StorageProductionGroup, list[Section]]:
    spg = StorageProductionGroup(code=code, name=f"SPG {code}")
    session.add(spg)
    await session.flush()
    sections: list[Section] = []
    for idx, sec_code in enumerate(section_codes):
        sec = Section(code=sec_code, name=f"Section {sec_code}", sort_order=idx)
        session.add(sec)
        await session.flush()
        session.add(SpgSection(spg_id=spg.id, section_id=sec.id, sort_order=idx * 10))
        sections.append(sec)
    await session.flush()
    return spg, sections


async def test_manual_operation_in_creates_remainder(client, session):
    await _make_admin(session, "spg-in@test.local")
    product = await _make_product(session, sku="FG-IN")
    spg, sections = await _make_spg_with_sections(session, "SPG-IN", "SEC-IN-A", "SEC-IN-B")
    sec_id = sections[0].id

    resp = await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={
            "product_id": product.id,
            "section_id": sec_id,
            "operation_type": "in",
            "quantity": 50,
            "reason": "инвентаризация",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["operation_type"] == "in"
    assert body["quantity"] == 50
    assert body["new_remainder_quantity"] == 50
    assert body["remainder_id"] is not None

    # Verify a manual remainder was created.
    remainder = (await session.execute(
        select(SpgRemainder).where(SpgRemainder.id == body["remainder_id"])
    )).scalar_one()
    assert remainder.source == "manual"
    assert remainder.spg_id == spg.id
    assert remainder.remainder_quantity == Decimal("50")

    # Verify a movement was logged.
    movement = (await session.execute(
        select(Movement).where(Movement.id == body["movement_id"])
    )).scalar_one()
    assert movement.movement_type == MovementType.manual_in
    assert movement.quantity == Decimal("50")
    assert movement.reason == "инвентаризация"


async def test_manual_operation_out_creates_negative_remainder(client, session):
    await _make_admin(session, "spg-out@test.local")
    product = await _make_product(session, sku="FG-OUT")
    spg, sections = await _make_spg_with_sections(session, "SPG-OUT", "SEC-OUT")
    sec_id = sections[0].id

    # Issue more than available — should go negative.
    resp = await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={
            "product_id": product.id,
            "section_id": sec_id,
            "operation_type": "out",
            "quantity": 10,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["operation_type"] == "out"
    assert body["new_remainder_quantity"] == -10

    # The remainder should now be negative.
    remainder = (await session.execute(
        select(SpgRemainder).where(SpgRemainder.id == body["remainder_id"])
    )).scalar_one()
    assert remainder.remainder_quantity == Decimal("-10")


async def test_manual_operation_in_then_out_balances(client, session):
    await _make_admin(session, "spg-bal@test.local")
    product = await _make_product(session, sku="FG-BAL")
    spg, sections = await _make_spg_with_sections(session, "SPG-BAL", "SEC-BAL")
    sec_id = sections[0].id

    in_resp = await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": product.id, "section_id": sec_id, "operation_type": "in", "quantity": 100},
    )
    assert in_resp.status_code == 200
    assert in_resp.json()["new_remainder_quantity"] == 100

    out_resp = await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": product.id, "section_id": sec_id, "operation_type": "out", "quantity": 30},
    )
    assert out_resp.status_code == 200
    assert out_resp.json()["new_remainder_quantity"] == 70

    # Both share the same manual remainder.
    assert in_resp.json()["remainder_id"] == out_resp.json()["remainder_id"]


async def test_manual_operation_rejects_invalid_type(client, session):
    await _make_admin(session, "spg-inv@test.local")
    product = await _make_product(session, sku="FG-INV")
    spg, sections = await _make_spg_with_sections(session, "SPG-INV", "SEC-INV")
    resp = await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": product.id, "section_id": sections[0].id, "operation_type": "sideways", "quantity": 1},
    )
    assert resp.status_code == 400


async def test_manual_operation_rejects_section_outside_spg(client, session):
    await _make_admin(session, "spg-xspg@test.local")
    product = await _make_product(session, sku="FG-XSPG")
    spg_a, _ = await _make_spg_with_sections(session, "SPG-A", "SEC-A1")
    # Section belonging to a different SPG.
    other_spg, other_sections = await _make_spg_with_sections(session, "SPG-B", "SEC-OTHER")

    resp = await client.post(
        f"/api/spg/{spg_a.id}/manual-operation",
        json={
            "product_id": product.id,
            "section_id": other_sections[0].id,
            "operation_type": "in",
            "quantity": 1,
        },
    )
    assert resp.status_code == 400


async def test_remainder_history_returns_origin_and_movements(client, session):
    await _make_admin(session, "spg-hist@test.local")
    product = await _make_product(session, sku="FG-HIST")
    spg, sections = await _make_spg_with_sections(session, "SPG-HIST", "SEC-H")
    sec_id = sections[0].id

    in_resp = await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": product.id, "section_id": sec_id, "operation_type": "in", "quantity": 25},
    )
    assert in_resp.status_code == 200
    rid = in_resp.json()["remainder_id"]

    out_resp = await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": product.id, "section_id": sec_id, "operation_type": "out", "quantity": 5},
    )
    assert out_resp.status_code == 200

    hist = await client.get(f"/api/spg/{spg.id}/remainders/{rid}/history")
    assert hist.status_code == 200, hist.text
    body = hist.json()

    assert body["remainder"]["id"] == rid
    assert body["remainder"]["remainder_quantity"] == 20
    assert body["remainder"]["product_sku"] == "FG-HIST"

    # Manual operation should not have an origin task.
    assert body["origin"] is None
    assert body["route"] is None

    # Movements should contain at least our two manual ops.
    types = [m["movement_type"] for m in body["movements"]]
    assert "manual_in" in types
    assert "manual_out" in types


async def test_list_remainders_includes_negative(client, session):
    await _make_admin(session, "spg-list@test.local")
    product = await _make_product(session, sku="FG-NEG")
    spg, sections = await _make_spg_with_sections(session, "SPG-NEG", "SEC-NEG")
    sec_id = sections[0].id

    await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": product.id, "section_id": sec_id, "operation_type": "out", "quantity": 3},
    )

    resp = await client.get(f"/api/spg/{spg.id}/remainders")
    assert resp.status_code == 200
    items = resp.json()
    # One remainder with negative quantity.
    matched = [r for r in items if r["product_id"] == product.id]
    assert matched
    assert matched[0]["remainder_quantity"] == -3
