"""Тесты единой политики резолва узла действия (ADR-0021, тикет #130).

Покрывает:
- трихотомию фолбэка по паре (action_type, ref_id) по АКТИВНЫМ действиям:
  0 → NotFound, ровно 1 → Resolved, больше 1 → Ambiguous(candidates);
- старшинство action_id: передан — строго этот узел, даже если пара
  неоднозначна; чужой action_type или несуществующий id → NotFound;
- ref_id=None без action_id → NotFound; с action_id — резолвится;
- инвариант transfer-типов (уникальный ref_id): активное действие ровно
  одно на живой паре и ноль после отката;
- сценарий дубля (#130): два активных действия одной пары → check()
  компенсатора без id даёт блокер ambiguous с обоими id, plan() →
  ValueError, confirm-диспетч поднимает NotAllowed.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_journal import Action, ActionStatus
from app.reversal import errors
from app.reversal.resolver import (
    Ambiguous,
    NotFound,
    Resolved,
    resolve_action,
)
from app.reversal.service import Blocker, reversal_service
from app.reversal.stock_compensator import StockCompensator
from app.services.action_journal_service import action_journal_service
from app.transfers.services import transfer_send
from tests.stock.test_transfer_stage2 import (
    _make_tasks_transferable,
    _make_two_ghp_setup,
)

pytestmark = pytest.mark.asyncio


async def test_trichotomy_by_pair(session: AsyncSession) -> None:
    """Фолбэк по паре без action_id — строгая трихотомия по активным."""
    base = 777_000

    # 0 записей вообще → NotFound.
    r0 = await resolve_action(
        session, action_type="task_complete", ref_id=base + 1, action_id=None
    )
    assert isinstance(r0, NotFound)

    # Ровно 1 активный → Resolved.
    j1 = await action_journal_service.log(
        session, action_type="task_complete", ref_id=base + 2
    )
    r1 = await resolve_action(
        session, action_type="task_complete", ref_id=base + 2, action_id=None
    )
    assert isinstance(r1, Resolved)
    assert r1.action.id == j1.id

    # Единственная запись в статусе reversed = 0 АКТИВНЫХ → NotFound.
    j_rev = await action_journal_service.log(
        session, action_type="task_complete", ref_id=base + 3
    )
    j_rev.status = ActionStatus.REVERSED
    await session.flush()
    r_rev = await resolve_action(
        session, action_type="task_complete", ref_id=base + 3, action_id=None
    )
    assert isinstance(r_rev, NotFound)

    # Больше одного активного → Ambiguous с отсортированными кандидатами.
    k1 = await action_journal_service.log(
        session, action_type="task_complete", ref_id=base + 4
    )
    k2 = await action_journal_service.log(
        session, action_type="task_complete", ref_id=base + 4
    )
    r2 = await resolve_action(
        session, action_type="task_complete", ref_id=base + 4, action_id=None
    )
    assert isinstance(r2, Ambiguous)
    assert r2.candidates == sorted([k1.id, k2.id])


async def test_action_id_is_senior_over_pair(session: AsyncSession) -> None:
    """action_id старше пары: при неоднозначной паре резолвится строго
    указанный узел (раньше StockCompensator молча брал «первый»)."""
    ref = 888_001
    m1 = await action_journal_service.log(
        session, action_type="task_complete", ref_id=ref
    )
    m2 = await action_journal_service.log(
        session, action_type="task_complete", ref_id=ref
    )

    by_first = await resolve_action(
        session, action_type="task_complete", ref_id=ref, action_id=m1.id
    )
    assert isinstance(by_first, Resolved)
    assert by_first.action.id == m1.id

    by_second = await resolve_action(
        session, action_type="task_complete", ref_id=ref, action_id=m2.id
    )
    assert isinstance(by_second, Resolved)
    assert by_second.action.id == m2.id


async def test_action_id_foreign_type_or_missing_is_not_found(
    session: AsyncSession,
) -> None:
    """Чужой action_type у узла и несуществующий id — честный NotFound."""
    j = await action_journal_service.log(
        session, action_type="task_complete", ref_id=888_002
    )
    wrong_type = await resolve_action(
        session, action_type="transfer_cancel", ref_id=j.ref_id, action_id=j.id
    )
    assert isinstance(wrong_type, NotFound)

    missing = await resolve_action(
        session, action_type="task_complete", ref_id=None, action_id=987_654_321
    )
    assert isinstance(missing, NotFound)


async def test_ref_none_resolves_only_by_action_id(session: AsyncSession) -> None:
    """ref_id=None (manual_adjustment): без action_id — NotFound,
    с action_id — строго этот узел."""
    no_address = await resolve_action(
        session, action_type="manual_adjustment", ref_id=None, action_id=None
    )
    assert isinstance(no_address, NotFound)

    j = await action_journal_service.log(
        session, action_type="manual_adjustment", ref_id=None
    )
    by_id = await resolve_action(
        session, action_type="manual_adjustment", ref_id=None, action_id=j.id
    )
    assert isinstance(by_id, Resolved)
    assert by_id.action.id == j.id


# ─── Инвариант transfer-типов: уникальный ref_id ↔ ровно один активный ──────


async def _send(session: AsyncSession, ctx: dict, qty: Decimal, key: str) -> int:
    result = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=qty,
        actor_id=ctx["user"].id,
        idempotency_key=key,
    )
    await session.commit()
    return result["transfer_id"]


async def _active_count(
    session: AsyncSession, action_type: str, ref_id: int
) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(Action)
        .where(
            Action.action_type == action_type,
            Action.ref_id == ref_id,
            Action.status == ActionStatus.ACTIVE,
        )
    )


async def test_transfer_pair_single_active_through_reverse(
    session: AsyncSession, client
) -> None:
    """Инвариант (ADR-0021): у типа с уникальным ref_id активное действие
    ровно одно на живой паре; после отката — ноль, фолбэк честно NotFound."""
    setup = await _make_two_ghp_setup(session, sku="RSLVINV", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    tid = await _send(session, ctx, Decimal("3"), "rslvinv:t1")

    assert await _active_count(session, "transfer_send", tid) == 1
    res = await resolve_action(
        session, action_type="transfer_send", ref_id=tid, action_id=None
    )
    assert isinstance(res, Resolved)
    action = res.action

    preview = await reversal_service.preview_reverse(session, action.id)
    assert not preview.blockers
    await reversal_service.reverse(
        session, action.id, plan_token=preview.plan_token, actor="tester"
    )
    await session.commit()

    assert await _active_count(session, "transfer_send", tid) == 0
    after = await resolve_action(
        session, action_type="transfer_send", ref_id=tid, action_id=None
    )
    assert isinstance(after, NotFound)


async def test_transfer_cancel_pair_policy(session: AsyncSession) -> None:
    """Инвариант для transfer_cancel (ADR-0021): пара с ровно одним
    активным резолвится; дубли активных → ambiguous с обоими id.

    Живого пути создания transfer_cancel нет: cancel_transfer (#124)
    переиспользует reverse от transfer_send и доменных записей этого типа
    не пишет — тип остаётся покрытым компенсатором для legacy-строк,
    поэтому политика проверяется на уровне seam'а резолва/компенсатора.
    """
    from app.reversal.resolver import Ambiguous as AmbiguousResult

    ref = 888_100
    comp = StockCompensator("transfer_cancel")

    c1 = await action_journal_service.log(
        session, action_type="transfer_cancel", ref_id=ref
    )
    single = await comp.check(session, ref)
    assert single.ok and single.node_id == c1.id

    c2 = await action_journal_service.log(
        session, action_type="transfer_cancel", ref_id=ref
    )
    dup = await comp.check(session, ref)
    assert not dup.ok
    [blocker] = dup.blockers
    assert blocker.kind == "ambiguous"
    assert str(c1.id) in blocker.detail and str(c2.id) in blocker.detail

    res = await resolve_action(
        session, action_type="transfer_cancel", ref_id=ref, action_id=None
    )
    assert isinstance(res, AmbiguousResult)
    assert res.candidates == sorted([c1.id, c2.id])


# ─── Сценарий дубля: ambiguous блокер + заблокированный confirm ─────────────


async def test_duplicate_pair_ambiguous_blocker_and_confirm_blocked(
    session: AsyncSession, client
) -> None:
    """Сценарий #130: два активных действия одной пары (transfer_send,
    tid). Вызывающий без action_id получает блокер ambiguous с обоими id,
    plan() отказывает с ValueError; confirm-диспетч поднимает NotAllowed.
    По action_id узел резолвится строго (id старше пары).

    Уровень seam'а — осознанно: preview_reverse/preview_amend всегда
    передают node.id (id старше пары), поэтому на сервисной границе
    неоднозначность недостижима ПО ПОСТРОЕНИЮ; источник блокеров preview —
    CheckBlocker компенсатора, а confirm-диспетч (_raise_blockers) —
    единственная точка принуждения «confirm заблокирован». Прямые вызовы
    check()/plan() — это контракт легаси-caller'ов без id, ради которых
    политика и введена.
    """
    setup = await _make_two_ghp_setup(session, sku="RSLVDUP", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    tid = await _send(session, ctx, Decimal("3"), "rslvdup:t1")
    a1 = (
        await session.execute(
            select(Action).where(
                Action.action_type == "transfer_send", Action.ref_id == tid
            )
        )
    ).scalar_one()
    # Аномалия данных: второй АКТИВНЫЙ узел той же пары (в проде such дубли
    # не возникают по построению amend/replay, но констрейнта в БД нет).
    a2 = await action_journal_service.log(
        session, action_type="transfer_send", ref_id=tid
    )
    await session.commit()

    comp = StockCompensator("transfer_send")

    # Прежний вызывающий без id: больше НЕ «первый попавшийся» — ambiguous.
    legacy = await comp.check(session, tid)
    assert not legacy.ok
    [blocker] = legacy.blockers
    assert blocker.kind == "ambiguous"
    assert str(a1.id) in blocker.detail and str(a2.id) in blocker.detail

    # Id старше пары: строгий резолв указанного узла.
    strict = await comp.check(session, tid, action_id=a2.id)
    assert strict.ok and strict.node_id == a2.id

    # plan(): неуспех резолва — обычный ValueError на границе.
    with pytest.raises(ValueError) as exc_info:
        await comp.plan(session, tid, hard=False)
    assert str(a1.id) in str(exc_info.value) and str(a2.id) in str(exc_info.value)

    # Confirm заблокирован: диспетч блокеров поднимает NotAllowed.
    with pytest.raises(errors.NotAllowed):
        reversal_service._raise_blockers(
            [
                Blocker(
                    kind="ambiguous",
                    node_id=a1.id,
                    detail=blocker.detail,
                )
            ]
        )
