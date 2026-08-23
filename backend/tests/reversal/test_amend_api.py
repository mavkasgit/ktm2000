"""REST-тесты amend (тикет #115): POST /actions/{id}/preview-amend и /amend.

Маппинг ошибок зеркален reverse: AlreadyReversed/StalePlanToken → 409,
HasDependentActions/CoverageShortfall → 409, NotAllowed → 403,
неизвестное действие → 404.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_journal import Action, ActionStatus
from app.models.work_task import WorkTask
from app.reversal.stock_compensator import StockCompensator
from app.stock.models import QualityState, Reason
from app.stock.services import StockCommand, StockCommandService
from app.transfers.services import transfer_send
from tests.stock.test_transfer_stage2 import (
    _make_tasks_transferable,
    _make_two_ghp_setup,
)
from tests.test_integrity_invariants import (
    _auth_headers,
    assert_no_invariants_violations,
)

pytestmark = pytest.mark.asyncio


async def _setup_action(
    session: AsyncSession, client, sku: str, *, qty=Decimal("3")
) -> tuple[Action, dict]:
    setup = await _make_two_ghp_setup(session, sku=sku, qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    result = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=qty,
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
    await session.commit()
    await assert_no_invariants_violations(session, context=f"{sku}-setup")
    return action, ctx


async def test_preview_and_amend_endpoints(session: AsyncSession, client) -> None:
    action, ctx = await _setup_action(session, client, "AMDAP1")
    headers = _auth_headers(ctx["user"])

    resp = await client.post(
        f"/api/actions/{action.id}/preview-amend",
        json={"changes": {"quantity": "4"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    preview = resp.json()
    assert preview["revert"][0]["id"] == action.id
    assert preview["blockers"] == []
    assert preview["plan_token"]

    resp = await client.post(
        f"/api/actions/{action.id}/amend",
        json={"plan_token": preview["plan_token"], "reason": "не то количество"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["action_id"] == action.id
    assert result["new_action_id"]
    assert result["new_ref_id"]
    assert len(result["compensated_tx_ids"]) == 2
    assert result["amended_action_ids"] == [action.id]
    assert result["reversed_action_ids"] == []

    # Старое действие amended; новое связано через amends_action_id
    await session.refresh(action)
    assert action.status == ActionStatus.AMENDED
    new_action = await session.get(Action, result["new_action_id"])
    assert new_action.amends_action_id == action.id

    await session.commit()
    await assert_no_invariants_violations(session, context="amdapi-happy")
    # Повторный amend — AlreadyReversed → 409
    again = await client.post(
        f"/api/actions/{action.id}/preview-amend",
        json={"changes": {"quantity": "4"}},
        headers=headers,
    )
    assert again.status_code == 409


async def test_preview_amend_coverage_blocker_no_token(
    session: AsyncSession, client
) -> None:
    """D7-A: дефицит покрытия новой записи — блокер, токен не выдаётся."""
    action, ctx = await _setup_action(session, client, "AMDAP2")
    resp = await client.post(
        f"/api/actions/{action.id}/preview-amend",
        json={"changes": {"quantity": "1000"}},
        headers=_auth_headers(ctx["user"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert any(b["kind"] == "coverage" for b in body["blockers"])
    assert body["plan_token"] is None


async def test_amend_with_reverse_token_maps_409(
    session: AsyncSession, client
) -> None:
    action, ctx = await _setup_action(session, client, "AMDAP3")
    headers = _auth_headers(ctx["user"])

    rev = await client.post(
        f"/api/actions/{action.id}/preview-reverse",
        json={"cascade": False},
        headers=headers,
    )
    token = rev.json()["plan_token"]

    resp = await client.post(
        f"/api/actions/{action.id}/amend",
        json={"plan_token": token},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text


async def test_amend_unknown_action_maps_404(session: AsyncSession, client) -> None:
    action, ctx = await _setup_action(session, client, "AMDAP4")
    headers = _auth_headers(ctx["user"])
    missing = await client.post(
        "/api/actions/999999/preview-amend",
        json={"changes": {"quantity": "1"}},
        headers=headers,
    )
    assert missing.status_code == 404

    unknown = Action(action_type="import_remainders", ref_id=999999, actor="test")
    session.add(unknown)
    await session.commit()
    await assert_no_invariants_violations(session, context="amdapi-notfound")
    not_allowed = await client.post(
        f"/api/actions/{unknown.id}/preview-amend",
        json={"changes": {"quantity": "1"}},
        headers=headers,
    )
    assert not_allowed.status_code == 403, not_allowed.text


async def test_amend_invalid_payload_preview_blocked(
    session: AsyncSession, client
) -> None:
    action, ctx = await _setup_action(session, client, "AMDAP5")
    headers = _auth_headers(ctx["user"])
    resp = await client.post(
        f"/api/actions/{action.id}/preview-amend",
        json={"changes": {"quantity": "-1", "evil_field": True}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert any(b["kind"] == "not_allowed" for b in body["blockers"])
    assert body["plan_token"] is None

    # Confirm с подделкой — StalePlanToken → 409.
    resp = await client.post(
        f"/api/actions/{action.id}/amend",
        json={"plan_token": "forged.token"},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text


async def test_amend_dependents_blocked_via_api(session: AsyncSession, client) -> None:
    setup = await _make_two_ghp_setup(session, sku="AMDAP6", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    r1 = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("5"),
        actor_id=ctx["user"].id,
        idempotency_key="amdap6:t1",
    )
    a1 = (
        await session.execute(
            select(Action).where(Action.ref_id == r1["transfer_id"])
        )
    ).scalar_one()
    r2 = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("5"),
        actor_id=ctx["user"].id,
        idempotency_key="amdap6:t2",
    )
    a2 = (
        await session.execute(
            select(Action).where(Action.ref_id == r2["transfer_id"])
        )
    ).scalar_one()
    a2.depends_on = [a1.id]
    await session.commit()
    await assert_no_invariants_violations(session, context="amdapi-deps")
    resp = await client.post(
        f"/api/actions/{a1.id}/preview-amend",
        json={"changes": {"quantity": "1"}},
        headers=_auth_headers(ctx["user"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    blocker = next(b for b in body["blockers"] if b["kind"] == "has_dependents")
    assert blocker["chain"] == [a2.id]
    assert body["plan_token"] is None


async def test_amend_confirm_shortfall_reports_real_deficit(
    session: AsyncSession, client, monkeypatch
) -> None:
    """D7-A: нехватка покрытия, вскрывшаяся только на confirm (дрейф
    остатков после fresh-preview), → 409 с РЕАЛЬНЫМ дефицитом, а не 0."""
    action, ctx = await _setup_action(session, client, "AMDAP7")
    headers = _auth_headers(ctx["user"])
    resp = await client.post(
        f"/api/actions/{action.id}/preview-amend",
        json={"changes": {"quantity": "9"}},
        headers=headers,
    )
    token = resp.json()["plan_token"]
    assert token

    from_task = await session.get(WorkTask, ctx["from_task_id"])
    original_apply = StockCompensator.apply
    commands = StockCommandService()

    async def drift_then_apply(self, db, plan, actor):
        # Гонка после fresh-preview: «параллельный оператор» списывает 7
        # единиц с источника новой ledger-записью (баланс = проекция
        # ledger, прямой UPDATE стёрся бы при пересчёте).
        to_task = await db.get(WorkTask, ctx["to_task_id"])
        await commands.record(
            db,
            StockCommand(
                product_id=from_task.product_id,
                quantity=Decimal("7"),
                reason=Reason.TRANSFER_SEND,
                from_location_id=from_task.section_id,
                to_location_id=to_task.section_id,
                quality_state=QualityState.GOOD,
                created_by=ctx["user"].id,
            ),
        )
        return await original_apply(self, db, plan, actor)

    monkeypatch.setattr(StockCompensator, "apply", drift_then_apply)

    confirm = await client.post(
        f"/api/actions/{action.id}/amend",
        json={"plan_token": token},
        headers=headers,
    )
    assert confirm.status_code == 409, confirm.text
    detail = confirm.json()["detail"]
    assert detail["node"] == action.id
    # Источник: было 10−3(отгрузка)=7, гонка −7 → 0; компенсации вернут 3;
    # нужно 9 → реальный дефицит 6.
    assert Decimal(detail["deficit"]) == Decimal("6")
