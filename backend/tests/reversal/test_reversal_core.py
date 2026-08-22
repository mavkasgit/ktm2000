"""Тесты ядра Reversal (ADR-0019, тикет #114): tree / preview / reverse.

Покрывают:
- tree: поддерево dependents со статусами;
- preview: три зоны (🔴 отменится / ⚪ останется / 🚫 блокировки);
- reverse: каскад в обратном топологическом порядке, пропуск уже отменённых;
- StalePlanToken при изменении мира между preview и confirm;
- CoverageShortfall при нехватке покрытия хвоста;
- AlreadyReversed / NotAllowed;
- инварианты ledger и остаток ≥ 0 до и после отката.

Зависимости depends_on между действиями в тестах проставляются явно:
бизнес-проводка зависимостей — зона #116.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_journal import Action, ActionStatus
from app.models.work_task import WorkTask
from app.reversal import errors
from app.reversal.service import reversal_service
from app.stock import StockCommand, StockCommandService
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
) -> Action:
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
    return action


async def _balance(session: AsyncSession, location_id: int, product_id: int) -> Decimal:
    return (
        await session.scalar(
            select(func.coalesce(func.sum(StockBalance.balance_qty), 0)).where(
                StockBalance.location_id == location_id,
                StockBalance.product_id == product_id,
            )
        )
    ) or Decimal("0")


async def _chain_of_two(session: AsyncSession, client, sku: str) -> dict:
    """Две передачи с одного источника; вторая зависит от первой."""
    setup = await _make_two_ghp_setup(session, sku=sku, qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    a1 = await _send_transfer(session, ctx, qty=Decimal("5"), key=f"{sku}:t1")
    a2 = await _send_transfer(session, ctx, qty=Decimal("5"), key=f"{sku}:t2")
    a2.depends_on = [a1.id]
    await session.commit()
    await assert_no_invariants_violations(session, context=f"{sku}-setup")
    return {"ctx": ctx, "a1": a1, "a2": a2}


async def test_tree_shows_dependents_with_statuses(session: AsyncSession, client) -> None:
    fx = await _chain_of_two(session, client, "RVTREE")

    tree = await reversal_service.tree(session, fx["a1"].id)
    assert tree.root.id == fx["a1"].id
    assert tree.root.status == "active"
    assert [c.id for c in tree.root.children] == [fx["a2"].id]
    assert tree.total_nodes == 2

    # Лист без зависимых — пустое поддерево.
    leaf = await reversal_service.tree(session, fx["a2"].id)
    assert leaf.root.children == []


async def test_preview_zones_cascade_and_not(session: AsyncSession, client) -> None:
    fx = await _chain_of_two(session, client, "RVPREV")

    # Без каскада: цель в 🔴, зависимая — блокировка 🚫.
    preview = await reversal_service.preview_reverse(session, fx["a1"].id)
    assert [n.id for n in preview.revert] == [fx["a1"].id]
    assert preview.blockers and preview.blockers[0].code == "HasDependentActions"
    assert preview.blockers[0].chain == [fx["a2"].id]
    assert preview.plan_token

    # С каскадом: обе в 🔴, блокировок нет, ⚪ пуст.
    cascade = await reversal_service.preview_reverse(session, fx["a1"].id, cascade=True)
    assert {n.id for n in cascade.revert} == {fx["a1"].id, fx["a2"].id}
    assert cascade.blockers == []
    assert cascade.stays == []


async def test_reverse_cascade_reverse_topological_order(
    session: AsyncSession, client,
) -> None:
    setup = await _make_two_ghp_setup(session, sku="RVORD", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    from_task = await session.get(WorkTask, ctx["from_task_id"])
    to_task = await session.get(WorkTask, ctx["to_task_id"])
    # Базовая линия — состояние мира ДО передач; откат возвращает ровно её.
    bal_src_before = await _balance(session, from_task.section_id, from_task.product_id)
    bal_dst_before = await _balance(session, to_task.section_id, to_task.product_id)
    assert bal_src_before >= 0 and bal_dst_before >= 0

    a1 = await _send_transfer(session, ctx, qty=Decimal("5"), key="rvord:t1")
    a2 = await _send_transfer(session, ctx, qty=Decimal("5"), key="rvord:t2")
    a2.depends_on = [a1.id]
    await session.commit()
    await assert_no_invariants_violations(session, context="rvord-setup")

    preview = await reversal_service.preview_reverse(session, a1.id, cascade=True)
    result = await reversal_service.reverse(
        session, a1.id, plan_token=preview.plan_token, reason="тест"
    )

    # Порядок каскада: a2 (dependent) раньше a1 — обратный топологический.
    assert result.reversed_action_ids == [a2.id, a1.id]

    # Статусы исходных → reversed, проставлен reversed_by_action_id.
    for aid in (a1.id, a2.id):
        a = await session.get(Action, aid)
        assert a.status == ActionStatus.REVERSED
        assert a.reversed_by_action_id is not None
        rev = await session.get(Action, a.reversed_by_action_id)
        assert rev.action_type == "reversal"
        assert rev.reason == "тест"

    # Компенсации: по 2 на каждое действие (SEND + RECEIVE).
    rev_ids = select(Action.id).where(Action.action_type == "reversal")
    comp_count = await session.scalar(
        select(func.count())
        .select_from(StockTransaction)
        .where(
            StockTransaction.reverses_id.is_not(None),
            StockTransaction.action_id.in_(rev_ids),
        )
    )
    assert comp_count == 4

    # Балансы возвращены к состоянию до передач; остаток ≥ 0 до и после.
    bal_src_after = await _balance(session, from_task.section_id, from_task.product_id)
    bal_dst_after = await _balance(session, to_task.section_id, to_task.product_id)
    assert bal_src_after == bal_src_before
    assert bal_dst_after == bal_dst_before
    assert bal_src_after >= 0 and bal_dst_after >= 0
    await assert_no_invariants_violations(session, context="rv-order")


async def test_reverse_skips_already_reversed(session: AsyncSession, client) -> None:
    fx = await _chain_of_two(session, client, "RVSKIP")

    # a2 «уже отменён» ранее.
    fx["a2"].status = ActionStatus.REVERSED
    await session.commit()

    preview = await reversal_service.preview_reverse(session, fx["a1"].id, cascade=True)
    assert [n.id for n in preview.stays] == [fx["a2"].id]

    result = await reversal_service.reverse(
        session, fx["a1"].id, plan_token=preview.plan_token
    )
    assert result.reversed_action_ids == [fx["a1"].id]


async def test_stale_plan_token_when_world_changed(
    session: AsyncSession, client,
) -> None:
    fx = await _chain_of_two(session, client, "RVSTALE")
    ctx = fx["ctx"]

    preview = await reversal_service.preview_reverse(session, fx["a2"].id)
    token = preview.plan_token

    # Мир изменился: новая проводка в ledger (отпечаток устаревает).
    svc = StockCommandService()
    to_task = await session.get(WorkTask, ctx["to_task_id"])
    await svc.record(
        session,
        StockCommand(
            product_id=to_task.product_id,
            quantity=Decimal("1"),
            reason=Reason.MANUAL_IN,
            to_location_id=to_task.section_id,
            created_by=ctx["user"].id,
        ),
    )
    await session.commit()

    with pytest.raises(errors.StalePlanToken):
        await reversal_service.reverse(session, fx["a2"].id, plan_token=token)

    # Подделанная подпись — тоже StalePlanToken.
    fresh = await reversal_service.preview_reverse(session, fx["a2"].id)
    with pytest.raises(errors.StalePlanToken):
        await reversal_service.reverse(
            session, fx["a2"].id, plan_token=fresh.plan_token[:-2] + "zz"
        )


async def test_coverage_shortfall_blocks_reverse(
    session: AsyncSession, client,
) -> None:
    setup = await _make_two_ghp_setup(session, sku="RVCOV", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    action = await _send_transfer(session, ctx, qty=Decimal("5"), key="rvcov:t1")
    await session.commit()

    to_task = await session.get(WorkTask, ctx["to_task_id"])
    # Хвост потреблён: 4 из 5 завершены на приёмном участке.
    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=to_task.product_id,
            quantity=Decimal("4"),
            reason=Reason.COMPLETE,
            from_location_id=to_task.section_id,
            to_location_id=None,
            task_id=to_task.id,
            created_by=ctx["user"].id,
        ),
    )
    await session.commit()

    preview = await reversal_service.preview_reverse(session, action.id)
    shortfall = next(b for b in preview.blockers if b.code == "CoverageShortfall")
    assert shortfall.deficit == Decimal("4")

    with pytest.raises(errors.CoverageShortfall) as ei:
        await reversal_service.reverse(session, action.id, plan_token=preview.plan_token)
    assert ei.value.node == action.id
    assert ei.value.deficit == Decimal("4")

    # Ничего не отменено: действие всё ещё active, инварианты целы.
    await session.commit()
    a = await session.get(Action, action.id)
    assert a.status == ActionStatus.ACTIVE
    await assert_no_invariants_violations(session, context="rv-cov")


async def test_already_reversed(session: AsyncSession, client) -> None:
    setup = await _make_two_ghp_setup(session, sku="RVALRD", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    action = await _send_transfer(session, ctx, qty=Decimal("2"), key="rvalrd:t1")
    await session.commit()

    preview = await reversal_service.preview_reverse(session, action.id)
    await reversal_service.reverse(session, action.id, plan_token=preview.plan_token)
    await session.commit()
    await assert_no_invariants_violations(session, context="rv-alrd")

    with pytest.raises(errors.AlreadyReversed):
        await reversal_service.preview_reverse(session, action.id)


async def test_not_allowed_for_unknown_action_type(
    session: AsyncSession, client,
) -> None:
    setup = await _make_two_ghp_setup(session, sku="RVNA", qty=Decimal("10"))
    await _make_tasks_transferable(session, client, setup)
    action = Action(action_type="import_remainders", ref_id=999999, actor="test")
    session.add(action)
    await session.commit()

    preview = await reversal_service.preview_reverse(session, action.id)
    assert {b.code for b in preview.blockers} == {"NotAllowed"}
    with pytest.raises(errors.NotAllowed):
        await reversal_service.reverse(session, action.id, plan_token=preview.plan_token)
