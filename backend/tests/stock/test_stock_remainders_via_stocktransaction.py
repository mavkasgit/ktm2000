"""Тесты для отображения и подсчёта остатков через StockTransaction/StockBalance.

Заменяют удалённые legacy тесты на SpgRemainder.
Проверяют что StockCommandService.record() корректно обновляет StockBalance.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, ProductType, Section, User, UserRole
from app.stock import (
    QualityState,
    Reason,
    StockBalance,
    StockCommand,
    StockCommandService,
    StockTransaction,
)
from tests.test_integrity_invariants import assert_no_stock_ledger_invariants_violations


# ─── helpers ────────────────────────────────────────────────────────────────


async def _make_user(session: AsyncSession) -> User:
    user = User(
        username="rem-tester",
        email="rem-tester@local",
        password_hash="x",
        full_name="Remainder Tester",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_product(session: AsyncSession, sku: str = "REM-PROD") -> Product:
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


async def _make_location(
    session: AsyncSession,
    *,
    code: str,
    name: str,
    loc_type: str,
) -> Section:
    section = Section(
        code=code,
        name=name,
        type=loc_type,
        is_active=True,
        sort_order=0,
    )
    session.add(section)
    await session.flush()
    return section


async def _balance(
    session: AsyncSession,
    product_id: int,
    location_id: int,
    quality_state: QualityState = QualityState.GOOD,
) -> Decimal:
    row = await session.execute(
        select(StockBalance).where(
            StockBalance.product_id == product_id,
            StockBalance.location_id == location_id,
            StockBalance.quality_state == quality_state,
        )
    )
    bal = row.scalar_one_or_none()
    return bal.balance_qty if bal else Decimal("0")


# ─── tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stock_balance_reflects_manual_in_transaction(session: AsyncSession):
    """Одиночная MANUAL_IN транзакция создаёт корректную строку StockBalance."""
    user = await _make_user(session)
    product = await _make_product(session)
    location = await _make_location(
        session, code="RAW-REM-1", name="Raw Remainder 1", loc_type="raw_stock"
    )

    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product.id,
        to_location_id=location.id,
        quantity=Decimal("100"),
        reason=Reason.MANUAL_IN,
        created_by=user.id,
    ))
    await session.commit()

    bal = await _balance(session, product.id, location.id)
    assert bal == Decimal("100"), f"Expected 100, got {bal}"

    await assert_no_stock_ledger_invariants_violations(
        session, context="after-manual-in"
    )


@pytest.mark.asyncio
async def test_stock_balance_aggregates_multiple_transactions(session: AsyncSession):
    """StockBalance суммирует MANUAL_IN и вычитает MANUAL_OUT."""
    user = await _make_user(session)
    product = await _make_product(session, sku="REM-AGG")
    location = await _make_location(
        session, code="RAW-REM-2", name="Raw Remainder 2", loc_type="raw_stock"
    )

    svc = StockCommandService()
    # MANUAL_IN 50
    await svc.record(session, StockCommand(
        product_id=product.id,
        to_location_id=location.id,
        quantity=Decimal("50"),
        reason=Reason.MANUAL_IN,
        created_by=user.id,
    ))
    # MANUAL_IN 30
    await svc.record(session, StockCommand(
        product_id=product.id,
        to_location_id=location.id,
        quantity=Decimal("30"),
        reason=Reason.MANUAL_IN,
        created_by=user.id,
    ))
    # MANUAL_OUT 20
    await svc.record(session, StockCommand(
        product_id=product.id,
        from_location_id=location.id,
        quantity=Decimal("20"),
        reason=Reason.MANUAL_OUT,
        created_by=user.id,
    ))
    await session.commit()

    bal = await _balance(session, product.id, location.id)
    assert bal == Decimal("60"), f"Expected 60, got {bal}"

    await assert_no_stock_ledger_invariants_violations(
        session, context="after-multi-tx"
    )


@pytest.mark.asyncio
async def test_stock_balance_quality_state_filtering(session: AsyncSession):
    """StockBalance разделяет GOOD и SCRAP по разным ключам."""
    user = await _make_user(session)
    product = await _make_product(session, sku="REM-QS")
    location = await _make_location(
        session, code="PROD-REM", name="Production", loc_type="production"
    )
    scrap_location = await _make_location(
        session, code="SCRAP-REM", name="Scrap Yard", loc_type="scrap"
    )

    svc = StockCommandService()

    # MANUAL_IN 100 GOOD на участок
    await svc.record(session, StockCommand(
        product_id=product.id,
        to_location_id=location.id,
        quantity=Decimal("100"),
        reason=Reason.MANUAL_IN,
        created_by=user.id,
    ))

    # SCRAP 30 с участка на склад брака
    await svc.record(session, StockCommand(
        product_id=product.id,
        from_location_id=location.id,
        to_location_id=scrap_location.id,
        quantity=Decimal("30"),
        reason=Reason.SCRAP,
        quality_state=QualityState.GOOD,
        to_quality_state=QualityState.SCRAP,
        created_by=user.id,
    ))
    await session.commit()

    good_bal = await _balance(session, product.id, location.id, QualityState.GOOD)
    assert good_bal == Decimal("70"), f"Expected 70 GOOD, got {good_bal}"

    scrap_bal = await _balance(
        session, product.id, scrap_location.id, QualityState.SCRAP
    )
    assert scrap_bal == Decimal("30"), f"Expected 30 SCRAP, got {scrap_bal}"

    await assert_no_stock_ledger_invariants_violations(
        session, context="after-quality-state"
    )


@pytest.mark.asyncio
async def test_list_stock_balances_endpoint_returns_correct_data(client, session: AsyncSession):
    """GET /api/v2/stock/balance возвращает корректные балансы после создания транзакций."""
    from app.core.security import create_access_token

    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    product = await _make_product(session, sku="REM-API")
    location = await _make_location(
        session, code="RAW-API-1", name="Raw API", loc_type="raw_stock"
    )

    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product.id,
        to_location_id=location.id,
        quantity=Decimal("75"),
        reason=Reason.MANUAL_IN,
        created_by=user.id,
    ))
    await session.commit()

    resp = await client.get("/api/v2/stock/balance")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Находим нашу запись баланса в ответе
    our_balance = [b for b in data if b["product_id"] == product.id]
    assert len(our_balance) == 1, f"Expected 1 balance row, got {len(our_balance)}"
    assert our_balance[0]["balance_qty"] == "75.000"
    assert our_balance[0]["location_id"] == location.id
