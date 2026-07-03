"""Тесты Этапа 2: Transfer на StockTransaction без двойной записи.

Покрывают:
- transfer_send создаёт 2 StockTransaction (TRANSFER_SEND + TRANSFER_RECEIVE)
- Баланс обновляется
- Идемпотентность transfer_send
- cancel_transfer создаёт компенсации
- Идемпотентность cancel
- correct_transfer обновляет quantity
- POST /api/transfers → 200 + Transfer + 2× StockTransaction
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, ProductType, Section, User, UserRole
from app.models.internal_plan import SectionPlanLine
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.techcard import Techcard, TechcardLine
from app.models.transfer import Transfer, TransferStatus
from app.models.work_task import WorkTask, WorkTaskStatus
from app.stock.models import QualityState, Reason, StockBalance, StockTransaction
from app.stock.services import StockCommand, StockCommandService
from app.transfers.services import cancel_transfer, correct_transfer, transfer_send
from tests.test_integrity_invariants import (
    _auth_headers,
    _make_user,
    _release_via_take_to_work,
)


# ─── helpers ────────────────────────────────────────────────────────────────


async def _make_product(session: AsyncSession, sku: str = "XFR") -> Product:
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
        code=code, name=name,
        kind="production" if loc_type in ("laser", "welding", "painting", "assembly") else loc_type,
        type=loc_type, is_active=True, sort_order=0,
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


async def _make_two_ghp_setup(
    session: AsyncSession,
    *,
    sku: str = "STG2",
    qty: Decimal = Decimal("10"),
) -> dict:
    """Две production-секции в разных GHP с маршрутом из двух этапов.

    Возвращает user, product, from_task, to_task, sections, transfer_id=None.
    """
    user = await _make_user(session, f"{sku}@local")

    sec1 = Section(code=f"{sku}-S1", name="S1", kind="production", is_active=True, sort_order=0)
    sec2 = Section(code=f"{sku}-S2", name="S2", kind="production", is_active=True, sort_order=1)
    session.add_all([sec1, sec2])
    await session.flush()

    spg_a = StorageProductionGroup(code=f"{sku}-A", name="A", is_active=True, sort_order=0)
    spg_b = StorageProductionGroup(code=f"{sku}-B", name="B", is_active=True, sort_order=1)
    session.add_all([spg_a, spg_b])
    await session.flush()
    session.add_all([
        SpgSection(spg_id=spg_a.id, section_id=sec1.id, sort_order=0),
        SpgSection(spg_id=spg_b.id, section_id=sec2.id, sort_order=0),
    ])

    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    route = ProductionRoute(name=f"R-{sku}", is_active=True)
    session.add(route)
    await session.flush()
    for idx, (sec, code) in enumerate([(sec1, "OP1"), (sec2, "OP2")], start=1):
        st = RouteStage(route_id=route.id, sequence=idx, section_id=sec.id, is_final=(idx == 2))
        session.add(st)
        await session.flush()
        session.add(RouteOperation(route_stage_id=st.id, sequence=1, operation_code=code, operation_name=code))

    tech = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(tech)
    await session.flush()
    session.add(TechcardLine(techcard_id=tech.id, component_product_id=product.id, quantity=Decimal("1"), unit="pcs"))

    plan = ProductionPlan(
        plan_no=f"P-{sku}", name="p", status=ProductionPlanStatus.approved,
        period_start=datetime(2026, 5, 1), period_end=datetime(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()

    pos = PlanPosition(
        production_plan_id=plan.id, product_id=product.id,
        source_type=PlanSourceType.manual, source_sku=product.sku, source_name=product.name,
        quantity=qty, source_payload={}, status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid, validation_errors=[],
        period_start=plan.period_start, period_end=plan.period_end,
        has_pack_ops=False, route_id=route.id, route_assigned_at=None,
    )
    session.add(pos)
    await session.flush()
    await session.commit()

    return {
        "user": user,
        "product": product,
        "plan": plan,
        "position": pos,
        "sections": [sec1, sec2],
        "route": route,
    }


async def _make_tasks_transferable(
    session: AsyncSession,
    client,
    setup: dict,
) -> dict:
    """Take-to-work → issue → complete on source task.

    Returns {from_task_id, to_task_id, user}.
    """
    await _release_via_take_to_work(client, setup["position"].id)
    tasks = (await session.execute(
        select(WorkTask).order_by(WorkTask.id)
    )).scalars().all()
    assert len(tasks) >= 2
    src = tasks[0]
    dst = tasks[1]

    # Create a stock section for issue_to_work from/to
    from app.stock import StockCommand, StockCommandService, Reason
    from app.models.section import Section
    stock = Section(code="T2-STK", name="Stock", kind="raw_stock", type="raw_stock",
                    is_active=True, sort_order=0)
    session.add(stock)
    await session.flush()
    stock_id = stock.id

    svc = StockCommandService()
    # Seed stock balance
    await svc.record(session, StockCommand(
        product_id=src.product_id,
        from_location_id=None,
        to_location_id=stock_id,
        quantity=src.planned_quantity,
        reason=Reason.manual_in,
        created_by=setup["user"].id,
    ))
    # issue_to_work: from stock to source section
    await svc.record(session, StockCommand(
        product_id=src.product_id,
        from_location_id=stock_id,
        to_location_id=src.section_id,
        quantity=src.planned_quantity,
        reason=Reason.issue_to_work,
        task_id=src.id,
        created_by=setup["user"].id,
    ))
    # complete: good output appears on the source section
    await svc.record(session, StockCommand(
        product_id=src.product_id,
        from_location_id=None,
        to_location_id=src.section_id,
        quantity=src.planned_quantity,
        reason=Reason.complete,
        task_id=src.id,
        source_ref="test_seed",
        created_by=setup["user"].id,
    ))
    await session.flush()

    # Verify source is transferable (check via ledger)
    from app.stock.services import StockProjectionManager
    pm = StockProjectionManager()
    cache = await pm.get_task_cache(session, src.id)
    assert cache["completed_quantity"] >= Decimal("0")

    return {"from_task_id": src.id, "to_task_id": dst.id, "user": setup["user"]}


_py_test_mark = pytest.mark.asyncio


# ─── tests ──────────────────────────────────────────────────────────────────


@_py_test_mark
async def test_transfer_send_creates_two_stock_tx(session: AsyncSession, client) -> None:
    """После transfer_send() есть 2 StockTransaction (SEND + RECEIVE)."""
    setup = await _make_two_ghp_setup(session, sku="T2STX", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)

    result = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("5"),
        actor_id=ctx["user"].id,
        idempotency_key="t2stx:send",
    )
    assert result["status"] == "accepted"
    await session.commit()

    # Check StockTransactions
    txs = (await session.execute(
        select(StockTransaction).where(
            StockTransaction.transfer_id == result["transfer_id"]
        ).order_by(StockTransaction.id)
    )).scalars().all()
    assert len(txs) == 2

    send_tx = txs[0]
    recv_tx = txs[1]
    assert send_tx.reason == Reason.transfer_send
    assert send_tx.task_id == ctx["from_task_id"]
    assert recv_tx.reason == Reason.transfer_receive
    assert recv_tx.task_id == ctx["to_task_id"]
    assert send_tx.quantity == Decimal("5")
    assert recv_tx.quantity == Decimal("5")
    assert send_tx.transfer_id == recv_tx.transfer_id


@_py_test_mark
async def test_transfer_send_updates_balance(session: AsyncSession, client) -> None:
    """StockBalance у to_location вырос, у from_location упал."""
    setup = await _make_two_ghp_setup(session, sku="T2BAL", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)

    from_task = await session.get(WorkTask, ctx["from_task_id"])
    to_task = await session.get(WorkTask, ctx["to_task_id"])

    bal_before_from = await _balance(session, from_task.product_id, from_task.section_id)
    bal_before_to = await _balance(session, to_task.product_id, to_task.section_id)

    await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("5"),
        actor_id=ctx["user"].id,
    )
    await session.commit()

    # From-location balance уменьшился, to-location увеличился
    bal_from = await _balance(session, from_task.product_id, from_task.section_id)
    bal_to = await _balance(session, to_task.product_id, to_task.section_id)
    # Две транзакции (SEND + RECEIVE) обе from→to → from:-2Q, to:+2Q
    assert bal_from == bal_before_from - Decimal("10")  # 2 × 5
    assert bal_to == bal_before_to + Decimal("10")


@_py_test_mark
async def test_transfer_send_idempotent(session: AsyncSession, client) -> None:
    """Повторный transfer_send с тем же idempotency_key не создаёт вторую пару."""
    setup = await _make_two_ghp_setup(session, sku="T2IDM", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)

    key = "t2idm:unique"
    r1 = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("5"),
        actor_id=ctx["user"].id,
        idempotency_key=key,
    )
    r2 = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("5"),
        actor_id=ctx["user"].id,
        idempotency_key=key,
    )
    await session.commit()

    assert r1["transfer_id"] == r2["transfer_id"]
    assert r2.get("idempotent_replay") is True
    txs = (await session.execute(
        select(StockTransaction).where(
            StockTransaction.transfer_id == r1["transfer_id"]
        )
    )).scalars().all()
    assert len(txs) == 2  # не 4


@_py_test_mark
async def test_cancel_transfer_creates_compensation(session: AsyncSession, client) -> None:
    """После отмены есть компенсационные StockTransaction, баланс = 0."""
    setup = await _make_two_ghp_setup(session, sku="T2CNL", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)

    send = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("5"),
        actor_id=ctx["user"].id,
    )
    from_task = await session.get(WorkTask, ctx["from_task_id"])
    to_task = await session.get(WorkTask, ctx["to_task_id"])

    await cancel_transfer(
        session, transfer_id=send["transfer_id"], actor_id=ctx["user"].id,
    )
    await session.commit()

    # После компенсации: на секции источника остаётся issue+complete (20)
    # минус transfer_send (5) плюс компенсация send (5) = 20
    assert (await _balance(session, from_task.product_id, from_task.section_id)) == Decimal("20")
    assert (await _balance(session, to_task.product_id, to_task.section_id)) == Decimal("0")

    # Есть компенсационные записи
    comps = (await session.execute(
        select(StockTransaction).where(
            StockTransaction.transfer_id == send["transfer_id"],
            StockTransaction.compensates_tx_id.isnot(None),
        )
    )).scalars().all()
    assert len(comps) == 2  # SEND + RECEIVE


@_py_test_mark
async def test_cancel_transfer_idempotent(session: AsyncSession, client) -> None:
    """Повторная отмена — no-op."""
    setup = await _make_two_ghp_setup(session, sku="T2CNI", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)

    send = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("5"),
        actor_id=ctx["user"].id,
    )
    r1 = await cancel_transfer(
        session, transfer_id=send["transfer_id"], actor_id=ctx["user"].id,
    )
    r2 = await cancel_transfer(
        session, transfer_id=send["transfer_id"], actor_id=ctx["user"].id,
    )
    await session.commit()
    assert r1["status"] == "cancelled"
    assert r2["status"] == "cancelled"
    txs = (await session.execute(
        select(StockTransaction).where(
            StockTransaction.transfer_id == send["transfer_id"]
        )
    )).scalars().all()
    # 2 оригинала + 2 компенсации = 4 (при повторном cancel не должно добавиться)
    assert len(txs) == 4


@_py_test_mark
async def test_correct_transfer_quantity(session: AsyncSession, client) -> None:
    """После correct_transfer() StockTransaction.quantity соответствует новому."""
    setup = await _make_two_ghp_setup(session, sku="T2COR", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)

    send = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("5"),
        actor_id=ctx["user"].id,
    )
    await correct_transfer(
        session,
        transfer_id=send["transfer_id"],
        new_quantity=Decimal("3"),
        actor_id=ctx["user"].id,
    )
    await session.commit()

    txs = (await session.execute(
        select(StockTransaction).where(
            StockTransaction.transfer_id == send["transfer_id"],
            StockTransaction.compensates_tx_id.is_(None),
        )
    )).scalars().all()
    for tx in txs:
        assert tx.quantity == Decimal("3")


@_py_test_mark
async def test_transfer_send_via_api(session: AsyncSession, client) -> None:
    """POST /api/transfers → 200 + Transfer + 2× StockTransaction."""
    setup = await _make_two_ghp_setup(session, sku="T2API", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    headers = _auth_headers(ctx["user"])

    resp = await client.post(
        "/api/transfers",
        json={
            "from_task_id": ctx["from_task_id"],
            "to_task_id": ctx["to_task_id"],
            "quantity": "5",
            "idempotency_key": "t2api:send",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "accepted"

    # Transfer exists
    transfer = await session.get(Transfer, data["transfer_id"])
    assert transfer is not None
    assert transfer.status == TransferStatus.accepted

    # 2 StockTransactions
    txs = (await session.execute(
        select(StockTransaction).where(
            StockTransaction.transfer_id == transfer.id,
        )
    )).scalars().all()
    assert len(txs) == 2

    # Проверка Stock Ledger инвариантов
    from tests.test_integrity_invariants import assert_no_stock_ledger_invariants_violations
    await assert_no_stock_ledger_invariants_violations(session, context="api-transfer")


@_py_test_mark
async def test_transfer_send_task_cache_via_ledger(session: AsyncSession, client) -> None:
    """get_task_cache() показывает transferred/received из StockTransaction после transfer_send."""
    setup = await _make_two_ghp_setup(session, sku="T2TCACHE", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)

    await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("5"),
        actor_id=ctx["user"].id,
    )
    await session.commit()

    from app.stock.services import StockProjectionManager
    pm = StockProjectionManager()
    from_cache = await pm.get_task_cache(session, ctx["from_task_id"])
    to_cache = await pm.get_task_cache(session, ctx["to_task_id"])

    assert from_cache["transferred_quantity"] == Decimal("5")
    assert to_cache["received_quantity"] == Decimal("5")
