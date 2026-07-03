"""Тесты POST /api/api/v2/stock/adjustment.

Проверяют:
- Создание StockTransaction при manual_in / manual_out
- Обновление баланса (приход / расход)
- Валидацию reason (неверный → 422)
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, ProductType, Section, User, UserRole
from app.stock.models import QualityState, Reason, StockBalance, StockTransaction

pytestmark = pytest.mark.asyncio


async def _make_product(session: AsyncSession, sku: str = "ADJ-PROD") -> Product:
    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()
    return product


async def _make_location(session: AsyncSession, code: str = "STOCK-1") -> Section:
    section = Section(
        code=code, name=code, kind="raw_stock", type="raw_stock", is_active=True, sort_order=0,
    )
    session.add(section)
    await session.flush()
    return section


async def test_adjustment_in_creates_stock_tx(client: AsyncClient, session: AsyncSession) -> None:
    """POST /adjustment с reason=manual_in → 201, StockTransaction создан, баланс вырос."""
    product = await _make_product(session)
    location = await _make_location(session)
    await session.commit()

    payload = {
        "product_id": product.id,
        "location_id": location.id,
        "quantity": 10.0,
        "reason": "manual_in",
        "quality_state": "good",
        "comment": "тестовый приход",
    }
    resp = await client.post("/api/v2/stock/adjustment", json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["reason"] == "manual_in"
    assert float(body["quantity"]) == 10.0

    # Проверяем что транзакция создана
    txs = (await session.execute(select(StockTransaction))).scalars().all()
    assert len(txs) == 1
    tx = txs[0]
    assert tx.product_id == product.id
    assert tx.to_location_id == location.id
    assert tx.from_location_id is None
    assert tx.reason == Reason.MANUAL_IN
    assert float(tx.quantity) == 10.0

    # Баланс должен быть 10
    balance = (await session.execute(select(StockBalance))).scalar_one_or_none()
    assert balance is not None
    assert float(balance.balance_qty) == 10.0
    assert balance.location_id == location.id


async def test_adjustment_out_creates_stock_tx(client: AsyncClient, session: AsyncSession) -> None:
    """POST /adjustment с reason=manual_out → 201, StockTransaction создан, баланс уменьшен."""
    product = await _make_product(session)
    location = await _make_location(session)

    # Сначала создаём приход, чтобы был баланс
    product2 = await _make_product(session, "ADJ-PROD2")

    payload_in = {
        "product_id": product.id,
        "location_id": location.id,
        "quantity": 100.0,
        "reason": "manual_in",
        "quality_state": "good",
    }
    resp_in = await client.post("/api/v2/stock/adjustment", json=payload_in)
    assert resp_in.status_code == 201

    # Расход
    payload_out = {
        "product_id": product.id,
        "location_id": location.id,
        "quantity": 30.0,
        "reason": "manual_out",
        "quality_state": "good",
    }
    resp_out = await client.post("/api/v2/stock/adjustment", json=payload_out)
    assert resp_out.status_code == 201, resp_out.text
    body = resp_out.json()
    assert body["reason"] == "manual_out"
    assert float(body["quantity"]) == 30.0

    # Транзакций должно быть 2 (приход + расход)
    txs = (await session.execute(select(StockTransaction))).scalars().all()
    assert len(txs) == 2

    # Баланс = 100 - 30 = 70
    balance = (await session.execute(
        select(StockBalance).where(StockBalance.product_id == product.id)
    )).scalar_one_or_none()
    assert balance is not None
    assert float(balance.balance_qty) == 70.0


async def test_adjustment_validates_reason(client: AsyncClient, session: AsyncSession) -> None:
    """POST /adjustment с невалидным reason → 422."""
    product = await _make_product(session)
    location = await _make_location(session)
    await session.commit()

    payload = {
        "product_id": product.id,
        "location_id": location.id,
        "quantity": 5.0,
        "reason": "complete",  # недопустимый reason для adjustment
    }
    resp = await client.post("/api/v2/stock/adjustment", json=payload)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "reason" in detail.lower() or "complete" in detail
