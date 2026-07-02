"""Тесты ядра Stock Ledger (Этап 1).

Покрывают:
- Базовую запись ``StockCommandService.record()`` и обновление баланса.
- Идемпотентность по ``idempotency_key``.
- Валидацию команд (quantity, locations, reason↔quality_state).
- Multi-transaction баланс: SUM(in) - SUM(out) по ключу.
- Полный пересчёт ``rebuild_all_balances``.
- Инвариант-проверки ``assert_no_stock_ledger_invariants_violations``.
- QualityState: SCRAP/REWORK как отдельные ключи баланса.
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
    StockProjectionManager,
    StockTransaction,
    StockValidationError,
)
from app.stock.models import LocationType
from tests.test_integrity_invariants import assert_no_stock_ledger_invariants_violations


# ─── helpers ────────────────────────────────────────────────────────────────


async def _make_user(session: AsyncSession, username: str = "stock-tester") -> User:
    user = User(
        username=username,
        email=f"{username}@local",
        password_hash="x",
        full_name="Stock Tester",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_product(session: AsyncSession, sku: str = "FRAME") -> Product:
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
        kind="production" if loc_type in ("laser", "welding", "painting", "assembly") else loc_type,
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
    quality_state: QualityState = QualityState.good,
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


# ─── tests: basic record + balance ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_issue_to_work_moves_balance_from_stock_to_production(session: AsyncSession):
    """RAW_STOCK -100, LASER +100 после ISSUE_TO_WORK."""
    user = await _make_user(session)
    product = await _make_product(session)
    raw = await _make_location(session, code="RAW", name="Raw", loc_type="raw_stock")
    laser = await _make_location(session, code="LASER", name="Laser", loc_type="laser")

    svc = StockCommandService()
    tx = await svc.record(session, StockCommand(
        product_id=product.id,
        from_location_id=raw.id,
        to_location_id=laser.id,
        quantity=Decimal("100"),
        reason=Reason.issue_to_work,
        created_by=user.id,
    ))

    await session.commit()
    assert tx.id is not None
    assert (await _balance(session, product.id, raw.id)) == Decimal("-100")
    assert (await _balance(session, product.id, laser.id)) == Decimal("100")


@pytest.mark.asyncio
async def test_balance_aggregates_multiple_transactions(session: AsyncSession):
    """Несколько транзакций складываются в один баланс по ключу."""
    user = await _make_user(session)
    product = await _make_product(session)
    raw = await _make_location(session, code="RAW2", name="Raw2", loc_type="raw_stock")
    laser = await _make_location(session, code="LASER2", name="Laser2", loc_type="laser")

    svc = StockCommandService()
    for qty in (Decimal("30"), Decimal("50"), Decimal("20")):
        await svc.record(session, StockCommand(
            product_id=product.id,
            from_location_id=raw.id,
            to_location_id=laser.id,
            quantity=qty,
            reason=Reason.issue_to_work,
            created_by=user.id,
        ))
    await session.commit()

    assert (await _balance(session, product.id, raw.id)) == Decimal("-100")
    assert (await _balance(session, product.id, laser.id)) == Decimal("100")


@pytest.mark.asyncio
async def test_return_to_stock_reverses_balance(session: AsyncSession):
    """RETURN_TO_STOCK: production → raw_stock возвращает материал."""
    user = await _make_user(session)
    product = await _make_product(session)
    raw = await _make_location(session, code="RAW3", name="Raw3", loc_type="raw_stock")
    laser = await _make_location(session, code="LASER3", name="Laser3", loc_type="laser")

    svc = StockCommandService()
    # Выдали 100
    await svc.record(session, StockCommand(
        product_id=product.id, from_location_id=raw.id, to_location_id=laser.id,
        quantity=Decimal("100"), reason=Reason.issue_to_work, created_by=user.id,
    ))
    # Вернули 30
    await svc.record(session, StockCommand(
        product_id=product.id, from_location_id=laser.id, to_location_id=raw.id,
        quantity=Decimal("30"), reason=Reason.return_to_stock, created_by=user.id,
    ))
    await session.commit()

    assert (await _balance(session, product.id, raw.id)) == Decimal("-70")
    assert (await _balance(session, product.id, laser.id)) == Decimal("70")


# ─── tests: idempotency ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotency_key_returns_existing_transaction(session: AsyncSession):
    """Повторная запись с тем же idempotency_key не создаёт дубль."""
    user = await _make_user(session)
    product = await _make_product(session)
    raw = await _make_location(session, code="RAW4", name="Raw4", loc_type="raw_stock")
    laser = await _make_location(session, code="LASER4", name="Laser4", loc_type="laser")

    svc = StockCommandService()
    cmd = StockCommand(
        product_id=product.id,
        from_location_id=raw.id,
        to_location_id=laser.id,
        quantity=Decimal("50"),
        reason=Reason.issue_to_work,
        created_by=user.id,
        idempotency_key="op-123",
    )
    tx1 = await svc.record(session, cmd)
    tx2 = await svc.record(session, cmd)
    await session.commit()

    assert tx1.id == tx2.id
    count = await session.execute(
        select(StockTransaction).where(StockTransaction.idempotency_key == "op-123")
    )
    assert len(count.scalars().all()) == 1


# ─── tests: validation ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validation_rejects_zero_quantity(session: AsyncSession):
    user = await _make_user(session)
    product = await _make_product(session)
    raw = await _make_location(session, code="RAW5", name="Raw5", loc_type="raw_stock")
    laser = await _make_location(session, code="LASER5", name="Laser5", loc_type="laser")

    svc = StockCommandService()
    with pytest.raises(StockValidationError, match="quantity"):
        await svc.record(session, StockCommand(
            product_id=product.id, from_location_id=raw.id, to_location_id=laser.id,
            quantity=Decimal("0"), reason=Reason.issue_to_work, created_by=user.id,
        ))


@pytest.mark.asyncio
async def test_validation_rejects_no_locations(session: AsyncSession):
    user = await _make_user(session)
    product = await _make_product(session)

    svc = StockCommandService()
    with pytest.raises(StockValidationError, match="at least one"):
        await svc.record(session, StockCommand(
            product_id=product.id, quantity=Decimal("10"),
            reason=Reason.manual_in, created_by=user.id,
        ))


@pytest.mark.asyncio
async def test_validation_rejects_same_from_to(session: AsyncSession):
    user = await _make_user(session)
    product = await _make_product(session)
    raw = await _make_location(session, code="RAW6", name="Raw6", loc_type="raw_stock")

    svc = StockCommandService()
    with pytest.raises(StockValidationError, match="must differ"):
        await svc.record(session, StockCommand(
            product_id=product.id, from_location_id=raw.id, to_location_id=raw.id,
            quantity=Decimal("10"), reason=Reason.adjustment_in, created_by=user.id,
        ))


@pytest.mark.asyncio
async def test_validation_rejects_scrap_with_wrong_quality_transition(session: AsyncSession):
    """SCRAP требует from_quality=good, to_quality=scrap."""
    user = await _make_user(session)
    product = await _make_product(session)
    laser = await _make_location(session, code="LASER6", name="Laser6", loc_type="laser")
    scrap = await _make_location(session, code="SCRAP1", name="Scrap", loc_type="scrap")

    svc = StockCommandService()
    # to_quality_state=good при reason=scrap — невалидно
    with pytest.raises(StockValidationError, match="reason=scrap"):
        await svc.record(session, StockCommand(
            product_id=product.id, from_location_id=laser.id, to_location_id=scrap.id,
            quantity=Decimal("5"), reason=Reason.scrap,
            quality_state=QualityState.good, to_quality_state=QualityState.good,
            created_by=user.id,
        ))


@pytest.mark.asyncio
async def test_validation_rejects_complete_with_non_good_quality(session: AsyncSession):
    user = await _make_user(session)
    product = await _make_product(session)
    laser = await _make_location(session, code="LASER7", name="Laser7", loc_type="laser")
    wip = await _make_location(session, code="WIP1", name="Wip", loc_type="wip_stock")

    svc = StockCommandService()
    with pytest.raises(StockValidationError, match="to_quality=good"):
        await svc.record(session, StockCommand(
            product_id=product.id, from_location_id=laser.id, to_location_id=wip.id,
            quantity=Decimal("5"), reason=Reason.complete,
            quality_state=QualityState.good, to_quality_state=QualityState.scrap,
            created_by=user.id,
        ))


# ─── tests: quality state ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scrap_creates_separate_balance_key(session: AsyncSession):
    """Брак — отдельный ключ баланса (location=SCRAP, quality=SCRAP)."""
    user = await _make_user(session)
    product = await _make_product(session)
    laser = await _make_location(session, code="LASER8", name="Laser8", loc_type="laser")
    scrap_loc = await _make_location(session, code="SCRAP2", name="Scrap2", loc_type="scrap")

    svc = StockCommandService()
    # 100 good на лазере
    await svc.record(session, StockCommand(
        product_id=product.id, from_location_id=None, to_location_id=laser.id,
        quantity=Decimal("100"), reason=Reason.manual_in, created_by=user.id,
    ))
    # 10 в брак: from_quality=good, to_quality=scrap
    await svc.record(session, StockCommand(
        product_id=product.id, from_location_id=laser.id, to_location_id=scrap_loc.id,
        quantity=Decimal("10"), reason=Reason.scrap,
        quality_state=QualityState.good, to_quality_state=QualityState.scrap,
        created_by=user.id,
    ))
    await session.commit()

    assert (await _balance(session, product.id, laser.id, QualityState.good)) == Decimal("90")
    assert (await _balance(session, product.id, scrap_loc.id, QualityState.scrap)) == Decimal("10")
    # Good на scrap-локации = 0 (нет строки)
    assert (await _balance(session, product.id, scrap_loc.id, QualityState.good)) == Decimal("0")


@pytest.mark.asyncio
async def test_rework_uses_rework_quality_state(session: AsyncSession):
    user = await _make_user(session)
    product = await _make_product(session)
    laser = await _make_location(session, code="LASER9", name="Laser9", loc_type="laser")
    rework_loc = await _make_location(session, code="RW1", name="Rework", loc_type="quarantine")

    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product.id, from_location_id=None, to_location_id=laser.id,
        quantity=Decimal("50"), reason=Reason.manual_in, created_by=user.id,
    ))
    await svc.record(session, StockCommand(
        product_id=product.id, from_location_id=laser.id, to_location_id=rework_loc.id,
        quantity=Decimal("7"), reason=Reason.rework,
        quality_state=QualityState.good, to_quality_state=QualityState.rework,
        created_by=user.id,
    ))
    await session.commit()

    assert (await _balance(session, product.id, laser.id, QualityState.good)) == Decimal("43")
    assert (await _balance(session, product.id, rework_loc.id, QualityState.rework)) == Decimal("7")


# ─── tests: rebuild_all_balances ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rebuild_all_balances_matches_incremental(session: AsyncSession):
    """Полный пересчёт даёт тот же результат, что инкрементальный refresh."""
    user = await _make_user(session)
    product = await _make_product(session)
    raw = await _make_location(session, code="RAW7", name="Raw7", loc_type="raw_stock")
    laser = await _make_location(session, code="LASER10", name="Laser10", loc_type="laser")
    scrap_loc = await _make_location(session, code="SCRAP3", name="Scrap3", loc_type="scrap")

    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product.id, from_location_id=raw.id, to_location_id=laser.id,
        quantity=Decimal("100"), reason=Reason.issue_to_work, created_by=user.id,
    ))
    await svc.record(session, StockCommand(
        product_id=product.id, from_location_id=laser.id, to_location_id=scrap_loc.id,
        quantity=Decimal("10"), reason=Reason.scrap,
        quality_state=QualityState.good, to_quality_state=QualityState.scrap,
        created_by=user.id,
    ))
    await session.commit()

    # Запоминаем инкрементальные балансы
    before_raw = await _balance(session, product.id, raw.id)
    before_laser = await _balance(session, product.id, laser.id)
    before_scrap = await _balance(session, product.id, scrap_loc.id, QualityState.scrap)

    # Полный пересчёт
    pm = StockProjectionManager()
    count = await pm.rebuild_all_balances(session)
    await session.commit()

    assert (await _balance(session, product.id, raw.id)) == before_raw
    assert (await _balance(session, product.id, laser.id)) == before_laser
    assert (await _balance(session, product.id, scrap_loc.id, QualityState.scrap)) == before_scrap
    assert count >= 3  # хотя бы 3 строки баланса


# ─── tests: invariants ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stock_ledger_invariants_pass_after_operations(session: AsyncSession):
    """Все S1-S6 инварианты не нарушаются после набора операций."""
    user = await _make_user(session)
    product = await _make_product(session)
    raw = await _make_location(session, code="RAW8", name="Raw8", loc_type="raw_stock")
    laser = await _make_location(session, code="LASER11", name="Laser11", loc_type="laser")
    scrap_loc = await _make_location(session, code="SCRAP4", name="Scrap4", loc_type="scrap")

    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product.id, from_location_id=raw.id, to_location_id=laser.id,
        quantity=Decimal("100"), reason=Reason.issue_to_work, created_by=user.id,
    ))
    await svc.record(session, StockCommand(
        product_id=product.id, from_location_id=laser.id, to_location_id=scrap_loc.id,
        quantity=Decimal("10"), reason=Reason.scrap,
        quality_state=QualityState.good, to_quality_state=QualityState.scrap,
        created_by=user.id,
    ))
    await session.commit()

    await assert_no_stock_ledger_invariants_violations(session, context="after-issue-scrap")


@pytest.mark.asyncio
async def test_zero_balance_row_removed(session: AsyncSession):
    """Если баланс становится 0 — строка удаляется (ck_stock_balances_nonzero)."""
    user = await _make_user(session)
    product = await _make_product(session)
    raw = await _make_location(session, code="RAW9", name="Raw9", loc_type="raw_stock")
    laser = await _make_location(session, code="LASER12", name="Laser12", loc_type="laser")

    svc = StockCommandService()
    # выдали 50, вернули 50 → на лазере баланс 0
    await svc.record(session, StockCommand(
        product_id=product.id, from_location_id=raw.id, to_location_id=laser.id,
        quantity=Decimal("50"), reason=Reason.issue_to_work, created_by=user.id,
    ))
    await svc.record(session, StockCommand(
        product_id=product.id, from_location_id=laser.id, to_location_id=raw.id,
        quantity=Decimal("50"), reason=Reason.return_to_stock, created_by=user.id,
    ))
    await session.commit()

    # На лазере баланс 0 → строки нет
    assert (await _balance(session, product.id, laser.id)) == Decimal("0")
    # На складе тоже 0 (вернули всё)
    assert (await _balance(session, product.id, raw.id)) == Decimal("0")
