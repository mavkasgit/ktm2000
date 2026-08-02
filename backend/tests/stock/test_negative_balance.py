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
    StockValidationError,
)

pytestmark = pytest.mark.asyncio


# ─── helpers ────────────────────────────────────────────────────────────────


async def _make_user(session: AsyncSession, username: str = "stock-tester") -> User:
    user = User(
        username=username,
        email=f"{username}@local",
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


async def test_insufficient_balance_raises_error(session: AsyncSession):
    user = await _make_user(session)
    product = await _make_product(session)
    raw = await _make_location(session, code="RAW", name="Raw", loc_type="raw_stock")
    laser = await _make_location(session, code="LASER", name="Laser", loc_type="production")

    svc = StockCommandService()
    # Нулевой баланс -> ошибка
    with pytest.raises(StockValidationError) as exc:
        await svc.record(session, StockCommand(
            product_id=product.id,
            from_location_id=raw.id,
            to_location_id=laser.id,
            quantity=Decimal("10"),
            reason=Reason.TRANSFER_SEND,
            created_by=user.id,
        ))
    assert "Insufficient stock" in str(exc.value)

    # Пополняем до 5
    await svc.record(session, StockCommand(
        product_id=product.id,
        to_location_id=raw.id,
        quantity=Decimal("5"),
        reason=Reason.MANUAL_IN,
        created_by=user.id,
    ))
    await session.commit()

    # Списание 10 (больше чем 5) -> ошибка
    with pytest.raises(StockValidationError) as exc:
        await svc.record(session, StockCommand(
            product_id=product.id,
            from_location_id=raw.id,
            to_location_id=laser.id,
            quantity=Decimal("10"),
            reason=Reason.TRANSFER_SEND,
            created_by=user.id,
        ))
    assert "Insufficient stock" in str(exc.value)

    # Списание 5 -> успешно
    tx = await svc.record(session, StockCommand(
        product_id=product.id,
        from_location_id=raw.id,
        to_location_id=laser.id,
        quantity=Decimal("5"),
        reason=Reason.TRANSFER_SEND,
        created_by=user.id,
    ))
    await session.commit()
    assert tx.id is not None
    assert (await _balance(session, product.id, raw.id)) == Decimal("0")
    assert (await _balance(session, product.id, laser.id)) == Decimal("5")


async def test_compensation_bypasses_balance_check(session: AsyncSession):
    user = await _make_user(session)
    product = await _make_product(session)
    raw = await _make_location(session, code="RAW", name="Raw", loc_type="raw_stock")
    laser = await _make_location(session, code="LASER", name="Laser", loc_type="production")

    svc = StockCommandService()
    # Сначала заносим 10 на raw
    tx_in = await svc.record(session, StockCommand(
        product_id=product.id,
        to_location_id=raw.id,
        quantity=Decimal("10"),
        reason=Reason.MANUAL_IN,
        created_by=user.id,
    ))
    # Перемещаем 10 на laser
    tx_send = await svc.record(session, StockCommand(
        product_id=product.id,
        from_location_id=raw.id,
        to_location_id=laser.id,
        quantity=Decimal("10"),
        reason=Reason.TRANSFER_SEND,
        created_by=user.id,
    ))
    await session.commit()

    # Баланс на raw стал 0.
    # Компенсационная транзакция списания с raw, где баланс сейчас равен 0.
    # Так как это компенсация (compensates_tx_id = tx_in.id), она должна пройти успешно.
    tx_comp = await svc.record(session, StockCommand(
        product_id=product.id,
        from_location_id=raw.id,
        to_location_id=laser.id,
        quantity=Decimal("10"),
        reason=Reason.TRANSFER_SEND,
        compensates_tx_id=tx_in.id,
        created_by=user.id,
    ))
    await session.commit()
    assert tx_comp.id is not None
    # Баланс стал отрицательным на raw, так как компенсация обошла валидацию баланса!
    assert (await _balance(session, product.id, raw.id)) == Decimal("-10")


async def test_manual_in_bypasses_balance_check(session: AsyncSession):
    user = await _make_user(session)
    product = await _make_product(session)
    raw = await _make_location(session, code="RAW", name="Raw", loc_type="raw_stock")

    svc = StockCommandService()
    # MANUAL_IN не имеет from_location_id (он None), баланс raw равен 0.
    tx = await svc.record(session, StockCommand(
        product_id=product.id,
        to_location_id=raw.id,
        quantity=Decimal("100"),
        reason=Reason.MANUAL_IN,
        created_by=user.id,
    ))
    await session.commit()
    assert tx.id is not None
    assert (await _balance(session, product.id, raw.id)) == Decimal("100")


async def test_idempotency_bypasses_balance_check_on_repeat(session: AsyncSession):
    user = await _make_user(session)
    product = await _make_product(session)
    raw = await _make_location(session, code="RAW", name="Raw", loc_type="raw_stock")
    laser = await _make_location(session, code="LASER", name="Laser", loc_type="production")

    svc = StockCommandService()
    # Пополняем баланс до 10
    await svc.record(session, StockCommand(
        product_id=product.id,
        to_location_id=raw.id,
        quantity=Decimal("10"),
        reason=Reason.MANUAL_IN,
        created_by=user.id,
    ))
    await session.commit()

    # Списываем 10 с ключом идемпотентности -> баланс становится 0
    cmd = StockCommand(
        product_id=product.id,
        from_location_id=raw.id,
        to_location_id=laser.id,
        quantity=Decimal("10"),
        reason=Reason.TRANSFER_SEND,
        idempotency_key="unique-key-123",
        created_by=user.id,
    )
    tx1 = await svc.record(session, cmd)
    await session.commit()
    assert tx1.id is not None
    assert (await _balance(session, product.id, raw.id)) == Decimal("0")

    # Повторный запрос с тем же idempotency_key должен вернуть ту же транзакцию
    # без ошибки недостатка баланса
    tx2 = await svc.record(session, cmd)
    await session.commit()
    assert tx2.id == tx1.id
