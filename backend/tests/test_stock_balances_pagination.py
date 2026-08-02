"""Pagination, total and search for GET /api/stock/balance."""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models import Product, ProductType, Section, User, UserRole
from app.stock import QualityState, Reason, StockCommand, StockCommandService


async def _make_user(session: AsyncSession) -> User:
    user = User(
        username="bal-page-tester",
        email="bal-page-tester@local",
        full_name="Bal Page Tester",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_product(session: AsyncSession, sku: str) -> Product:
    product = Product(
        sku=sku,
        name=sku,
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
    )
    session.add(product)
    await session.flush()
    return product


async def _make_location(session: AsyncSession, *, code: str, name: str) -> Section:
    section = Section(
        code=code,
        name=name,
        type="raw_stock",
        is_active=True,
        sort_order=0,
    )
    session.add(section)
    await session.flush()
    return section


async def _seed_balances(
    session: AsyncSession,
    *,
    location_id: int,
    user_id: int,
    count: int,
    sku_prefix: str = "BAL-PAGE",
) -> list[Product]:
    svc = StockCommandService()
    products: list[Product] = []
    for i in range(count):
        product = await _make_product(session, sku=f"{sku_prefix}-{i:03d}")
        products.append(product)
        await svc.record(session, StockCommand(
            product_id=product.id,
            to_location_id=location_id,
            quantity=Decimal("10"),
            reason=Reason.MANUAL_IN,
            created_by=user_id,
        ))
    await session.commit()
    return products


@pytest.mark.asyncio
async def test_balances_default_limit_returns_total(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    location = await _make_location(session, code="BAL-LOC-1", name="Balance Alpha")
    await _seed_balances(
        session,
        location_id=location.id,
        user_id=user.id,
        count=65,
    )

    resp = await client.get(f"/api/stock/balance?location_id={location.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["balances"]) == 50
    assert body["total"] == 65
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.asyncio
async def test_balances_offset_pagination(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    location = await _make_location(session, code="BAL-LOC-2", name="Balance Beta")
    await _seed_balances(
        session,
        location_id=location.id,
        user_id=user.id,
        count=75,
    )

    first = await client.get(
        f"/api/stock/balance?location_id={location.id}&limit=50&offset=0",
    )
    second = await client.get(
        f"/api/stock/balance?location_id={location.id}&limit=50&offset=50",
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    first_ids = {row["id"] for row in first.json()["balances"]}
    second_ids = {row["id"] for row in second.json()["balances"]}
    assert len(first_ids) == 50
    assert len(second_ids) == 25
    assert first_ids.isdisjoint(second_ids)
    assert first.json()["total"] == 75
    assert second.json()["total"] == 75


@pytest.mark.asyncio
async def test_balances_search_finds_record_on_second_page(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    location = await _make_location(session, code="BAL-LOC-3", name="Balance Gamma")
    await _seed_balances(
        session,
        location_id=location.id,
        user_id=user.id,
        count=60,
        sku_prefix="ORDINARY",
    )
    marker_product = await _make_product(session, sku="UNIQUE-BAL-MARKER-42")
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=marker_product.id,
        to_location_id=location.id,
        quantity=Decimal("5"),
        reason=Reason.MANUAL_IN,
        created_by=user.id,
    ))
    await session.commit()

    resp = await client.get(
        f"/api/stock/balance?location_id={location.id}"
        f"&search=UNIQUE-BAL-MARKER-42&limit=50&offset=0",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["balances"]) == 1
    assert body["balances"][0]["product_sku"] == "UNIQUE-BAL-MARKER-42"


@pytest.mark.asyncio
async def test_balances_limit_max_validation(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    resp = await client.get("/api/stock/balance?limit=1000")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_balances_sort_by_quantity(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    location = await _make_location(session, code="BAL-SORT-LOC", name="Sort Balance")
    product_low = await _make_product(session, sku="BAL-SORT-LOW")
    product_high = await _make_product(session, sku="BAL-SORT-HIGH")
    product_mid = await _make_product(session, sku="BAL-SORT-MID")
    svc = StockCommandService()
    for product, qty in (
        (product_low, Decimal("3")),
        (product_high, Decimal("30")),
        (product_mid, Decimal("7")),
    ):
        await svc.record(session, StockCommand(
            product_id=product.id,
            to_location_id=location.id,
            quantity=qty,
            reason=Reason.MANUAL_IN,
            created_by=user.id,
        ))
    await session.commit()

    resp = await client.get(
        f"/api/stock/balance?location_id={location.id}"
        f"&sort_by=quantity&sort_order=asc&limit=50",
    )
    assert resp.status_code == 200, resp.text
    quantities = [Decimal(row["balance_qty"]) for row in resp.json()["balances"]]
    assert quantities == sorted(quantities)


@pytest.mark.asyncio
async def test_balances_filter_quality_state(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    product = await _make_product(session, sku="BAL-FILTER-QS")
    location = await _make_location(session, code="BAL-FILTER-LOC", name="Filter Balance")
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product.id,
        to_location_id=location.id,
        quantity=Decimal("10"),
        reason=Reason.MANUAL_IN,
        quality_state=QualityState.GOOD,
        created_by=user.id,
    ))
    await svc.record(session, StockCommand(
        product_id=product.id,
        to_location_id=location.id,
        quantity=Decimal("4"),
        reason=Reason.MANUAL_IN,
        quality_state=QualityState.SCRAP,
        created_by=user.id,
    ))
    await session.commit()

    resp = await client.get(
        f"/api/stock/balance?location_id={location.id}"
        f"&quality_state=scrap&limit=50&offset=0",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["balances"]) == 1
    assert body["balances"][0]["quality_state"] == "scrap"


@pytest.mark.asyncio
async def test_balances_location_ids_filter(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    loc_a = await _make_location(session, code="BAL-MULTI-A", name="Multi A")
    loc_b = await _make_location(session, code="BAL-MULTI-B", name="Multi B")
    loc_c = await _make_location(session, code="BAL-MULTI-C", name="Multi C")
    product_a = await _make_product(session, sku="BAL-MULTI-A-SKU")
    product_b = await _make_product(session, sku="BAL-MULTI-B-SKU")
    product_c = await _make_product(session, sku="BAL-MULTI-C-SKU")
    svc = StockCommandService()
    for product, location in (
        (product_a, loc_a),
        (product_b, loc_b),
        (product_c, loc_c),
    ):
        await svc.record(session, StockCommand(
            product_id=product.id,
            to_location_id=location.id,
            quantity=Decimal("1"),
            reason=Reason.MANUAL_IN,
            created_by=user.id,
        ))
    await session.commit()

    resp = await client.get(
        f"/api/stock/balance?location_ids={loc_a.id}&location_ids={loc_b.id}&limit=50",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    location_ids = {row["location_id"] for row in body["balances"]}
    assert location_ids == {loc_a.id, loc_b.id}