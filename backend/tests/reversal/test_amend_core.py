"""Тесты ядра amend (ADR-0019, тикет #115): preview_amend / amend.

Покрывают:
- happy path: компенсация старого + новый Transfer + amends_action_id;
  старое действие → status='amended' (reversed_by НЕ заполняется);
- атомарность: сбой на apply_forward откатывает всю транзакцию (D7-A);
- каскад зависимых (cascade=True): dependents компенсируются и получают
  'reversed', их эффекты заново НЕ воспроизводятся; без cascade —
  HasDependentActions;
- D7-A покрытие хвоста: дефицит новой прямой записи → CoverageShortfall
  блокер в preview, токен не выдаётся;
- StalePlanToken: kind токена различает reverse/amend; изменение мира.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.reversal.stock_compensator as sc_module
from app.models.action_journal import Action, ActionStatus
from app.models.transfer import Transfer, TransferStatus
from app.models.work_task import WorkTask
from app.reversal import errors
from app.reversal.service import reversal_service
from app.stock.models import Reason, StockBalance, StockTransaction
from app.transfers.services import transfer_send
from tests.stock.test_transfer_stage2 import (
    _make_tasks_transferable,
    _make_two_ghp_setup,
)
from tests.test_integrity_invariants import assert_no_invariants_violations

pytestmark = pytest.mark.asyncio


async def _send_transfer(
    session: AsyncSession,
    ctx: dict,
    *,
    qty: Decimal,
    key: str,
) -> tuple[Action, int]:
    result = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=qty,
        actor_id=ctx["user"].id,
        idempotency_key=key,
    )
    assert result["status"] == "accepted"
    action = (
        await session.execute(
            select(Action).where(
                Action.action_type == "transfer_send",
                Action.ref_id == result["transfer_id"],
            )
        )
    ).scalar_one()
    return action, result["transfer_id"]


async def _balance(session: AsyncSession, location_id: int, product_id: int) -> Decimal:
    return (
        await session.scalar(
            select(func.coalesce(func.sum(StockBalance.balance_qty), 0)).where(
                StockBalance.location_id == location_id,
                StockBalance.product_id == product_id,
            )
        )
    ) or Decimal("0")


async def _setup(session: AsyncSession, client, sku: str, *, qty=Decimal("5")):
    setup = await _make_two_ghp_setup(session, sku=sku, qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    action, transfer_id = await _send_transfer(session, ctx, qty=qty, key=f"{sku}:t1")
    await session.commit()
    await assert_no_invariants_violations(session, context=f"{sku}-setup")
    return action, transfer_id, ctx


async def _sections(session: AsyncSession, ctx: dict) -> tuple[int, int]:
    frm = await session.get(WorkTask, ctx["from_task_id"])
    to = await session.get(WorkTask, ctx["to_task_id"])
    assert frm is not None and to is not None
    return frm.section_id, to.section_id


# ─── happy path ──────────────────────────────────────────────────────────────


async def test_amend_replaces_action_atomically(session: AsyncSession, client) -> None:
    action, old_tid, ctx = await _setup(session, client, "AMDHAPPY")
    src_sec, dst_sec = await _sections(session, ctx)

    preview = await reversal_service.preview_amend(
        session, action.id, {"quantity": "3"}
    )
    assert preview.blockers == []
    assert preview.plan_token
    # Токен различим по kind от reverse
    from app.reversal.service import _verify_token

    payload = _verify_token(preview.plan_token, kind="amend")
    assert payload["kind"] == "amend"
    assert payload["changes"] == {"quantity": "3"}

    product_id = (await session.get(Transfer, old_tid)).product_id
    result = await reversal_service.amend(
        session,
        action.id,
        changes={"quantity": "3"},
        plan_token=preview.plan_token,
        reason="оператор ошибся количеством",
        actor="Тест",
        actor_id=ctx["user"].id,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="amd-happy")

    # Старое действие amended, reversed_by пуст; новое связано через amends_action_id
    await session.refresh(action)
    assert action.status == ActionStatus.AMENDED
    assert action.reversed_by_action_id is None
    new_action = await session.get(Action, result.new_action_id)
    assert new_action is not None
    assert new_action.action_type == "transfer_send"
    assert new_action.amends_action_id == action.id
    assert new_action.reason == "оператор ошибся количеством"

    # Новый Transfer принят с новым количеством; старый доменно отменён
    new_transfer = await session.get(Transfer, result.new_ref_id)
    old_transfer = await session.get(Transfer, old_tid)
    assert new_transfer is not None and new_transfer.id != old_tid
    assert new_transfer.status == TransferStatus.accepted
    assert new_transfer.sent_quantity == Decimal("3")
    assert old_transfer.status == TransferStatus.cancelled

    # Ledger: 2 компенсации + новая пара SEND/RECEIVE от нового действия
    txs = (
        await session.execute(
            select(StockTransaction).where(StockTransaction.action_id == new_action.id)
        )
    ).scalars().all()
    comp_txs = [t for t in txs if t.reverses_id is not None]
    fwd_txs = [t for t in txs if t.reverses_id is None]
    assert len(comp_txs) == 2
    assert {t.reason for t in fwd_txs} == {Reason.TRANSFER_SEND, Reason.TRANSFER_RECEIVE}
    assert all(t.quantity == Decimal("3") for t in fwd_txs)
    assert len(result.compensated_tx_ids) == 2

    # Нетто-эффект: источник −3, приёмник +3
    assert await _balance(session, src_sec, product_id) == Decimal("7")
    assert await _balance(session, dst_sec, product_id) == Decimal("3")




async def test_amend_failure_rolls_back_whole_transaction(
    session: AsyncSession, client, monkeypatch
) -> None:
    action, old_tid, ctx = await _setup(session, client, "AMDATOM")
    src_sec, dst_sec = await _sections(session, ctx)
    product_id = (await session.get(Transfer, old_tid)).product_id

    preview = await reversal_service.preview_amend(
        session, action.id, {"quantity": "4"}
    )
    assert preview.plan_token

    async def _boom(self, db, *, action, ref_id, changes, actor, actor_id):
        raise errors.CoverageShortfall(node=action.amends_action_id, deficit=Decimal("1"))

    aid, tid = action.id, old_tid  # plain int: после rollback объекты expired
    monkeypatch.setattr(sc_module.StockCompensator, "apply_forward", _boom)
    with pytest.raises(errors.CoverageShortfall):
        await reversal_service.amend(
            session,
            aid,
            changes={"quantity": "4"},
            plan_token=preview.plan_token,
            actor_id=ctx["user"].id,
        )
    await session.rollback()  # исключение = откат всей транзакции
    session.expunge_all()  # pending-объекты после rollback не пере-flush'ить
    monkeypatch.undo()

    action_db = await session.get(Action, aid)
    assert action_db.status == ActionStatus.ACTIVE
    orphan = (
        await session.execute(select(Action).where(Action.amends_action_id == aid))
    ).scalar_one_or_none()
    assert orphan is None
    old_transfer = await session.get(Transfer, tid)
    assert old_transfer.status == TransferStatus.accepted
    assert await _balance(session, src_sec, product_id) == Decimal("5")
    assert await _balance(session, dst_sec, product_id) == Decimal("5")
    await assert_no_invariants_violations(session, context="amd-atom")


# ─── D7-A покрытие новой записи ──────────────────────────────────────────────


async def test_preview_amend_blocks_on_forward_coverage_shortfall(
    session: AsyncSession, client
) -> None:
    action, _tid, _ctx = await _setup(session, client, "AMDCOV")

    preview = await reversal_service.preview_amend(
        session, action.id, {"quantity": "100"}
    )
    kinds = [b.kind for b in preview.blockers]
    assert "coverage" in kinds
    assert preview.plan_token is None  # preview-first: токена нет


# ─── каскад ──────────────────────────────────────────────────────────────────


async def _chain_of_two(session: AsyncSession, client, sku: str):
    setup = await _make_two_ghp_setup(session, sku=sku, qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    a1, t1 = await _send_transfer(session, ctx, qty=Decimal("5"), key=f"{sku}:t1")
    a2, _t2 = await _send_transfer(session, ctx, qty=Decimal("5"), key=f"{sku}:t2")
    a2.depends_on = [a1.id]
    await session.commit()
    await assert_no_invariants_violations(session, context=f"{sku}-chain")
    return a1, a2, ctx


async def test_amend_without_cascade_blocked_by_dependents(
    session: AsyncSession, client
) -> None:
    a1, a2, _ctx = await _chain_of_two(session, client, "AMDDEP")

    preview = await reversal_service.preview_amend(
        session, a1.id, {"quantity": "1"}
    )
    assert [b.kind for b in preview.blockers] == ["has_dependents"]
    assert preview.blockers[0].chain == [a2.id]
    assert preview.plan_token is None  # preview-first: confirm невозможен


async def test_amend_cascade_compensates_dependents_without_replay(
    session: AsyncSession, client
) -> None:
    a1, a2, ctx = await _chain_of_two(session, client, "AMDCAS")
    src_sec, dst_sec = await _sections(session, ctx)
    product_id = (await session.get(WorkTask, ctx["from_task_id"])).product_id

    preview = await reversal_service.preview_amend(
        session, a1.id, {"quantity": "2"}, cascade=True
    )
    assert preview.blockers == []
    reverted_ids = {n.id for n in preview.revert}
    assert reverted_ids == {a1.id, a2.id}

    result = await reversal_service.amend(
        session,
        a1.id,
        changes={"quantity": "2"},
        plan_token=preview.plan_token,
        actor_id=ctx["user"].id,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="amd-cas")

    await session.refresh(a1)
    await session.refresh(a2)
    assert a1.status == ActionStatus.AMENDED
    assert a2.status == ActionStatus.REVERSED
    assert a2.reversed_by_action_id is not None
    # Эффекты зависимого НЕ воспроизводятся: только одно новое действие
    assert result.reversed_action_ids == [a2.id]
    assert result.amended_action_ids == [a1.id]

    # Нетто: обе передачи погашены, применена одна новая на 2 шт.
    assert await _balance(session, src_sec, product_id) == Decimal("8")
    assert await _balance(session, dst_sec, product_id) == Decimal("2")


# ─── токены и статусы ────────────────────────────────────────────────────────


async def test_amend_rejects_reverse_token_and_vice_versa(
    session: AsyncSession, client
) -> None:
    action, _tid, _ctx = await _setup(session, client, "AMDTOK")

    rev_preview = await reversal_service.preview_reverse(session, action.id)
    with pytest.raises(errors.StalePlanToken):
        await reversal_service.amend(
            session,
            action.id,
            changes={"quantity": "3"},
            plan_token=rev_preview.plan_token,
        )

    amd_preview = await reversal_service.preview_amend(
        session, action.id, {"quantity": "3"}
    )
    with pytest.raises(errors.StalePlanToken):
        await reversal_service.reverse(session, action.id, plan_token=amd_preview.plan_token)


async def test_amend_stale_when_world_changed(session: AsyncSession, client) -> None:
    action, _tid, ctx = await _setup(session, client, "AMDSTL")

    preview = await reversal_service.preview_amend(
        session, action.id, {"quantity": "3"}
    )
    await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("1"),
        actor_id=ctx["user"].id,
        idempotency_key="amdstl:t2",
    )
    await session.commit()

    with pytest.raises(errors.StalePlanToken):
        await reversal_service.amend(
            session,
            action.id,
            changes={"quantity": "3"},
            plan_token=preview.plan_token,
        )


async def test_amend_changes_must_match_preview(session: AsyncSession, client) -> None:
    action, _tid, _ctx = await _setup(session, client, "AMDCHG")
    preview = await reversal_service.preview_amend(
        session, action.id, {"quantity": "3"}
    )
    with pytest.raises(errors.StalePlanToken):
        await reversal_service.amend(
            session,
            action.id,
            changes={"quantity": "9"},  # ≠ подписанному в токене
            plan_token=preview.plan_token,
        )


async def test_amend_already_reversed_and_not_allowed(
    session: AsyncSession, client
) -> None:
    action, _tid, _ctx = await _setup(session, client, "AMDACT")

    await reversal_service.reverse(
        session, action.id, plan_token=(await reversal_service.preview_reverse(session, action.id)).plan_token
    )
    await session.commit()

    with pytest.raises(errors.AlreadyReversed):
        await reversal_service.preview_amend(session, action.id, {"quantity": "3"})

    unknown = Action(action_type="import_remainders", ref_id=999999, actor="test")
    session.add(unknown)
    await session.commit()
    with pytest.raises(errors.NotAllowed):
        await reversal_service.preview_amend(session, unknown.id, {"quantity": "3"})


async def test_amend_invalid_payload_blockers(session: AsyncSession, client) -> None:
    action, _tid, _ctx = await _setup(session, client, "AMDBAD")

    preview = await reversal_service.preview_amend(
        session, action.id, {"quantity": "-5", "hax": 1}
    )
    kinds = [b.kind for b in preview.blockers]
    assert "not_allowed" in kinds
    assert preview.plan_token is None
