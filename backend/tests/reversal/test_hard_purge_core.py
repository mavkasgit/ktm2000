"""Тесты hard-чистки скомпенсированных пар (ADR-0019 п.7, тикет #118).

Покрывают:
- dry_run: отчёт пар «исходная+компенсация» + plan_token kind='purge',
  без изменений в ledger;
- confirm: удаление компенсаций, затем исходных (FK reverses_id → источник),
  статус 'purged'; записи action_journal сохраняются (аудит);
- условия отказа (NotAllowed): не reversed, непарность (≠1:1), живые
  зависимые;
- StalePlanToken при изменении мира между dry_run и confirm;
- инварианты net до/после идентичны; assert_no_invariants_violations.
"""
from __future__ import annotations

from decimal import Decimal

import re

import pytest
from sqlalchemy import event, select

from app.models.action_journal import Action, ActionStatus
from app.reversal import errors
from app.reversal.service import reversal_service
from app.stock.models import StockBalance, StockTransaction
from app.transfers.services import transfer_send
from tests.stock.test_transfer_stage2 import (
    _make_tasks_transferable,
    _make_two_ghp_setup,
)
from tests.test_integrity_invariants import assert_no_invariants_violations

pytestmark = pytest.mark.asyncio


async def _reversed_action(session: AsyncSession, client, sku: str) -> Action:
    """Передача, немедленно скомпенсированная обратной (status='reversed')."""
    setup = await _make_two_ghp_setup(session, sku=sku, qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    result = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("4"),
        actor_id=ctx["user"].id,
        idempotency_key=f"{sku}:t1",
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
    preview = await reversal_service.preview_reverse(session, action.id)
    assert not preview.blockers and preview.plan_token
    await reversal_service.reverse(
        session, action.id, plan_token=preview.plan_token, reason="тест #118"
    )
    await session.commit()
    await assert_no_invariants_violations(session, context=f"{sku}-reversed")
    return action


async def _net_by_key(session: AsyncSession) -> dict[tuple[int, int, str], Decimal]:
    """net по (product, локация, качество): приход минус расход по ledger."""
    txs = (
        await session.execute(select(StockTransaction))
    ).scalars().all()
    net: dict[tuple[int, int, str], Decimal] = {}
    for t in txs:
        if t.to_location_id is not None:
            key = (t.product_id, t.to_location_id, str(t.to_quality_state))
            net[key] = net.get(key, Decimal("0")) + t.quantity
        if t.from_location_id is not None:
            key = (t.product_id, t.from_location_id, str(t.from_quality_state))
            net[key] = net.get(key, Decimal("0")) - t.quantity
    return {k: v for k, v in net.items() if v != 0}


async def test_dry_run_report_without_changes(session: AsyncSession, client) -> None:
    action = await _reversed_action(session, client, "HPCORE1")
    src_count = len((await session.execute(select(StockTransaction.id))).all())

    report = await reversal_service.hard_purge(session, action.id, dry_run=True)
    assert report.plan_token

    # Передача = пара проводок SEND+RECEIVE → 2 пары с равными количествами.
    assert len(report.pairs) == 2
    for pair in report.pairs:
        assert pair.source_tx_id != pair.reverse_tx_id
        assert pair.quantity == Decimal("4")
    assert {p.source_tx_id for p in report.pairs}.isdisjoint(
        {p.reverse_tx_id for p in report.pairs}
    )

    # Ничего не удалено, статус не изменился.
    after_count = len((await session.execute(select(StockTransaction.id))).all())
    assert after_count == src_count
    await session.refresh(action)
    assert action.status == ActionStatus.REVERSED


async def test_confirm_deletes_pairs_sets_purged_net_identical(
    session: AsyncSession, client,
) -> None:
    action = await _reversed_action(session, client, "HPCORE2")
    net_before = await _net_by_key(session)
    balances_before = (
        await session.execute(
            select(StockBalance.location_id, StockBalance.product_id,
                   StockBalance.balance_qty)
        )
    ).all()

    dry = await reversal_service.hard_purge(session, action.id, dry_run=True)
    result = await reversal_service.hard_purge(
        session, action.id, dry_run=False, plan_token=dry.plan_token
    )

    assert len(result.deleted_tx_ids) == 2 * len(result.pairs)
    remaining_ids = set(
        (await session.execute(select(StockTransaction.id))).scalars().all()
    )
    assert remaining_ids.isdisjoint(result.deleted_tx_ids)
    # Компенсации исходного действия исчезли вместе с исходными.
    orphaned = (
        await session.execute(
            select(StockTransaction.id).where(
                StockTransaction.reverses_id.in_(result.deleted_tx_ids)
            )
        )
    ).scalar_one_or_none()
    assert orphaned is None

    # Статус purged, запись журнала сохранена (аудит).
    await session.refresh(action)
    assert action.status == ActionStatus.PURGED

    # net до/после идентичен; инварианты ledger не нарушены.
    net_after = await _net_by_key(session)
    assert net_after == net_before
    balances_after = (
        await session.execute(
            select(StockBalance.location_id, StockBalance.product_id,
                   StockBalance.balance_qty)
        )
    ).all()
    assert sorted(balances_after) == sorted(balances_before)
    await assert_no_invariants_violations(session, context="hpcore2-purged")


async def test_confirm_deletes_compensations_before_sources(
    session: AsyncSession, client,
) -> None:
    """Порядок п.4 спеки: сначала компенсации, затем исходные."""
    action = await _reversed_action(session, client, "HPCORE3")
    dry = await reversal_service.hard_purge(session, action.id, dry_run=True)

    deletes: list[set[int]] = []
    eng = session.bind.sync_engine

    def _record(conn, cursor, statement, parameters, context, executemany):
        s = " ".join(statement.split()).lower()
        if s.startswith("delete from stock_transactions"):
            deletes.append({int(m) for m in re.findall(r"\d+", str(parameters))})

    event.listen(eng, "before_cursor_execute", _record)
    try:
        await reversal_service.hard_purge(
            session, action.id, dry_run=False, plan_token=dry.plan_token
        )
    finally:
        event.remove(eng, "before_cursor_execute", _record)

    comp_ids = {p.reverse_tx_id for p in dry.pairs}
    source_ids = {p.source_tx_id for p in dry.pairs}
    assert len(deletes) >= 2
    first_with_comp = next(i for i, ids in enumerate(deletes) if ids & comp_ids)
    first_with_source = next(
        i for i, ids in enumerate(deletes) if ids & source_ids
    )
    assert first_with_comp < first_with_source


async def test_rejects_active_action(session: AsyncSession, client) -> None:
    setup = await _make_two_ghp_setup(session, sku="HPCORE4", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    result = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("2"),
        actor_id=ctx["user"].id,
        idempotency_key="hpcore4:t1",
    )
    action = (
        await session.execute(
            select(Action).where(Action.ref_id == result["transfer_id"])
        )
    ).scalar_one()
    await session.commit()

    with pytest.raises(errors.NotAllowed, match="reversed"):
        await reversal_service.hard_purge(session, action.id, dry_run=True)


async def test_rejects_unpaired_compensations(session: AsyncSession, client) -> None:
    action = await _reversed_action(session, client, "HPCORE5")

    # Вторая компенсация той же исходной проводки ломает парность 1:1.
    orig_id = (
        await session.execute(
            select(StockTransaction.reverses_id).where(
                StockTransaction.reverses_id.is_not(None),
                StockTransaction.action_id != action.id,
            )
        )
    ).first()
    assert orig_id is not None
    dup_source_id = orig_id[0]
    original = await session.get(StockTransaction, dup_source_id)
    session.add(
        StockTransaction(
            product_id=original.product_id,
            from_location_id=original.to_location_id,
            to_location_id=original.from_location_id,
            quantity=original.quantity,
            reason=original.reason,
            from_quality_state=original.to_quality_state,
            to_quality_state=original.from_quality_state,
            reverses_id=dup_source_id,
            created_by=original.created_by,
        )
    )
    await session.commit()

    with pytest.raises(errors.NotAllowed, match="1:1"):
        await reversal_service.hard_purge(session, action.id, dry_run=True)


async def test_rejects_live_dependent(session: AsyncSession, client) -> None:
    action = await _reversed_action(session, client, "HPCORE6")
    dependent = Action(
        action_type="transfer_send", ref_id=None, actor="test",
        depends_on=[action.id],
    )
    session.add(dependent)
    await session.commit()

    with pytest.raises(errors.NotAllowed, match=f"#{dependent.id}"):
        await reversal_service.hard_purge(session, action.id, dry_run=True)


async def test_rejects_transitive_live_dependent(session, client) -> None:
    """Цепочка A←B(reversed)←C(active): прямой зависимый уже отменён,
    но живой узел глубже в цепочке блокирует чистку."""
    action = await _reversed_action(session, client, "HPCORE8")
    mid = Action(
        action_type="transfer_send", ref_id=None, actor="test",
        depends_on=[action.id], status=ActionStatus.REVERSED,
    )
    session.add(mid)
    await session.commit()
    deep = Action(
        action_type="transfer_send", ref_id=None, actor="test",
        depends_on=[mid.id],
    )
    session.add(deep)
    await session.commit()

    with pytest.raises(errors.NotAllowed, match=f"#{deep.id}"):
        await reversal_service.hard_purge(session, action.id, dry_run=True)


async def test_purge_passes_after_deep_dependent_reversed(session, client) -> None:
    """После reverse глубокого узла C вся цепочка reversed → purge проходит."""
    action = await _reversed_action(session, client, "HPCORE9")
    mid = Action(
        action_type="transfer_send", ref_id=None, actor="test",
        depends_on=[action.id], status=ActionStatus.REVERSED,
    )
    session.add(mid)
    await session.commit()
    deep = Action(
        action_type="transfer_send", ref_id=None, actor="test",
        depends_on=[mid.id],
    )
    session.add(deep)
    await session.commit()

    # Пока C жив — отказ; после reverse цепочка чистится.
    with pytest.raises(errors.NotAllowed):
        await reversal_service.hard_purge(session, action.id, dry_run=True)
    deep.status = ActionStatus.REVERSED
    await session.commit()

    report = await reversal_service.hard_purge(session, action.id, dry_run=True)
    assert len(report.pairs) == 2
    await session.refresh(action)
    assert action.status == ActionStatus.REVERSED


async def test_confirm_with_stale_token_rejected(session: AsyncSession, client) -> None:
    action = await _reversed_action(session, client, "HPCORE7")
    dry = await reversal_service.hard_purge(session, action.id, dry_run=True)

    # Мир изменился: новая запись журнала меняет fingerprint (max Action.id).
    session.add(Action(action_type="transfer_send", ref_id=None, actor="world"))
    await session.commit()

    with pytest.raises(errors.StalePlanToken):
        await reversal_service.hard_purge(
            session, action.id, dry_run=False, plan_token=dry.plan_token
        )
    await session.refresh(action)
    assert action.status == ActionStatus.REVERSED
