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
    assert_no_invariants_violations,
)
# Канонические определения фабрик живут в tests/helpers/transfers.py
# (#131 follow-up); реэкспорт сохраняет старый путь импорта для потребителей.
from tests.helpers.transfers import _make_tasks_transferable, _make_two_ghp_setup


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
        type=loc_type, is_active=True, sort_order=0,
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


# _make_two_ghp_setup / _make_tasks_transferable переехали в канонический
# tests/helpers/transfers.py (#131 follow-up) — см. реэкспорт в шапке модуля.


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
    assert send_tx.reason == Reason.TRANSFER_SEND
    assert send_tx.task_id == ctx["from_task_id"]
    assert recv_tx.reason == Reason.TRANSFER_RECEIVE
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
    # TRANSFER_SEND двигает остаток; TRANSFER_RECEIVE — только учёт задачи.
    assert bal_from == bal_before_from - Decimal("5")
    assert bal_to == bal_before_to + Decimal("5")


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

    # После компенсации: на секции источника остаётся TRANSFER_RECEIVE (10)
    # минус transfer_send (5) плюс компенсация send (5) = 10
    assert (await _balance(session, from_task.product_id, from_task.section_id)) == Decimal("10")
    assert (await _balance(session, to_task.product_id, to_task.section_id)) == Decimal("0")

    # Есть компенсационные записи
    comps = (await session.execute(
        select(StockTransaction).where(
            StockTransaction.transfer_id == send["transfer_id"],
            StockTransaction.reverses_id.isnot(None),
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
    """correct_transfer через ReversalService.amend: старая пара неизменна,
    компенсации под старым Transfer, новая пара — под новым Transfer."""
    setup = await _make_two_ghp_setup(session, sku="T2COR", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)

    send = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("5"),
        actor_id=ctx["user"].id,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="t2cor-send")

    originals = sorted(
        (
            await session.execute(
                select(StockTransaction).where(
                    StockTransaction.transfer_id == send["transfer_id"],
                    StockTransaction.reverses_id.is_(None),
                )
            )
        ).scalars().all(),
        key=lambda t: t.id,
    )
    assert len(originals) == 2

    correct_result = await correct_transfer(
        session,
        transfer_id=send["transfer_id"],
        new_quantity=Decimal("3"),
        actor_id=ctx["user"].id,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="t2cor-correct")

    new_transfer_id = correct_result["new_transfer_id"]
    assert correct_result["amended_transfer_id"] == send["transfer_id"]
    assert correct_result["status"] == "amended"

    # Старый Transfer: 2 исходных (нетронутых) + 2 компенсации = 4.
    old_txs = (await session.execute(
        select(StockTransaction).where(
            StockTransaction.transfer_id == send["transfer_id"]
        ).order_by(StockTransaction.id)
    )).scalars().all()
    assert len(old_txs) == 4

    by_id = {tx.id: tx for tx in old_txs}
    for orig in originals:
        assert by_id[orig.id].quantity == Decimal("5")
        assert by_id[orig.id].from_location_id == orig.from_location_id
        assert by_id[orig.id].to_location_id == orig.to_location_id

    compensations = [tx for tx in old_txs if tx.reverses_id is not None]
    assert {tx.reverses_id for tx in compensations} == {orig.id for orig in originals}
    assert all(tx.quantity == Decimal("5") for tx in compensations)

    # Новый Transfer: 2 проводки с новым quantity.
    new_txs = (await session.execute(
        select(StockTransaction).where(
            StockTransaction.transfer_id == new_transfer_id
        ).order_by(StockTransaction.id)
    )).scalars().all()
    assert len(new_txs) == 2
    assert all(tx.quantity == Decimal("3") for tx in new_txs)

    # Старый Transfer в статусе amended.
    old_transfer = await session.get(Transfer, send["transfer_id"])
    assert old_transfer.status == TransferStatus.amended


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


@_py_test_mark
async def test_complete_after_transfer_balance_not_doubled(session: AsyncSession, client) -> None:
    """transfer_send + complete_task: balance приёмника == qty, не 2×."""
    setup = await _make_two_ghp_setup(session, sku="T2CMP", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)

    xfer_qty = Decimal("10")
    await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=xfer_qty,
        actor_id=ctx["user"].id,
        idempotency_key="t2cmp:send",
    )
    await session.commit()

    to_task = await session.get(WorkTask, ctx["to_task_id"])
    assert to_task is not None
    bal_after_xfer = await _balance(session, to_task.product_id, to_task.section_id)
    assert bal_after_xfer == xfer_qty

    from app.services.shopfloor.operations_tasks import complete_task
    await complete_task(
        session,
        task_id=to_task.id,
        good_quantity=xfer_qty,
        defect_quantity=Decimal("0"),
        actor_id=ctx["user"].id,
    )
    await session.commit()

    bal_after_complete = await _balance(session, to_task.product_id, to_task.section_id)
    assert bal_after_complete == xfer_qty, (
        f"Expected receiver balance {xfer_qty}, got {bal_after_complete}"
    )

    complete_tx = await session.scalar(
        select(StockTransaction).where(
            StockTransaction.task_id == to_task.id,
            StockTransaction.reason == Reason.COMPLETE,
        )
    )
    assert complete_tx is not None
    assert complete_tx.from_location_id == to_task.section_id
    assert complete_tx.to_location_id == to_task.section_id

    from app.stock.services import StockProjectionManager
    pm = StockProjectionManager()
    cache = await pm.get_task_cache(session, to_task.id)
    assert cache["issued_quantity"] == xfer_qty
    assert cache["completed_quantity"] == xfer_qty


@_py_test_mark
async def test_correct_then_reverse_balance_restored(
    session: AsyncSession, client,
) -> None:
    """DoD тикет #124: correct → reverse → баланс восстановлен (net=0).

    Сценарий: send(5) → correct(3) → cancel(new_transfer).
    Оба Transfer (старый и новый) компенсируются, net по обеим секциям = 0.
    """
    from app.models.action_journal import Action

    setup = await _make_two_ghp_setup(session, sku="T2CRV", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    from_task = await session.get(WorkTask, ctx["from_task_id"])
    to_task = await session.get(WorkTask, ctx["to_task_id"])

    # 1. Send 5
    send = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("5"),
        actor_id=ctx["user"].id,
        idempotency_key="t2crv:send",
    )
    await session.commit()

    # 2. Correct 5 → 3 (amend)
    correct_result = await correct_transfer(
        session,
        transfer_id=send["transfer_id"],
        new_quantity=Decimal("3"),
        actor_id=ctx["user"].id,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="t2crv-correct")

    new_transfer_id = correct_result["new_transfer_id"]

    # После correct: net по источнику = -3 (отправлено 3),
    # net по приёмнику = +3 (получено 3).
    assert (await _balance(
        session, from_task.product_id, from_task.section_id,
    )) == Decimal("7")  # 10 - 3
    assert (await _balance(
        session, to_task.product_id, to_task.section_id,
    )) == Decimal("3")

    # 3. Reverse (cancel) нового Transfer
    cancel_result = await cancel_transfer(
        session,
        transfer_id=new_transfer_id,
        actor_id=ctx["user"].id,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="t2crv-cancel")

    assert cancel_result["status"] == "cancelled"

    # Баланс восстановлен: net=0 по обеим секциям.
    assert (await _balance(
        session, from_task.product_id, from_task.section_id,
    )) == Decimal("10")  # исходный баланс возвращён
    assert (await _balance(
        session, to_task.product_id, to_task.section_id,
    )) == Decimal("0")

    # Старый Transfer = amended, новый = cancelled.
    old_transfer = await session.get(Transfer, send["transfer_id"])
    assert old_transfer.status == TransferStatus.amended
    new_transfer = await session.get(Transfer, new_transfer_id)
    assert new_transfer.status == TransferStatus.cancelled

    # Под новым Transfer'ом есть reversal Action (от cancel).
    # Старый Transfer корректируется через amend: компенсации делят
    # новый Action с action_type="transfer_send" (amends_action_id ≠ None).
    from app.models.action_journal import ActionStatus
    from sqlalchemy import select as sa_select

    # Исходный Action перешёл в AMENDED (не REVERSED).
    old_send_action = (await session.execute(
        sa_select(Action).where(
            Action.action_type == "transfer_send",
            Action.ref_id == send["transfer_id"],
        )
    )).scalar_one_or_none()
    assert old_send_action is not None
    assert old_send_action.status == ActionStatus.AMENDED

    # Новый Action: transfer_send с amends_action_id → новый Transfer.
    amend_action = (await session.execute(
        sa_select(Action).where(
            Action.action_type == "transfer_send",
            Action.amends_action_id == old_send_action.id,
        )
    )).scalar_one_or_none()
    assert amend_action is not None
    assert amend_action.ref_id == new_transfer_id

    # Под новым Transfer: reversal Action (от cancel).
    new_reversals = (await session.execute(
        sa_select(Action).where(
            Action.action_type == "reversal",
            Action.ref_id == new_transfer_id,
        )
    )).scalars().all()
    assert len(new_reversals) == 1  # от cancel


@_py_test_mark
async def test_cancel_transfer_blocked_when_target_completed_parts(
    session: AsyncSession, client,
) -> None:
    """Guard-паритет #124: предварительная доменная валидация сохранена.

    Приёмная сторона завершила часть количества (in_work < sent_quantity) —
    cancel_transfer отклоняется ДО вызова reverse, компенсаций нет.
    """
    setup = await _make_two_ghp_setup(session, sku="T2CNG", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)

    send = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("5"),
        actor_id=ctx["user"].id,
        idempotency_key="t2cng:send",
    )
    await session.commit()

    # Приёмник завершил 2 из 5 → in_work = 3 < 5.
    from app.services.shopfloor.operations_tasks import complete_task

    await complete_task(
        session,
        task_id=ctx["to_task_id"],
        good_quantity=Decimal("2"),
        defect_quantity=Decimal("0"),
        actor_id=ctx["user"].id,
    )
    await session.commit()

    with pytest.raises(ValueError, match="Cannot cancel transfer"):
        await cancel_transfer(
            session,
            transfer_id=send["transfer_id"],
            actor_id=ctx["user"].id,
        )
    await assert_no_invariants_violations(session, context="t2cng-cancel-guard")

    # Ничего не изменилось: Transfer остался accepted, компенсаций нет.
    transfer = await session.get(Transfer, send["transfer_id"])
    assert transfer is not None
    assert transfer.status == TransferStatus.accepted
    comps = (await session.execute(
        select(StockTransaction).where(
            StockTransaction.transfer_id == transfer.id,
            StockTransaction.reverses_id.is_not(None),
        )
    )).scalars().all()
    assert comps == []


@_py_test_mark
async def test_correct_transfer_reduce_blocked_by_target_in_work(
    session: AsyncSession, client,
) -> None:
    """Guard-паритет #124: reduce ниже in_work баланса приёмника отклоняется.

    Приёмник завершил 3 из 5 (in_work = 2); коррекция 5 → 1 (diff=-4)
    создала бы «фантомный» слив — ValueError до amend, без побочных эффектов.
    """
    setup = await _make_two_ghp_setup(session, sku="T2CRG", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)

    send = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("5"),
        actor_id=ctx["user"].id,
        idempotency_key="t2crg:send",
    )
    await session.commit()

    from app.services.shopfloor.operations_tasks import complete_task

    await complete_task(
        session,
        task_id=ctx["to_task_id"],
        good_quantity=Decimal("3"),
        defect_quantity=Decimal("0"),
        actor_id=ctx["user"].id,
    )
    await session.commit()

    with pytest.raises(ValueError, match="Cannot reduce transfer"):
        await correct_transfer(
            session,
            transfer_id=send["transfer_id"],
            new_quantity=Decimal("1"),
            actor_id=ctx["user"].id,
        )
    await assert_no_invariants_violations(session, context="t2crg-correct-guard")

    # Ничего не изменилось: Transfer остался accepted (не amended).
    transfer = await session.get(Transfer, send["transfer_id"])
    assert transfer is not None
    assert transfer.status == TransferStatus.accepted
    comps = (await session.execute(
        select(StockTransaction).where(
            StockTransaction.transfer_id == transfer.id,
            StockTransaction.reverses_id.is_not(None),
        )
    )).scalars().all()
    assert comps == []
