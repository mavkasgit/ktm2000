"""API-регрессии issue #182 для уведомлений под strict break-glass.

Проверяем публичные notification routes без моков. Служебный пользователь
читается из БД, поэтому тест не зависит от его ORM id.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token
from app.models.notification import Notification, UserNotificationState
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio


async def _system_user(session: AsyncSession) -> User:
    user = await session.scalar(select(User).where(User.username == "system"))
    assert user is not None, "conftest должен создать служебного пользователя"
    return user


async def _make_user(session: AsyncSession, username: str) -> User:
    user = User(
        username=username,
        email=f"{username}@example.com",
        full_name=f"User {username}",
        role=UserRole.viewer,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_notification(
    session: AsyncSession,
    *,
    user_id: int | None,
    title: str,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        notification_type="test",
        title=title,
    )
    session.add(notification)
    await session.flush()
    return notification


async def _break_glass_headers(client: AsyncClient) -> dict[str, str]:
    login = await client.post(
        "/api/auth/break-glass/login",
        json={"password": settings.BREAK_GLASS_PASSWORD},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_break_glass_notifications_are_common_only_and_state_belongs_to_system(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break-glass видит только общие уведомления; их состояние принадлежит system user."""
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    system = await _system_user(session)
    common = await _make_notification(session, user_id=None, title="Общее #182")
    personal_system = await _make_notification(
        session,
        user_id=system.id,
        title="Персональное системное #182",
    )
    await session.commit()
    headers = await _break_glass_headers(client)

    listed = await client.get("/api/internal-notifications", headers=headers)
    assert listed.status_code == 200, listed.text
    data = listed.json()
    assert data["total"] == 1
    assert data["unread_count"] == 1
    assert [
        (item["id"], item["user_id"], item["title"])
        for item in data["items"]
    ] == [(common.id, None, "Общее #182")]

    personal_read = await client.post(
        f"/api/internal-notifications/{personal_system.id}/read",
        headers=headers,
    )
    assert personal_read.status_code == 404, personal_read.text
    personal_close = await client.post(
        f"/api/internal-notifications/{personal_system.id}/close",
        headers=headers,
    )
    assert personal_close.status_code == 404, personal_close.text
    personal_state = await session.scalar(
        select(UserNotificationState).where(
            UserNotificationState.notification_id == personal_system.id,
            UserNotificationState.user_id == system.id,
        )
    )
    assert personal_state is None

    read = await client.post(
        f"/api/internal-notifications/{common.id}/read",
        headers=headers,
    )
    assert read.status_code == 200, read.text
    read_body = read.json()
    assert read_body["read_at"] is not None
    assert read_body["closed_at"] is None

    state = await session.scalar(
        select(UserNotificationState).where(
            UserNotificationState.notification_id == common.id,
            UserNotificationState.user_id == system.id,
        )
    )
    assert state is not None
    assert state.read_at is not None
    assert state.closed_at is None
    read_at = state.read_at

    closed = await client.post(
        f"/api/internal-notifications/{common.id}/close",
        headers=headers,
    )
    assert closed.status_code == 200, closed.text
    close_body = closed.json()
    assert close_body["read_at"] is not None
    assert close_body["closed_at"] is not None

    await session.refresh(state)
    assert state.user_id == system.id
    assert state.read_at == read_at
    assert state.closed_at is not None


async def test_regular_user_notifications_include_common_and_own_only(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Обычный пользователь видит общие и адресованные ему, но не чужие личные."""
    current_user = await _make_user(session, "notif_regular_182")
    other_user = await _make_user(session, "notif_other_182")
    common = await _make_notification(session, user_id=None, title="Общее #182")
    own = await _make_notification(
        session,
        user_id=current_user.id,
        title="Своё #182",
    )
    await _make_notification(
        session,
        user_id=other_user.id,
        title="Чужое #182",
    )
    await session.commit()
    client.headers["Authorization"] = (
        f"Bearer {create_access_token(subject=current_user.username)}"
    )

    listed = await client.get("/api/internal-notifications")
    assert listed.status_code == 200, listed.text
    data = listed.json()
    assert data["total"] == 2
    assert data["unread_count"] == 2
    assert {
        (item["id"], item["user_id"], item["title"])
        for item in data["items"]
    } == {
        (common.id, None, "Общее #182"),
        (own.id, current_user.id, "Своё #182"),
    }
