"""REST-тесты hard-чистки (тикет #118, ADR-0019 п.7).

admin-only guard (не-admin writer → 403), dry_run → confirm 200,
stale token 409, 404, NotAllowed → 403.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.action_journal import Action, ActionStatus
from app.models.user import User, UserRole
from app.reversal.service import reversal_service
from app.transfers.services import transfer_send
from tests.stock.test_transfer_stage2 import (
    _make_tasks_transferable,
    _make_two_ghp_setup,
)

pytestmark = pytest.mark.asyncio


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(subject=user.email)}"}


async def _setup_reversed_action(session: AsyncSession, client, sku: str) -> Action:
    """Передача + обратная (status='reversed') — готова к hard-purge."""
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
    await reversal_service.reverse(session, action.id, plan_token=preview.plan_token)
    await session.commit()
    return action


async def _make_user(session: AsyncSession, username: str, role: UserRole) -> User:
    user = User(
        username=username,
        email=f"{username}@example.com",
        full_name=username.title(),
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    return user


async def test_admin_dry_run_then_confirm(session: AsyncSession, client) -> None:
    action = await _setup_reversed_action(session, client, "HPAPI1")
    admin = await _make_user(session, "hpapi1_admin", UserRole.admin)
    headers = _headers(admin)

    resp = await client.post(
        f"/api/actions/{action.id}/hard-purge",
        json={"dry_run": True},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["action_id"] == action.id
    assert report["total_pairs"] == 2
    assert len(report["pairs"]) == 2
    assert report["pairs"][0]["quantity"] == "4.000"
    assert report["plan_token"]
    assert report["deleted_tx_ids"] == []

    resp = await client.post(
        f"/api/actions/{action.id}/hard-purge",
        json={"dry_run": False, "plan_token": report["plan_token"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    confirmed = resp.json()
    # Все 4 проводки (2 пары) физически удалены.
    assert len(confirmed["deleted_tx_ids"]) == 4
    assert len(set(confirmed["deleted_tx_ids"])) == 4

    await session.refresh(action)
    assert action.status == ActionStatus.PURGED


async def test_non_admin_writer_forbidden_403(session: AsyncSession, client) -> None:
    action = await _setup_reversed_action(session, client, "HPAPI2")
    operator = await _make_user(session, "hpapi2_operator", UserRole.operator)
    # Оператор может reverse, но не hard-purge (отдельное право admin).
    resp = await client.post(
        f"/api/actions/{action.id}/hard-purge",
        json={"dry_run": True},
        headers=_headers(operator),
    )
    assert resp.status_code == 403


async def test_not_allowed_maps_403(session: AsyncSession, client) -> None:
    """Нарушение условий п.3 спеки (статус не reversed) → 403 даже для admin."""
    setup = await _make_two_ghp_setup(session, sku="HPAPI3", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    result = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("1"),
        actor_id=ctx["user"].id,
        idempotency_key="hpapi3:t1",
    )
    action = (
        await session.execute(
            select(Action).where(Action.ref_id == result["transfer_id"])
        )
    ).scalar_one()
    await session.commit()

    admin = await _make_user(session, "hpapi3_admin", UserRole.admin)
    resp = await client.post(
        f"/api/actions/{action.id}/hard-purge",
        json={"dry_run": True},
        headers=_headers(admin),
    )
    assert resp.status_code == 403


async def test_stale_plan_token_maps_409(session: AsyncSession, client) -> None:
    action = await _setup_reversed_action(session, client, "HPAPI4")
    admin = await _make_user(session, "hpapi4_admin", UserRole.admin)
    headers = _headers(admin)

    resp = await client.post(
        f"/api/actions/{action.id}/hard-purge",
        json={"dry_run": True},
        headers=headers,
    )
    token = resp.json()["plan_token"]

    # Мир изменился — новая запись журнала меняет fingerprint (max Action.id).
    session.add(Action(action_type="transfer_send", ref_id=None, actor="world"))
    await session.commit()

    resp = await client.post(
        f"/api/actions/{action.id}/hard-purge",
        json={"dry_run": False, "plan_token": token},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text


async def test_unknown_action_404(session: AsyncSession, client) -> None:
    admin = await _make_user(session, "hpapi5_admin", UserRole.admin)
    resp = await client.post(
        "/api/actions/999999/hard-purge",
        json={"dry_run": True},
        headers=_headers(admin),
    )
    assert resp.status_code == 404
