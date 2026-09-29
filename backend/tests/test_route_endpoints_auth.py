"""Контракт входа на ручки маршрутов и посева (`/api/routes`, `/api/routes-seed`).

Раньше эти ручки были единственными в своём роутере без гварда, и аноним
проходил по ним и в strict-режиме. Тест гоняет настоящий вход: без токена —
401, токен роли viewer на чтение — 200, на запись — 403, токен роли operator
на запись — не 401/403.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User, UserRole
from app.services.session_service import issue_app_token

pytestmark = pytest.mark.asyncio


async def _headers_for(session: AsyncSession, role: UserRole, username: str) -> dict[str, str]:
    """Настоящий JWT роли: пользователь + активная серверная сессия (claim sid)."""
    user = User(
        username=username,
        email=f"{username}@example.com",
        full_name=f"User {username}",
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    token = await issue_app_token(session, user=user, login_method="oidc")
    await session.commit()
    return {"Authorization": f"Bearer {token}"}


async def test_anonymous_cannot_reach_route_endpoints(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Анонимный клиент не читает и не меняет маршруты и не сеет справочники."""
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)

    assert (await client.get("/api/routes")).status_code == 401
    assert (await client.delete("/api/routes/1")).status_code == 401
    seeded = await client.post("/api/routes-seed?force=true")
    assert seeded.status_code == 401


async def test_viewer_reads_routes_but_cannot_write(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Viewer — режим «только чтение»: список маршрутов виден, запись отбита."""
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    headers = await _headers_for(session, UserRole.viewer, "routes_viewer")

    assert (await client.get("/api/routes", headers=headers)).status_code == 200
    assert (await client.post("/api/routes", json={"name": "Viewer route"}, headers=headers)).status_code == 403
    assert (await client.delete("/api/routes/1", headers=headers)).status_code == 403


async def test_operator_may_create_route(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Роль, которой запись полагается (operator), проходит гвард."""
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    headers = await _headers_for(session, UserRole.operator, "routes_operator")

    created = await client.post(
        "/api/routes",
        json={"name": "Operator route", "is_active": True},
        headers=headers,
    )
    assert created.status_code not in (401, 403), created.text