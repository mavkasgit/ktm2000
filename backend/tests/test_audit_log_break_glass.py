"""API regression for issue #183: strict break-glass audit attribution."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.audit_log_service import log_action
from app.models.audit_log import AuditLog
from app.models.user import User

pytestmark = pytest.mark.asyncio

_BREAK_GLASS_AUTHOR = "Emergency Access Admin"


async def _system_user(session: AsyncSession) -> User:
    user = await session.scalar(select(User).where(User.username == "system"))
    assert user is not None, "conftest должен создать служебного пользователя"
    return user


async def _break_glass_headers(client: AsyncClient) -> dict[str, str]:
    login = await client.post(
        "/api/auth/break-glass/login",
        json={"password": settings.BREAK_GLASS_PASSWORD},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_break_glass_audit_log_is_attributed_to_system_user(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /api/audit-logs exposes and persists the emergency attribution."""
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    system = await _system_user(session)
    headers = await _break_glass_headers(client)

    response = await client.post(
        "/api/audit-logs",
        headers=headers,
        json={
            "status": "info",
            "title": "Break-glass audit regression",
            "message": "Audit entry created through the strict break-glass API",
            "action": "create",
            "entity_type": "production_plan",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_id"] == system.id
    assert body["user_name"] == _BREAK_GLASS_AUTHOR

    log = await session.get(AuditLog, body["id"])
    assert log is not None
    assert log.user_id == system.id
    assert log.user_name == _BREAK_GLASS_AUTHOR


async def test_log_action_does_not_store_invalid_actor_fk(
    session: AsyncSession,
) -> None:
    """A missing actor is stored as NULL with its emergency name preserved."""
    log = await log_action(
        session,
        status="info",
        title="Missing actor regression",
        message="An emergency audit entry without a persisted actor",
        user=None,
        user_id=0,
        user_name=_BREAK_GLASS_AUTHOR,
    )

    assert log.user_id is None
    assert log.user_name == _BREAK_GLASS_AUTHOR
