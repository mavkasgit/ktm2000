"""Тесты ядра replay (#121): план ветки, чемпионы amend-цепочек,
прямой топологический порядок реплея, will_replay/fingerprint, полный
откат при провале глубокого узла (решения 1-7 спеки t12-replay-amend).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.reversal.stock_compensator as sc_module
from app.models.action_journal import Action, ActionStatus
from app.models.section import Section as SectionModel
from app.models.transfer import Transfer, TransferStatus
from app.models.work_task import WorkTask
from app.reversal import errors
from app.reversal.service import reversal_service
from app.reversal.stock_compensator import StockCompensator
from app.stock.models import Reason, StockBalance, StockTransaction
from app.models.internal_plan import SectionPlanLine
from app.transfers.services import transfer_send
from tests.stock.test_transfer_stage2 import (
    _make_tasks_transferable,
    _make_two_ghp_setup,
)
from tests.test_integrity_invariants import assert_no_invariants_violations

pytestmark = pytest.mark.asyncio


async def _send(
    session: AsyncSession, ctx: dict, *, qty: Decimal, key: str
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


async def _sections(session: AsyncSession, ctx: dict) -> tuple[int, int]:
    frm = await session.get(WorkTask, ctx["from_task_id"])
    to = await session.get(WorkTask, ctx["to_task_id"])
    assert frm is not None and to is not None
    return frm.section_id, to.section_id


async def _bump_line_plan(session: AsyncSession, ctx: dict, planned: Decimal) -> None:
    """Поднять плановый лимит строки: иначе план-кап не пустит реплей
    после увеличенной новой записи корня."""
    frm = await session.get(WorkTask, ctx["from_task_id"])
    assert frm is not None
    line = await session.get(SectionPlanLine, frm.section_plan_line_id)
    assert line is not None
    line.planned_quantity = planned
    await session.flush()


async def _world_counts(session: AsyncSession) -> tuple[int, int, int]:
    acts = await session.scalar(select(func.count(Action.id))) or 0
    txs = await session.scalar(select(func.count(StockTransaction.id))) or 0
    trs = await session.scalar(select(func.count(Transfer.id))) or 0
    return int(acts), int(txs), int(trs)


async def _chain_two(session: AsyncSession, client, sku: str):
    setup = await _make_two_ghp_setup(session, sku=sku, qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    a1, _t1 = await _send(session, ctx, qty=Decimal("5"), key=f"{sku}:t1")
    a2, _t2 = await _send(session, ctx, qty=Decimal("5"), key=f"{sku}:t2")
    a2.depends_on = [a1.id]
    await session.commit()
    return a1, a2, ctx


# ─── build_replay_payload: координаты из проводок ────────────────────────────


async def test_replay_payload_from_transactions_not_transfer_row(
    session: AsyncSession, client
) -> None:
    """Payload собирается из StockTransaction действия, а НЕ из Transfer:
    работает и после мутаций доменной строки."""
    setup = await _make_two_ghp_setup(session, sku="RPLPAY", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    action, tid = await _send(session, ctx, qty=Decimal("5"), key="rplpay:t1")
    await session.commit()

    send_tx = (
        await session.execute(
            select(StockTransaction).where(
                StockTransaction.action_id == action.id,
                StockTransaction.reason == Reason.TRANSFER_SEND,
            )
        )
    ).scalar_one()
    receive_tx = (
        await session.execute(
            select(StockTransaction).where(
                StockTransaction.action_id == action.id,
                StockTransaction.reason == Reason.TRANSFER_RECEIVE,
            )
        )
    ).scalar_one()
    comp = StockCompensator("transfer_send")
    payload = await comp.build_replay_payload(session, action)

    assert payload is not None
    assert payload["quantity"] == Decimal("5")  # из проводки, не 999
    assert payload["from_task_id"] == send_tx.task_id
    assert payload["to_task_id"] == receive_tx.task_id
    assert payload["dimensions"] == send_tx.dimensions


async def test_transfer_cancel_is_not_replayable(session: AsyncSession) -> None:
    comp = StockCompensator("transfer_cancel")
    assert await comp.build_replay_payload(session, Action()) is None


# ─── глубина 3: прямой топологический порядок ────────────────────────────────


async def test_depth3_replays_in_direct_topological_order(
    session: AsyncSession, client
) -> None:
    """Реплей транзитивной ветки глубины 3: зависимость раньше потомка."""
    a1, a2, ctx = await _chain_two(session, client, "RPLD3A")
    await _bump_line_plan(session, ctx, Decimal("30"))

    # Третий узел — независимая передача (свой склад), объявленная
    # зависимой от a2: транзитивный внук.
    stock_sec = (
        await session.execute(
            select(SectionModel).where(SectionModel.code == "T2-STK")
        )
    ).scalar_one()
    stock_sec.code = "RPLD3A-STK"
    await session.commit()

    setup2 = await _make_two_ghp_setup(session, sku="RPLD3AX", qty=Decimal("4"))
    ctx2 = await _make_tasks_transferable(session, client, setup2)
    a3, _t3 = await _send(session, ctx2, qty=Decimal("2"), key="rpld3a:t3")
    a3.depends_on = [a2.id]
    await session.commit()

    src_sec, dst_sec = await _sections(session, ctx)
    product_id = (await session.get(WorkTask, ctx["from_task_id"])).product_id

    preview = await reversal_service.preview_amend(
        session, a1.id, {"quantity": "3"}, cascade=True
    )
    assert preview.blockers == []
    assert [(w.node_id, w.champion_id, w.order) for w in preview.will_replay] == [
        (a2.id, a2.id, 0),
        (a3.id, a3.id, 1),
    ]

    result = await reversal_service.amend(
        session,
        a1.id,
        changes={"quantity": "3"},
        plan_token=preview.plan_token,
        actor_id=ctx["user"].id,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="rpld3")

    # Прямой порядок: реплей a2 создан раньше реплея a3.
    assert len(result.replayed_action_ids) == 2
    rep_a2 = await session.get(Action, result.replayed_action_ids[0])
    rep_a3 = await session.get(Action, result.replayed_action_ids[1])
    assert rep_a2 is not None and rep_a3 is not None
    assert rep_a2.id < rep_a3.id
    assert rep_a2.replay_of_action_id == a2.id
    assert rep_a3.replay_of_action_id == a3.id
    assert rep_a2.status == ActionStatus.ACTIVE
    assert rep_a3.status == ActionStatus.ACTIVE
    await session.refresh(a1)
    await session.refresh(a2)
    await session.refresh(a3)
    assert a1.status == ActionStatus.AMENDED
    assert a2.status == ActionStatus.REVERSED
    assert a3.status == ActionStatus.REVERSED

    # Нетто: второй сетап сеет ещё 10 в тот же склад (итого 20);
    # после amend корень 3 + реплеи 5 и 2 лежат на приёмной стороне.
    assert await _balance(session, src_sec, product_id) == Decimal("10")
    assert await _balance(session, dst_sec, product_id) == Decimal("10")


# ─── чемпион amend-цепочки ────────────────────────────────────────────────────


async def test_amended_dependent_replays_champion(
    session: AsyncSession, client
) -> None:
    """Зависимый был изменён (amend): реплеится голова его цепочки."""
    a1, a2, ctx = await _chain_two(session, client, "RPLCHP")
    src_sec, dst_sec = await _sections(session, ctx)
    product_id = (await session.get(WorkTask, ctx["from_task_id"])).product_id

    # Сначала изменяют сам зависимый: a2 → amended, a2' → активный чемпион.
    p_dep = await reversal_service.preview_amend(session, a2.id, {"quantity": "3"})
    assert p_dep.plan_token
    await reversal_service.amend(
        session,
        a2.id,
        changes={"quantity": "3"},
        plan_token=p_dep.plan_token,
        actor_id=ctx["user"].id,
    )
    champ = (
        await session.execute(
            select(Action).where(Action.amends_action_id == a2.id)
        )
    ).scalar_one()
    assert champ.status == ActionStatus.ACTIVE
    await session.commit()

    preview = await reversal_service.preview_amend(
        session, a1.id, {"quantity": "4"}, cascade=True
    )
    assert preview.blockers == []
    # Ветка: активный dependent — только чемпион; узел a2 уже amended.
    assert {n.id for n in preview.revert} == {a1.id, champ.id}
    assert [(w.node_id, w.champion_id) for w in preview.will_replay] == [
        (champ.id, champ.id)
    ]

    result = await reversal_service.amend(
        session,
        a1.id,
        changes={"quantity": "4"},
        plan_token=preview.plan_token,
        actor_id=ctx["user"].id,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="rplchp")

    assert len(result.replayed_action_ids) == 1
    rep = await session.get(Action, result.replayed_action_ids[0])
    assert rep is not None
    assert rep.replay_of_action_id == champ.id  # чемпион, не мёртвый узел
    assert rep.status == ActionStatus.ACTIVE
    await session.refresh(a1)
    await session.refresh(a2)
    await session.refresh(champ)
    assert a1.status == ActionStatus.AMENDED
    assert a2.status == ActionStatus.AMENDED  # мёртвое звено не тронуто
    assert champ.status == ActionStatus.REVERSED

    assert await _balance(session, src_sec, product_id) == Decimal("3")
    assert await _balance(session, dst_sec, product_id) == Decimal("7")


# ─── не-реплеяемые типы блокируют до изменений ────────────────────────────────


async def test_not_replayable_dependent_blocks_before_mutation(
    session: AsyncSession, client
) -> None:
    a1, _a2, ctx = await _chain_two(session, client, "RPLNR")
    dep = Action(
        action_type="seed_demo", ref_id=None, actor="t", depends_on=[a1.id]
    )
    session.add(dep)
    await session.commit()

    preview = await reversal_service.preview_amend(
        session, a1.id, {"quantity": "4"}, cascade=True
    )
    na = [b for b in preview.blockers if b.kind == "not_allowed"]
    assert na and na[0].node_id == dep.id
    assert preview.plan_token is None  # preview-first: confirm невозможен


# ─── провал глубокого узла → полный откат ────────────────────────────────────


async def test_deep_node_domain_failure_rolls_back_world(
    session: AsyncSession, client, monkeypatch
) -> None:
    """Доменный сбой на глубоком узле реплея: исключение летит вверх,
    TX откатывается целиком, мир не меняется (решение 4 спеки).

    Доменная ошибка инжектируется в write-path передачи только для
    реплей-действий — компенсация ветки и новая запись корня успевают
    исполниться, и откат должен погасить их все.
    """
    from app.transfers import services as transfer_services

    a1, a2, ctx = await _chain_two(session, client, "RPLRBK")
    # plain int: после rollback объекты expired/detached
    aid1, aid2 = a1.id, a2.id
    src_sec, dst_sec = await _sections(session, ctx)
    product_id = (await session.get(WorkTask, ctx["from_task_id"])).product_id
    world_before = await _world_counts(session)

    original_send = transfer_services.transfer_send

    async def _domain_reject(db, **kwargs):
        action = kwargs.get("action")
        if getattr(action, "replay_of_action_id", None) is not None:
            raise ValueError("Transfer quantity exceeds transferable amount")
        return await original_send(db, **kwargs)

    monkeypatch.setattr(
        transfer_services, "transfer_send", _domain_reject
    )

    preview = await reversal_service.preview_amend(
        session, a1.id, {"quantity": "4"}, cascade=True
    )
    assert preview.plan_token

    with pytest.raises(errors.NotAllowed):
        await reversal_service.amend(
            session,
            a1.id,
            changes={"quantity": "4"},
            plan_token=preview.plan_token,
            actor_id=ctx["user"].id,
        )
    monkeypatch.undo()

    await session.rollback()
    session.expunge_all()

    # Мир не изменился: ни одной новой записи, статусы исходные.
    assert await _world_counts(session) == world_before
    a1_db = await session.get(Action, aid1)
    a2_db = await session.get(Action, aid2)
    assert a1_db is not None and a2_db is not None
    assert a1_db.status == ActionStatus.ACTIVE
    assert a2_db.status == ActionStatus.ACTIVE
    assert await _balance(session, src_sec, product_id) == Decimal("0")
    assert await _balance(session, dst_sec, product_id) == Decimal("10")
    await assert_no_invariants_violations(session, context="rplrbk")


async def test_replay_coverage_failure_maps_to_shortfall(
    session: AsyncSession, client, monkeypatch
) -> None:
    """StockValidationError покрытия на узле реплея → CoverageShortfall(node)
    (решение 4); без компенсирующих записей отката."""
    from app.stock.services import StockValidationError

    a1, a2, ctx = await _chain_two(session, client, "RPLCSF")
    world_before = await _world_counts(session)

    original = sc_module.StockCompensator.apply_forward

    async def _boom(self, db, *, action, ref_id, changes, actor, actor_id):
        if getattr(action, "replay_of_action_id", None) is not None:
            raise StockValidationError("недостаточно покрытия для реплея")
        return await original(
            self,
            db,
            action=action,
            ref_id=ref_id,
            changes=changes,
            actor=actor,
            actor_id=actor_id,
        )

    preview = await reversal_service.preview_amend(
        session, a1.id, {"quantity": "4"}, cascade=True
    )
    assert preview.plan_token

    monkeypatch.setattr(sc_module.StockCompensator, "apply_forward", _boom)
    with pytest.raises(errors.CoverageShortfall) as exc_info:
        await reversal_service.amend(
            session,
            a1.id,
            changes={"quantity": "4"},
            plan_token=preview.plan_token,
            actor_id=ctx["user"].id,
        )
    monkeypatch.undo()
    # Узел плана — зависимый, не корень и не новый action.
    assert exc_info.value.node == a2.id

    await session.rollback()
    session.expunge_all()
    assert await _world_counts(session) == world_before
    await assert_no_invariants_violations(session, context="rplcsf")


# ─── stale при изменении ветки ────────────────────────────────────────────────


async def test_stale_token_when_branch_changed_between_preview_and_confirm(
    session: AsyncSession, client
) -> None:
    a1, _a2, ctx = await _chain_two(session, client, "RPLSTL")
    preview = await reversal_service.preview_amend(
        session, a1.id, {"quantity": "4"}, cascade=True
    )
    assert preview.plan_token

    # Ветка изменилась: появился новый активный dependent.
    dep = Action(
        action_type="transfer_send", ref_id=None, actor="t", depends_on=[a1.id]
    )
    session.add(dep)
    await session.commit()

    with pytest.raises(errors.StalePlanToken):
        await reversal_service.amend(
            session,
            a1.id,
            changes={"quantity": "4"},
            plan_token=preview.plan_token,
            actor_id=ctx["user"].id,
        )


# ─── net-инварианты после успешного реплея с доменными мутациями ─────────────


async def test_replay_after_domain_mutation_uses_transaction_coords(
    session: AsyncSession, client
) -> None:
    """Доменно отменённый Transfer старого корня не мешает реплею:
    координаты берутся из проводок (решение 2 спеки)."""
    a1, a2, ctx = await _chain_two(session, client, "RPLDMN")
    src_sec, dst_sec = await _sections(session, ctx)
    product_id = (await session.get(WorkTask, ctx["from_task_id"])).product_id

    preview = await reversal_service.preview_amend(
        session, a1.id, {"to_task_id": ctx["to_task_id"]}, cascade=True
    )
    assert preview.blockers == []
    result = await reversal_service.amend(
        session,
        a1.id,
        changes={"to_task_id": ctx["to_task_id"]},
        plan_token=preview.plan_token,
        actor_id=ctx["user"].id,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="rpldmn")

    assert len(result.replayed_action_ids) == 1
    rep = await session.get(Action, result.replayed_action_ids[0])
    assert rep is not None
    new_transfer = await session.get(Transfer, rep.ref_id)
    assert new_transfer is not None
    assert new_transfer.status == TransferStatus.accepted
    assert await _balance(session, src_sec, product_id) == Decimal("0")
    assert await _balance(session, dst_sec, product_id) == Decimal("10")
