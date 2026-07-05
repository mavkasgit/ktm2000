"""Pagination, total and search for GET /api/v2/stock/transactions."""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models import Product, ProductType, Section, User, UserRole
from app.stock import Reason, StockCommand, StockCommandService


async def _make_user(session: AsyncSession) -> User:
    user = User(
        username="tx-page-tester",
        email="tx-page-tester@local",
        password_hash="x",
        full_name="Tx Page Tester",
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


async def _seed_transactions(
    session: AsyncSession,
    *,
    product_id: int,
    location_id: int,
    user_id: int,
    count: int,
    comment_prefix: str = "batch",
) -> None:
    svc = StockCommandService()
    for i in range(count):
        await svc.record(session, StockCommand(
            product_id=product_id,
            to_location_id=location_id,
            quantity=Decimal("1"),
            reason=Reason.MANUAL_IN,
            comment=f"{comment_prefix}-{i:03d}",
            created_by=user_id,
        ))
    await session.commit()


@pytest.mark.asyncio
async def test_transactions_default_limit_returns_total(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    product = await _make_product(session, sku="TX-PAGE-1")
    location = await _make_location(session, code="TX-LOC-1", name="Warehouse Alpha")
    await _seed_transactions(
        session,
        product_id=product.id,
        location_id=location.id,
        user_id=user.id,
        count=65,
    )

    resp = await client.get(
        f"/api/v2/stock/transactions?product_id={product.id}",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["transactions"]) == 50
    assert body["total"] == 65
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.asyncio
async def test_transactions_offset_pagination(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    product = await _make_product(session, sku="TX-PAGE-2")
    location = await _make_location(session, code="TX-LOC-2", name="Warehouse Beta")
    await _seed_transactions(
        session,
        product_id=product.id,
        location_id=location.id,
        user_id=user.id,
        count=75,
    )

    first = await client.get(
        f"/api/v2/stock/transactions?product_id={product.id}&limit=50&offset=0",
    )
    second = await client.get(
        f"/api/v2/stock/transactions?product_id={product.id}&limit=50&offset=50",
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    first_ids = {tx["id"] for tx in first.json()["transactions"]}
    second_ids = {tx["id"] for tx in second.json()["transactions"]}
    assert len(first_ids) == 50
    assert len(second_ids) == 25
    assert first_ids.isdisjoint(second_ids)
    assert first.json()["total"] == 75
    assert second.json()["total"] == 75


@pytest.mark.asyncio
async def test_transactions_search_finds_record_on_second_page(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    product = await _make_product(session, sku="TX-PAGE-3")
    location = await _make_location(session, code="TX-LOC-3", name="Warehouse Gamma")
    await _seed_transactions(
        session,
        product_id=product.id,
        location_id=location.id,
        user_id=user.id,
        count=60,
        comment_prefix="ordinary",
    )
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product.id,
        to_location_id=location.id,
        quantity=Decimal("1"),
        reason=Reason.MANUAL_IN,
        comment="UNIQUE-TX-MARKER-42",
        created_by=user.id,
    ))
    await session.commit()

    resp = await client.get(
        f"/api/v2/stock/transactions?product_id={product.id}"
        f"&search=UNIQUE-TX-MARKER-42&limit=50&offset=0",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["transactions"]) == 1
    assert body["transactions"][0]["comment"] == "UNIQUE-TX-MARKER-42"


@pytest.mark.asyncio
async def test_transactions_limit_max_validation(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    resp = await client.get("/api/v2/stock/transactions?limit=1000")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_stock_tx_sort_by_quantity(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    product = await _make_product(session, sku="TX-SORT-QTY")
    location = await _make_location(session, code="TX-SORT-LOC", name="Sort Warehouse")
    svc = StockCommandService()
    for qty, marker in ((Decimal("3"), "low"), (Decimal("30"), "high"), (Decimal("7"), "mid")):
        await svc.record(session, StockCommand(
            product_id=product.id,
            to_location_id=location.id,
            quantity=qty,
            reason=Reason.MANUAL_IN,
            comment=f"qty-{marker}",
            created_by=user.id,
        ))
    await session.commit()

    resp = await client.get(
        f"/api/v2/stock/transactions?product_id={product.id}"
        f"&sort_by=quantity&sort_order=asc&limit=50",
    )
    assert resp.status_code == 200, resp.text
    quantities = [Decimal(tx["quantity"]) for tx in resp.json()["transactions"]]
    assert quantities == sorted(quantities)


@pytest.mark.asyncio
async def test_stock_tx_filter_reason(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    product = await _make_product(session, sku="TX-FILTER-REASON")
    location = await _make_location(session, code="TX-FILTER-LOC", name="Filter Warehouse")
    svc = StockCommandService()

    for i in range(55):
        await svc.record(session, StockCommand(
            product_id=product.id,
            to_location_id=location.id,
            quantity=Decimal("1"),
            reason=Reason.MANUAL_IN,
            comment=f"ordinary-{i:03d}",
            created_by=user.id,
        ))
    await svc.record(session, StockCommand(
        product_id=product.id,
        to_location_id=location.id,
        quantity=Decimal("5"),
        reason=Reason.ADJUSTMENT_IN,
        comment="special-adjustment-marker",
        created_by=user.id,
    ))
    await session.commit()

    resp = await client.get(
        f"/api/v2/stock/transactions?product_id={product.id}"
        f"&reason=adjustment_in&limit=50&offset=0",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["transactions"]) == 1
    assert body["transactions"][0]["reason"] == "adjustment_in"