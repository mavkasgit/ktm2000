"""Контракт входа на полный сброс производства (`POST /production-plans/reset-all`).

Сброс стирает планы, задания, передачи, проводки и справочники — это
инструмент стенда (issue #234), а не боевая ручка. Тест гоняет настоящий
вход: аноним — 401, `viewer` — 403, `admin` при выключенном
`ALLOW_PRODUCTION_RESET` — 404 (прод не подтверждает существование ручки),
`admin` при включённом — 204.

Ролевая проверка стоит в сигнатуре маршрута раньше env-гейта. Тесты анонима и
`viewer` гоняются при ВЫКЛЮЧЕННОМ флаге — именно так фиксируется этот порядок:
без них перестановка двух зависимостей осталась бы зелёной, а аноним получал
бы 404 вместо 401.
"""
from __future__ import annotations

import pytest
from app.core.config import settings
from app.models.user import User, UserRole
from app.services.session_service import issue_app_token
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

RESET_ALL_URL = "/api/production-plans/reset-all"


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


async def test_anonymous_gets_401_when_reset_disabled(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без токена — 401, а не 404: ролевой гвард раньше env-гейта."""
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    monkeypatch.setattr(settings, "ALLOW_PRODUCTION_RESET", False)

    assert (await client.post(RESET_ALL_URL)).status_code == 401


async def test_viewer_gets_403_when_reset_disabled(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Зритель не сбрасывает производство: ручка только для admin."""
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    monkeypatch.setattr(settings, "ALLOW_PRODUCTION_RESET", False)
    headers = await _headers_for(session, UserRole.viewer, "reset_viewer")

    assert (await client.post(RESET_ALL_URL, headers=headers)).status_code == 403


async def test_admin_gets_404_when_reset_disabled(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Флаг выключен — 404 и админу: прод не подтверждает существование ручки."""
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    monkeypatch.setattr(settings, "ALLOW_PRODUCTION_RESET", False)
    headers = await _headers_for(session, UserRole.admin, "reset_admin_off")

    assert (await client.post(RESET_ALL_URL, headers=headers)).status_code == 404


async def test_admin_gets_204_when_reset_enabled(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Флаг включён (dev/e2e) — админ сбрасывает производство."""
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    monkeypatch.setattr(settings, "ALLOW_PRODUCTION_RESET", True)
    headers = await _headers_for(session, UserRole.admin, "reset_admin_on")

    assert (await client.post(RESET_ALL_URL, headers=headers)).status_code == 204
