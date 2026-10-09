"""Каскадный amend: покрытие по виртуальному состоянию остатков (#321).

Остаток скоупа #274: `preview_reverse` моделирует виртуальное состояние
остатков (компенсации проходятся в обратном топологическом порядке), а
`preview_amend` проверял каждый узел против текущего склада — та же форма,
которую #274 признал ложной.

Здесь класс #274 воспроизведён на amend-пути БЕЗ засева остатка: корень —
передача `transfer_send`, зависимый — `task_complete` на приёмной задаче,
который выедает принесённый материал. Компенсация корня берёт материал с
приёмного участка (его `to_location`), но тот пуст — вернуть его может только
откат зависимого, который идёт первым.

`mavkasgit/ktm2000#321` называет цепочкой `complete → final_release →
return_to_stock`, но amend существует только у `StockCompensator`
(transfer_send/transfer_cancel): попытка `preview_amend` на `task_complete`
отвечает `NotAllowed` («amend не поддерживается для action_type=task_complete»).
Поэтому воспроизведение — на amendable-корне с тем же классом дефицита;
цепочка task-действий остаётся непроходимой для amend by design (тикет #115).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from app.models.action_journal import Action
from app.reversal.service import reversal_service
from app.services.shopfloor.operations_tasks import complete_task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers.transfers import _make_tasks_transferable, _make_two_ghp_setup
from tests.reversal.test_amend_core import _send_transfer
from tests.stock.helpers import FAKE_SCRAP_POLICY
from tests.test_integrity_invariants import assert_no_invariants_violations

pytestmark = pytest.mark.asyncio


async def _transfer_root_with_completed_receiver(
    session: AsyncSession, client, *, sku: str, qty: Decimal = Decimal(5)
) -> tuple[Action, Action, dict]:
    """Передача src→dst, затем завершение приёмной задачи (выедает приход).

    Возвращает (действие передачи, действие завершения, контекст задач).
    Никакого обходного засева в группу приёмного участка здесь нет: остаток
    на нём создаёт сама передача, а исчерпывает — завершение.
    """
    setup = await _make_two_ghp_setup(session, sku=sku, qty=Decimal(10))
    ctx = await _make_tasks_transferable(session, client, setup)
    send, _transfer_id = await _send_transfer(
        session, ctx, qty=qty, key=f"{sku}:t1"
    )
    await complete_task(
        session,
        task_id=ctx["to_task_id"],
        good_quantity=qty,
        defect_quantity=Decimal(0),
        actor_id=ctx["user"].id,
        defect_reason=None,
        **FAKE_SCRAP_POLICY,
    )
    await session.commit()
    complete = (
        await session.execute(
            select(Action).where(
                Action.action_type == "task_complete",
                Action.ref_id == ctx["to_task_id"],
            )
        )
    ).scalar_one()
    return send, complete, ctx


async def test_amend_cascade_covers_root_from_dependent_revert(
    session: AsyncSession, client
) -> None:
    """Фальшивого CoverageShortfall нет: покрытие корня даёт откат зависимого."""
    send, complete, _ctx = await _transfer_root_with_completed_receiver(
        session, client, sku="AMDCASC"
    )
    complete.depends_on = [send.id]
    await session.commit()

    preview = await reversal_service.preview_amend(
        session, send.id, {"quantity": "5"}, cascade=True
    )

    assert not preview.blockers, [b.detail for b in preview.blockers]
    assert preview.plan_token
    assert {n.id for n in preview.revert} == {send.id, complete.id}
    await assert_no_invariants_violations(session, context="amd-cascade-cov")


async def test_amend_target_alone_keeps_real_coverage_blocker(
    session: AsyncSession, client
) -> None:
    """Реально нехватающее покрытие остаётся блокером (не глушится виртуальным).

    Приёмная задача уже выела приход, а зависимой связи нет — корень
    откатывается в одиночку и обязан упереться в честный дефицит.
    """
    send, _complete, _ctx = await _transfer_root_with_completed_receiver(
        session, client, sku="AMDREAL"
    )

    preview = await reversal_service.preview_amend(
        session, send.id, {"quantity": "5"}, cascade=True
    )

    kinds = [b.kind for b in preview.blockers]
    assert "coverage" in kinds, kinds
    assert preview.plan_token is None
