"""Терминальная секция (тикет #136): «Отправлено» вне оперативных остатков.

Семантика (гриллинг 2026-09-05): терминальная секция хранит полный след в
ledger, но не участвует в балансах/отчётах остатков — по аналогии с
Customer-локацией Odoo (виртуальная, вне оценки) и движением 601 в SAP.

Покрывают:
- Классификатор: ``terminal`` вне STOCK_TYPES / STORAGE_TYPES,
  предикат ``is_terminal_section``.
- Передача на терминал: 2 проводки в ledger, баланс приёмника не создаётся,
  баланс отправителя корректно уменьшается, инварианты зелёные.
- ``rebuild_all_balances`` пропускает терминал.
- Сиды: SHIPPED имеет тип ``terminal``.
- DB-триггер: transport-операция на терминале допустима.
- Импорт остатков: терминал отклоняется как целевая секция.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, ProductType, Section, User, UserRole
from app.models.route import SectionOperation
from app.seeds.sections import SECTIONS_DATA
from app.services.route_storage_classifier import (
    SECTION_TYPE_TERMINAL,
    STORAGE_TYPES,
    STOCK_TYPES,
    TERMINAL_TYPES,
    is_stock_section,
    is_storage_section,
    is_terminal_section,
)
from app.stock import (
    QualityState,
    Reason,
    StockBalance,
    StockCommand,
    StockCommandService,
    StockProjectionManager,
    StockTransaction,
)
from app.stock.import_service import resolve_target_section
from tests.test_integrity_invariants import assert_no_invariants_violations


# ─── helpers ────────────────────────────────────────────────────────────────


async def _make_user(session: AsyncSession, username: str = "terminal-tester") -> User:
    user = User(
        username=username,
        email=f"{username}@local",
        full_name="Terminal Tester",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_product(session: AsyncSession, sku: str = "TMTL") -> Product:
    product = Product(
        sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True,
    )
    session.add(product)
    await session.flush()
    return product


async def _make_location(
    session: AsyncSession, *, code: str, name: str, loc_type: str,
) -> Section:
    section = Section(
        code=code, name=name, type=loc_type, is_active=True, sort_order=0,
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


# ─── классификатор ──────────────────────────────────────────────────────────


def test_terminal_section_outside_stock_classifiers() -> None:
    """``terminal`` — не оборачиваемый склад и не storage в смысле остатков."""
    assert SECTION_TYPE_TERMINAL == "terminal"
    assert TERMINAL_TYPES == frozenset({"terminal"})
    assert "terminal" not in STOCK_TYPES
    assert "terminal" not in STORAGE_TYPES

    terminal = Section(code="T", name="Т", type="terminal", is_active=True)
    assert is_terminal_section(terminal)
    assert not is_stock_section(terminal)
    # «хранение, а не работа»: маршруты/транспорт как у склада
    assert is_storage_section(terminal)
    assert not is_stock_section(None)
    assert not is_terminal_section(None)


# ─── ledger / проекция ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transfer_to_terminal_writes_ledger_but_no_balance(
    session: AsyncSession,
) -> None:
    """Передача ГП → «Отправлено»: след в ledger полный, баланса приёмника нет."""
    user = await _make_user(session)
    product = await _make_product(session)
    finished = await _make_location(
        session, code="FG", name="Склад ГП", loc_type="finished_stock",
    )
    shipped = await _make_location(
        session, code="SHIPPED-T", name="Отправлено", loc_type="terminal",
    )

    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product.id,
        to_location_id=finished.id,
        quantity=Decimal("10"),
        reason=Reason.MANUAL_IN,
        created_by=user.id,
    ))
    tx_send = await svc.record(session, StockCommand(
        product_id=product.id,
        from_location_id=finished.id,
        to_location_id=shipped.id,
        quantity=Decimal("4"),
        reason=Reason.TRANSFER_SEND,
        created_by=user.id,
    ))

    await session.commit()
    assert tx_send.id is not None
    # Полный след: обе проводки на месте.
    txs = (await session.execute(
        select(StockTransaction).order_by(StockTransaction.id)
    )).scalars().all()
    assert [t.reason for t in txs] == [Reason.MANUAL_IN, Reason.TRANSFER_SEND]

    # Оперативный остаток: склад ГП уменьшился, у «Отправлено» баланса нет.
    assert (await _balance(session, product.id, finished.id)) == Decimal("6")
    assert (await _balance(session, product.id, shipped.id)) == Decimal("0")
    assert (await session.execute(
        select(StockBalance).where(StockBalance.location_id == shipped.id)
    )).scalar_one_or_none() is None

    await assert_no_invariants_violations(session, context="terminal-transfer")


@pytest.mark.asyncio
async def test_rebuild_all_balances_skips_terminal(session: AsyncSession) -> None:
    """Полный пересчёт из ledger не порождает строк баланса для терминала."""
    user = await _make_user(session)
    product = await _make_product(session)
    finished = await _make_location(
        session, code="FG2", name="Склад ГП 2", loc_type="finished_stock",
    )
    shipped = await _make_location(
        session, code="SHIPPED-T2", name="Отправлено 2", loc_type="terminal",
    )

    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product.id,
        to_location_id=finished.id,
        quantity=Decimal("10"),
        reason=Reason.MANUAL_IN,
        created_by=user.id,
    ))
    await svc.record(session, StockCommand(
        product_id=product.id,
        from_location_id=finished.id,
        to_location_id=shipped.id,
        quantity=Decimal("4"),
        reason=Reason.TRANSFER_SEND,
        created_by=user.id,
    ))
    await session.commit()

    # Форс-мажор: строка баланса терминала всё же появилась (legacy) —
    # rebuild обязан её вымести.
    session.add(StockBalance(
        product_id=product.id,
        location_id=shipped.id,
        quality_state=QualityState.GOOD,
        balance_qty=Decimal("4"),
    ))
    await session.commit()

    pm = StockProjectionManager()
    await pm.rebuild_all_balances(session)
    await session.commit()

    assert (await _balance(session, product.id, finished.id)) == Decimal("6")
    assert (await session.execute(
        select(StockBalance).where(StockBalance.location_id == shipped.id)
    )).scalar_one_or_none() is None


# ─── сиды и триггеры ────────────────────────────────────────────────────────


def test_shipped_seed_is_terminal() -> None:
    """Сид SHIPPED switched to terminal, остальные склады не тронуты."""
    by_code = {row["code"]: row for row in SECTIONS_DATA}
    assert by_code["SHIPPED"]["type"] == "terminal"
    assert by_code["FINISHED_STOCK"]["type"] == "finished_stock"
    assert by_code["SHIPMENT"]["type"] == "finished_stock"


@pytest.mark.asyncio
async def test_transport_operation_allowed_on_terminal(session: AsyncSession) -> None:
    """DB-триггер пропускает transport-операцию на терминальной секции."""
    shipped = await _make_location(
        session, code="SHIPPED-T3", name="Отправлено 3", loc_type="terminal",
    )
    session.add(SectionOperation(
        section_id=shipped.id,
        group_code="SHIPPED",
        group_name="Отправлено",
        sort_order=10,
        operation_code="SENT",
        operation_name="Отправлено",
        is_significant=False,
        operation_type="transport",
    ))
    await session.flush()


# ─── импорт остатков ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_remainder_import_rejects_terminal(session: AsyncSession) -> None:
    """Терминал — не цель импорта остатков: оперативных остатков там нет."""
    shipped = await _make_location(
        session, code="SHIPPED-T4", name="Отправлено 4", loc_type="terminal",
    )
    errors: list[str] = []
    section_id, section_name = await resolve_target_section(
        session, shipped.name, errors,
    )
    assert section_id is None
    assert section_name is None
    assert errors and "terminal" in errors[0]
