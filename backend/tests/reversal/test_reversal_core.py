"""Тесты ядра Reversal (ADR-0019, тикет #114): tree / preview / reverse.

Покрывают:
- tree: поддерево dependents со статусами;
- preview: три зоны (🔴 отменится / ⚪ останется / 🚫 блокировки),
  plan_token не выдаётся при блокировках (preview-first);
- reverse: каскад в обратном топологическом порядке, пропуск уже отменённых;
- StalePlanToken при изменении мира между preview и confirm;
- CoverageShortfall при нехватке покрытия хвоста;
- AlreadyReversed (в т.ч. доменно-отменённая передача), NotAllowed;
- полный chain при нескольких dependents; активные внуки отменённого узла;
- сохранение quality_state в коррекции передачи;
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
from app.reversal.service import Blocker, reversal_service
from app.stock import StockCommand, StockCommandService
from app.stock.models import Reason, StockBalance, StockTransaction
from app.transfers.services import cancel_transfer, correct_transfer, transfer_send
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

    # Без каскада: цель в 🔴, зависимые полной цепочкой в 🚫,
    # plan_token НЕ выдаётся (preview-first).
    preview = await reversal_service.preview_reverse(session, fx["a1"].id)
    assert [n.id for n in preview.revert] == [fx["a1"].id]
    assert preview.blockers and preview.blockers[0].kind == "has_dependents"
    assert preview.blockers[0].chain == [fx["a2"].id]
    assert preview.plan_token is None

    # С каскадом: обе в 🔴, блокировок нет, ⚪ пуст, токен выдан.
    cascade = await reversal_service.preview_reverse(session, fx["a1"].id, cascade=True)
    assert {n.id for n in cascade.revert} == {fx["a1"].id, fx["a2"].id}
    assert cascade.blockers == []
    assert cascade.stays == []
    assert cascade.plan_token


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



async def _chain_of_three(session: AsyncSession, client, sku: str) -> dict:
    setup = await _make_two_ghp_setup(session, sku=sku, qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    a1 = await _send_transfer(session, ctx, qty=Decimal("5"), key=f"{sku}:t1")
    a2 = await _send_transfer(session, ctx, qty=Decimal("5"), key=f"{sku}:t2")
    a2.depends_on = [a1.id]
    await session.commit()

    # Второй сетап сеет секцию с тем же кодом "T2-STK" — переименуем первую.
    from app.models.section import Section as SectionModel

    stock_sec = (
        await session.execute(select(SectionModel).where(SectionModel.code == "T2-STK"))
    ).scalar_one()
    stock_sec.code = f"{sku}-STK"
    await session.commit()

    # Третья передача — независимая, объявлена зависимой от a2.
    setup2 = await _make_two_ghp_setup(session, sku=f"{sku}X", qty=Decimal("4"))
    ctx2 = await _make_tasks_transferable(session, client, setup2)
    a3 = await _send_transfer(session, ctx2, qty=Decimal("2"), key=f"{sku}:t3")
    a3.depends_on = [a2.id]
    await session.commit()
    await assert_no_invariants_violations(session, context=f"{sku}-chain3")
    return {"ctx": ctx, "a1": a1, "a2": a2, "a3": a3}


async def test_full_chain_collected_without_break(session: AsyncSession, client) -> None:
    fx = await _chain_of_three(session, client, "RVCHAIN")

    # Без каскада chain полная: и прямой dependent, и транзитивный внук.
    preview = await reversal_service.preview_reverse(session, fx["a1"].id)
    dep_blocker = next(b for b in preview.blockers if b.kind == "has_dependents")
    assert set(dep_blocker.chain) == {fx["a2"].id, fx["a3"].id}


async def test_orphan_grandchildren_visible_in_zones(session: AsyncSession, client) -> None:
    """Активный внук отменённого узла не теряется из трёх зон."""
    fx = await _chain_of_three(session, client, "RVORPH")

    # a2 отменён; его активный dependent a3 должен попасть в 🚫.
    fx["a2"].status = ActionStatus.REVERSED
    await session.commit()

    preview = await reversal_service.preview_reverse(session, fx["a1"].id, cascade=True)
    # ⚪: отменённый a2 пропущен.
    assert [n.id for n in preview.stays] == [fx["a2"].id]
    # 🚫: активный внук a3 виден как блокировка already_reversed.
    orphan_blockers = [b for b in preview.blockers if b.node_id == fx["a3"].id]
    assert orphan_blockers and orphan_blockers[0].kind == "already_reversed"
    # Ни один узел не потерян: a1 и a2 учтены в зонах.
    zone_ids = {n.id for n in preview.revert} | {n.id for n in preview.stays}
    assert zone_ids == {fx["a1"].id, fx["a2"].id}
    assert preview.plan_token is None


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
    shortfall = next(b for b in preview.blockers if b.kind == "coverage")
    assert shortfall.deficit == Decimal("4")
    assert shortfall.node_id == action.id
    # Preview-first: токен при блокировке не выдаётся.
    assert preview.plan_token is None
    # Confirm невозможен до повторного preview.
    with pytest.raises(errors.StalePlanToken):
        await reversal_service.reverse(session, action.id, plan_token=None)

    # Типизированная ошибка CoverageShortfall — контрактный диспетч
    # сервиса (_raise_blockers по kind).
    with pytest.raises(errors.CoverageShortfall) as ei:
        reversal_service._raise_blockers(
            [
                Blocker(
                    kind="coverage",
                    node_id=action.id,
                    detail="недостаточно покрытия",
                    deficit=Decimal("4"),
                )
            ]
        )
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


async def test_preview_domain_cancelled_transfer_blocked(
    session: AsyncSession, client,
) -> None:
    """Доменно-отменённая передача: preview 🚫 already_reversed,
    plan_token не выдаётся, confirm невозможен."""
    setup = await _make_two_ghp_setup(session, sku="RVDOMC", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    action = await _send_transfer(session, ctx, qty=Decimal("3"), key="rvdomc:t1")
    await session.commit()

    await cancel_transfer(
        session, transfer_id=action.ref_id, actor_id=ctx["user"].id
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="rvdomc-cancel")

    preview = await reversal_service.preview_reverse(session, action.id)
    kinds = {b.kind for b in preview.blockers}
    assert "already_reversed" in kinds
    assert preview.plan_token is None
    # Запись журнала при доменной отмене остаётся active — блокер даёт
    # именно доменное состояние Transfer.
    assert action.status == ActionStatus.ACTIVE

    with pytest.raises(errors.StalePlanToken):
        await reversal_service.reverse(session, action.id, plan_token="forged.token")


async def test_not_allowed_for_unknown_action_type(
    session: AsyncSession, client,
) -> None:
    setup = await _make_two_ghp_setup(session, sku="RVNA", qty=Decimal("10"))
    await _make_tasks_transferable(session, client, setup)
    action = Action(action_type="nonexistent_type", ref_id=999999, actor="test")
    session.add(action)
    await session.commit()

    preview = await reversal_service.preview_reverse(session, action.id)
    assert {b.kind for b in preview.blockers} == {"not_allowed"}
    assert preview.plan_token is None
    with pytest.raises(errors.StalePlanToken):
        await reversal_service.reverse(session, action.id, plan_token="garbage.token")


async def test_not_found_blocker_is_distinct(session: AsyncSession) -> None:
    """not_found ≠ already_reversed: ref без записи в журнале."""
    from app.reversal.stock_compensator import StockCompensator

    comp = StockCompensator("transfer_send")
    check = await comp.check(session, ref_id=987654)
    assert not check.ok
    assert check.blockers[0].kind == "not_found"
    assert check.node_id is None  # сентинел -1 убран
    # Диспетч по kind: not_found → ValueError (маппится в 404), а не в 409.
    with pytest.raises(ValueError):
        reversal_service._raise_blockers(
            [Blocker(kind="not_found", node_id=None, detail="нет Transfer")]
        )


async def test_correct_transfer_preserves_quality_state(
    session: AsyncSession, client,
) -> None:
    """Коррекция количества сохраняет quality_state исходных проводок:
    баланс ключуется по (product, location, quality_state, dimensions)."""
    from app.models.transfer import Transfer, TransferStatus
    from app.stock.models import QualityState

    setup = await _make_two_ghp_setup(session, sku="RVQ", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    user = ctx["user"]
    from_task = await session.get(WorkTask, ctx["from_task_id"])
    to_task = await session.get(WorkTask, ctx["to_task_id"])

    # Scrap-остаток на участке-источнике.
    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=from_task.product_id,
            quantity=Decimal("3"),
            reason=Reason.MANUAL_IN,
            to_location_id=from_task.section_id,
            quality_state=QualityState.SCRAP,
            created_by=user.id,
        ),
    )
    await session.flush()

    # Ручная принятая передача со scrap-качеством проводок.
    transfer = Transfer(
        transfer_no="RVQ-T1",
        from_task_id=from_task.id,
        to_task_id=to_task.id,
        from_section_id=from_task.section_id,
        to_section_id=to_task.section_id,
        product_id=from_task.product_id,
        sent_quantity=Decimal("3"),
        accepted_quantity=Decimal("3"),
        status=TransferStatus.accepted,
    )
    session.add(transfer)
    await session.flush()
    send_tx = await svc.record(
        session,
        StockCommand(
            product_id=from_task.product_id,
            quantity=Decimal("3"),
            reason=Reason.TRANSFER_SEND,
            from_location_id=from_task.section_id,
            to_location_id=to_task.section_id,
            task_id=from_task.id,
            transfer_id=transfer.id,
            quality_state=QualityState.SCRAP,
            created_by=user.id,
        ),
    )
    await svc.record(
        session,
        StockCommand(
            product_id=from_task.product_id,
            quantity=Decimal("3"),
            reason=Reason.TRANSFER_RECEIVE,
            task_id=to_task.id,
            transfer_id=transfer.id,
            quality_state=QualityState.SCRAP,
            created_by=user.id,
        ),
    )
    action = Action(
        action_type="transfer_send", ref_id=transfer.id, actor="test"
    )
    session.add(action)
    await session.commit()

    await correct_transfer(
        session,
        transfer_id=transfer.id,
        new_quantity=Decimal("1"),
        actor_id=user.id,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="rvq-correct")

    txs = (
        await session.execute(
            select(StockTransaction)
            .where(StockTransaction.transfer_id == transfer.id)
            .order_by(StockTransaction.id)
        )
    ).scalars().all()
    # 2 исходных + 2 компенсации + 2 новых = 6; компенсации и новая пара
    # наследуют scrap-качество исходных (баланс ключуется по качеству).
    assert len(txs) == 6
    for tx in txs:
        if tx.reverses_id is not None or tx.quantity == Decimal("1"):
            assert tx.from_quality_state == QualityState.SCRAP
            assert tx.to_quality_state == QualityState.SCRAP
    # Исходные проводки нетронуты.
    orig = await session.get(StockTransaction, send_tx.id)
    assert orig.quantity == Decimal("3")
    assert orig.from_quality_state == QualityState.SCRAP
