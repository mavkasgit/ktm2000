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
        storage_kind=SpgStorageKind.finished,
        requires_lot=True,
    )
    session.add(spg)
    await session.flush()
    reloaded = await session.get(StorageProductionGroup, spg.id)
    assert reloaded.storage_kind == SpgStorageKind.finished
    assert reloaded.requires_lot is True



async def _make_admin(session, email: str = "lot-admin@test.local") -> User:
    user = User(email=email, full_name="Lot Admin", role=UserRole.admin, is_active=True)
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_spg_with_requires_lot_blocks_negative_remainder(client, session):
    """SPG requires_lot flag prevents negative stock via StockTransaction."""
    from app.stock import Reason, StockCommand, StockCommandService

    await _make_admin(session)
    product = Product(sku="FG-LOT", name="Lot Product", type=ProductType.finished_good, unit="pcs")
    section = Section(code="LOT-SEC", name="Lot section")
    spg = StorageProductionGroup(code="LOT-SPG", name="Lot SPG", requires_lot=True, storage_kind=SpgStorageKind.raw)
    session.add_all([product, section, spg])
    await session.flush()
    session.add(SpgSection(spg_id=spg.id, section_id=section.id, sort_order=0))
    await session.commit()

    # Add stock via StockCommandService (manual_in)
    admin_user = await session.scalar(select(User).where(User.role == UserRole.admin))
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product.id,
        from_location_id=None,
        to_location_id=section.id,
        quantity=5,
        reason=Reason.MANUAL_IN,
        created_by=admin_user.id if admin_user else 1,
    ))
    await session.commit()

    # Verify balance via StockBalance table
    from app.stock.models import QualityState, StockBalance
    bal = await session.scalar(
        select(StockBalance).where(
            StockBalance.product_id == product.id,
            StockBalance.location_id == section.id,
            StockBalance.quality_state == QualityState.GOOD,
        )
    )
    assert bal is not None
    assert bal.balance_qty == 5

    # The requires_lot logic was formerly enforced at the old manual-operation
    # endpoint (deleted in Stage 7). Now it lives in StockCommandService._validate:
    # allow_negative (#133, negative_remainder) не пробивает lot-учёт.

    from app.stock import StockValidationError

    # Осознанный минус на участке с requires_lot блокируется даже с флагом.
    with pytest.raises(StockValidationError, match="requires_lot"):
        await svc.record(session, StockCommand(
            product_id=product.id,
            from_location_id=section.id,
            to_location_id=None,
            quantity=10,
            reason=Reason.TRANSFORM_CONSUME,
            created_by=admin_user.id if admin_user else 1,
            allow_negative=True,
        ))

    # Контроль: участок без requires_lot уходит в минус осознанно (#133).
    free_section = Section(code="LOT-FREE", name="No-lot section")
    session.add(free_section)
    await session.flush()
    await svc.record(session, StockCommand(
        product_id=product.id,
        to_location_id=free_section.id,
        quantity=5,
        reason=Reason.MANUAL_IN,
        created_by=admin_user.id if admin_user else 1,
    ))
    await svc.record(session, StockCommand(
        product_id=product.id,
        from_location_id=free_section.id,
        to_location_id=None,
        quantity=10,
        reason=Reason.TRANSFORM_CONSUME,
        created_by=admin_user.id if admin_user else 1,
        allow_negative=True,
    ))
    await session.commit()

    free_bal = await session.scalar(
        select(StockBalance).where(
            StockBalance.product_id == product.id,
            StockBalance.location_id == free_section.id,
            StockBalance.quality_state == QualityState.GOOD,
        )
    )
    assert free_bal is not None
    assert free_bal.balance_qty == -5

    # Лотковый участок не тронут: попытка минуса ничего не записала.
    bal_after = await session.scalar(
        select(StockBalance).where(
            StockBalance.product_id == product.id,
            StockBalance.location_id == section.id,
            StockBalance.quality_state == QualityState.GOOD,
        )
    )
    assert bal_after is not None
    assert bal_after.balance_qty == 5
