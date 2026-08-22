"""Тесты журнала действий action_journal (ADR-0019, тикет #113).

Покрывают:
- transfer_send создаёт одну запись Action (transfer_send, ref_id=transfer.id)
- обе проводки ledger ссылаются на неё через StockTransaction.action_id
- cancel_transfer создаёт Action (transfer_cancel), компенсации ссылаются на него
"""
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_journal import Action
from app.stock.models import Reason, StockTransaction
from app.transfers.services import cancel_transfer, transfer_send
from tests.test_integrity_invariants import assert_no_invariants_violations
from tests.stock.test_transfer_stage2 import _make_two_ghp_setup, _make_tasks_transferable

_py_test_mark = pytest.mark.asyncio


@_py_test_mark
async def test_transfer_send_creates_action(session: AsyncSession, client) -> None:
    """transfer_send создаёт Action с ref_id=transfer.id; проводки ссылаются на него."""
    setup = await _make_two_ghp_setup(session, sku="AJT1", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)

    result = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("5"),
        actor_id=ctx["user"].id,
        idempotency_key="ajt1:send",
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="aj-transfer-send")

    actions = (await session.execute(
        select(Action).where(
            Action.action_type == "transfer_send",
            Action.ref_id == result["transfer_id"],
        )
    )).scalars().all()
    assert len(actions) == 1
    action = actions[0]
    assert action.status == "active"
    assert action.depends_on == []

    txs = (await session.execute(
        select(StockTransaction).where(
            StockTransaction.transfer_id == result["transfer_id"]
        ).order_by(StockTransaction.id)
    )).scalars().all()
    assert len(txs) == 2
    assert all(tx.action_id == action.id for tx in txs)
    assert {tx.reason for tx in txs} == {Reason.TRANSFER_SEND, Reason.TRANSFER_RECEIVE}


@_py_test_mark
async def test_cancel_transfer_creates_action(session: AsyncSession, client) -> None:
    """cancel_transfer создаёт Action; компенсационные проводки ссылаются на него."""
    setup = await _make_two_ghp_setup(session, sku="AJT2", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)

    send = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("5"),
        actor_id=ctx["user"].id,
        idempotency_key="ajt2:send",
    )
    await session.commit()

    await cancel_transfer(
        session,
        transfer_id=send["transfer_id"],
        actor_id=ctx["user"].id,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="aj-cancel-transfer")

    actions = (await session.execute(
        select(Action).where(
            Action.action_type == "transfer_cancel",
            Action.ref_id == send["transfer_id"],
        )
    )).scalars().all()
    assert len(actions) == 1
    cancel_action = actions[0]

    comp_txs = (await session.execute(
        select(StockTransaction).where(
            StockTransaction.transfer_id == send["transfer_id"],
            StockTransaction.reverses_id.is_not(None),
        )
    )).scalars().all()
    assert len(comp_txs) == 2  # SEND + RECEIVE
    assert all(tx.action_id == cancel_action.id for tx in comp_txs)
