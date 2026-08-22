"""REST-тесты ресурса /actions (тикет #114, D6).

Маппинг ошибок: AlreadyReversed → 409, StalePlanToken → 409,
NotAllowed → 403; happy path tree / preview-reverse / reverse.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_journal import Action
from app.transfers.services import transfer_send
from tests.stock.test_transfer_stage2 import (
    _make_tasks_transferable,
    _make_two_ghp_setup,
)
from tests.test_integrity_invariants import _auth_headers

pytestmark = pytest.mark.asyncio


async def _setup_action(session: AsyncSession, client, sku: str) -> tuple[Action, dict]:
    setup = await _make_two_ghp_setup(session, sku=sku, qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    result = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("3"),
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
    return action, ctx


async def test_tree_endpoint(session: AsyncSession, client) -> None:
    action, ctx = await _setup_action(session, client, "RVAPI1")
    resp = await client.get(
        f"/api/actions/{action.id}/tree", headers=_auth_headers(ctx["user"])
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["root"]["id"] == action.id
    assert data["root"]["action_type"] == "transfer_send"
    assert data["root"]["status"] == "active"
    assert data["total_nodes"] == 1

    # 404 на несуществующее действие.
    missing = await client.get(
        "/api/actions/999999/tree", headers=_auth_headers(ctx["user"])
    )
    assert missing.status_code == 404


async def test_preview_and_reverse_endpoints(session: AsyncSession, client) -> None:
    action, ctx = await _setup_action(session, client, "RVAPI2")
    headers = _auth_headers(ctx["user"])

    resp = await client.post(
        f"/api/actions/{action.id}/preview-reverse",
        json={"cascade": False},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    preview = resp.json()
    assert preview["revert"][0]["id"] == action.id
    assert preview["blockers"] == []
    assert preview["plan_token"]

    resp = await client.post(
        f"/api/actions/{action.id}/reverse",
        json={"plan_token": preview["plan_token"], "reason": "ошибка оператора"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["reversed_action_ids"] == [action.id]
    assert len(result["compensated_tx_ids"]) == 2

    # Повторный reverse — AlreadyReversed → 409.
    again = await client.post(
        f"/api/actions/{action.id}/preview-reverse",
        json={"cascade": False},
        headers=headers,
    )
    assert again.status_code == 409

    reverse_again = await client.post(
        f"/api/actions/{action.id}/reverse",
        json={"plan_token": preview["plan_token"]},
        headers=headers,
    )
    assert reverse_again.status_code == 409


async def test_reverse_stale_token_maps_409(session: AsyncSession, client) -> None:
    action, ctx = await _setup_action(session, client, "RVAPI3")
    headers = _auth_headers(ctx["user"])

    resp = await client.post(
        f"/api/actions/{action.id}/preview-reverse",
        json={"cascade": False},
        headers=headers,
    )
    token = resp.json()["plan_token"]

    # Мир изменился (новая передача) — токен устарел.
    await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("1"),
        actor_id=ctx["user"].id,
        idempotency_key="rvapi3:t2",
    )
    await session.commit()

    resp = await client.post(
        f"/api/actions/{action.id}/reverse",
        json={"plan_token": token},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert "preview" in resp.json()["detail"].lower()


async def test_not_allowed_maps_403(session: AsyncSession, client) -> None:
    action, ctx = await _setup_action(session, client, "RVAPI4")
    unknown = Action(action_type="import_remainders", ref_id=999999, actor="test")
    session.add(unknown)
    await session.commit()

    resp = await client.post(
        f"/api/actions/{unknown.id}/preview-reverse",
        json={"cascade": False},
        headers=_auth_headers(ctx["user"]),
    )
    assert resp.status_code == 200
    assert resp.json()["blockers"][0]["code"] == "NotAllowed"

    resp = await client.post(
        f"/api/actions/{unknown.id}/reverse",
        json={"plan_token": resp.json()["plan_token"]},
        headers=_auth_headers(ctx["user"]),
    )
    assert resp.status_code == 403, resp.text
