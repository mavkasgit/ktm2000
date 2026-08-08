"""Tests for GET /api/internal-notifications (список уведомлений).

Контракт: {items, total, unread_count}, скоуп user_id IS NULL OR user_id = текущий,
фильтр only_unclosed, сортировка created_at DESC, пагинация limit/offset.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models.internal_notification import InternalNotification
from app.models.user import User, UserRole

NOTIFICATION_FIELDS = {
    "id",
    "user_id",
    "notification_type",
    "title",
    "text",
    "entity_type",
    "entity_id",
    "created_at",
    "read_at",
    "closed_at",
}


def _dt(days_back: int = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_back)


async def _make_user(session, *, username: str, role: UserRole = UserRole.viewer) -> User:
    user = User(
        username=username,
        email=f"{username}@example.com",
        full_name=f"User {username}",
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_notification(
    session,
    *,
    user_id: int | None,
    title: str = "Тестовое уведомление",
    notification_type: str = "test",
    text: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    created_at: datetime | None = None,
    read_at: datetime | None = None,
    closed_at: datetime | None = None,
) -> InternalNotification:
    notification = InternalNotification(
        user_id=user_id,
        notification_type=notification_type,
        title=title,
        text=text,
        entity_type=entity_type,
        entity_id=entity_id,
        created_at=created_at or _dt(),
        read_at=read_at,
        closed_at=closed_at,
    )
    session.add(notification)
    await session.flush()
    return notification


async def _testauth_id(session) -> int:
    user = await session.scalar(select(User).where(User.username == "testauth"))
    assert user is not None
    return user.id


@pytest.mark.asyncio
async def test_notifications_list_empty_when_no_notifications(auth_client) -> None:
    response = await auth_client.get("/api/internal-notifications")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "unread_count": 0}


@pytest.mark.asyncio
async def test_notifications_payload_matches_frontend_contract(auth_client, session) -> None:
    current_user_id = await _testauth_id(session)
    notification = await _make_notification(
        session,
        user_id=current_user_id,
        title="Личное",
        notification_type="test",
        text="Текст",
        entity_type="product",
        entity_id=42,
    )
    await session.commit()

    response = await auth_client.get("/api/internal-notifications")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert set(item.keys()) == NOTIFICATION_FIELDS
    assert item["id"] == notification.id
    assert item["user_id"] == current_user_id
    assert item["notification_type"] == "test"
    assert item["title"] == "Личное"
    assert item["text"] == "Текст"
    assert item["entity_type"] == "product"
    assert item["entity_id"] == 42
    assert item["read_at"] is None
    assert item["closed_at"] is None


@pytest.mark.asyncio
async def test_notifications_scope_includes_general_and_own(auth_client, session) -> None:
    current_user_id = await _testauth_id(session)
    other = await _make_user(session, username="notif_other")
    await _make_notification(session, user_id=None, title="Общее")
    await _make_notification(session, user_id=current_user_id, title="Своё")
    await _make_notification(session, user_id=other.id, title="Чужое")
    await session.commit()

    response = await auth_client.get("/api/internal-notifications")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert {item["title"] for item in data["items"]} == {"Общее", "Своё"}
    by_title = {item["title"]: item["user_id"] for item in data["items"]}
    assert by_title["Общее"] is None
    assert by_title["Своё"] == current_user_id


@pytest.mark.asyncio
async def test_notifications_only_unclosed_excludes_closed_by_default(auth_client, session) -> None:
    await _make_notification(session, user_id=None, title="Открытое")
    closed = await _make_notification(session, user_id=None, title="Закрытое")
    closed.closed_at = _dt()
    await session.commit()

    response = await auth_client.get("/api/internal-notifications")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert [item["title"] for item in data["items"]] == ["Открытое"]

    response_all = await auth_client.get("/api/internal-notifications?only_unclosed=false")
    assert response_all.status_code == 200
    data_all = response_all.json()
    assert data_all["total"] == 2
    assert {item["title"] for item in data_all["items"]} == {"Открытое", "Закрытое"}


@pytest.mark.asyncio
async def test_notifications_sorted_by_created_at_desc(auth_client, session) -> None:
    for index in range(5):
        await _make_notification(
            session,
            user_id=None,
            title=f"Уведомление {index}",
            created_at=_dt(days_back=index),
        )
    await session.commit()

    response = await auth_client.get("/api/internal-notifications")
    assert response.status_code == 200
    titles = [item["title"] for item in response.json()["items"]]
    assert titles == ["Уведомление 0", "Уведомление 1", "Уведомление 2", "Уведомление 3", "Уведомление 4"]


@pytest.mark.asyncio
async def test_notifications_pagination_limit_offset(auth_client, session) -> None:
    for index in range(5):
        await _make_notification(
            session,
            user_id=None,
            title=f"Уведомление {index}",
            created_at=_dt(days_back=index),
        )
    await session.commit()

    first = await auth_client.get("/api/internal-notifications?limit=2&offset=0")
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["total"] == 5
    assert [item["title"] for item in first_body["items"]] == ["Уведомление 0", "Уведомление 1"]

    second = await auth_client.get("/api/internal-notifications?limit=2&offset=2")
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["total"] == 5
    assert [item["title"] for item in second_body["items"]] == ["Уведомление 2", "Уведомление 3"]

    first_ids = {item["id"] for item in first_body["items"]}
    second_ids = {item["id"] for item in second_body["items"]}
    assert first_ids.isdisjoint(second_ids)


@pytest.mark.asyncio
async def test_notifications_unread_count_only_active_unread(auth_client, session) -> None:
    current_user_id = await _testauth_id(session)
    other = await _make_user(session, username="notif_other_unread")
    await _make_notification(session, user_id=None, title="Активное непрочитанное")
    read = await _make_notification(session, user_id=None, title="Активное прочитанное")
    read.read_at = _dt()
    closed = await _make_notification(session, user_id=None, title="Закрытое непрочитанное")
    closed.closed_at = _dt()
    await _make_notification(session, user_id=current_user_id, title="Своё непрочитанное")
    await _make_notification(session, user_id=other.id, title="Чужое непрочитанное")
    await session.commit()

    response = await auth_client.get("/api/internal-notifications")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert data["unread_count"] == 2


@pytest.mark.asyncio
async def test_notifications_accessible_to_any_authenticated_user(client, session) -> None:
    viewer = await _make_user(session, username="notif_viewer")
    await session.commit()
    client.headers["Authorization"] = f"Bearer {create_access_token(subject=viewer.username)}"

    await _make_notification(session, user_id=viewer.id, title="Для вьювера")
    await session.commit()

    response = await client.get("/api/internal-notifications")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Для вьювера"


@pytest.mark.asyncio
async def test_notifications_limit_validation(auth_client) -> None:
    response = await auth_client.get("/api/internal-notifications?limit=1000")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_mark_read_sets_read_at(auth_client, session) -> None:
    current_user_id = await _testauth_id(session)
    notification = await _make_notification(session, user_id=current_user_id)
    await session.commit()

    response = await auth_client.post(f"/api/internal-notifications/{notification.id}/read")
    assert response.status_code == 200
    body = response.json()
    assert body["read_at"] is not None
    assert body["closed_at"] is None

    await session.refresh(notification)
    assert notification.read_at is not None
    assert notification.closed_at is None


@pytest.mark.asyncio
async def test_mark_read_is_idempotent(auth_client, session) -> None:
    current_user_id = await _testauth_id(session)
    notification = await _make_notification(session, user_id=current_user_id)
    await session.commit()

    first = await auth_client.post(f"/api/internal-notifications/{notification.id}/read")
    await session.refresh(notification)
    first_read_at = notification.read_at
    assert first_read_at is not None

    second = await auth_client.post(f"/api/internal-notifications/{notification.id}/read")
    assert second.status_code == 200
    assert second.json()["read_at"] == first.json()["read_at"]

    await session.refresh(notification)
    assert notification.read_at == first_read_at


@pytest.mark.asyncio
async def test_mark_read_general_notification_allowed(auth_client, session) -> None:
    notification = await _make_notification(session, user_id=None)
    await session.commit()

    response = await auth_client.post(f"/api/internal-notifications/{notification.id}/read")
    assert response.status_code == 200
    assert response.json()["read_at"] is not None


@pytest.mark.asyncio
async def test_mark_read_foreign_personal_notification_404(auth_client, session) -> None:
    other = await _make_user(session, username="notif_foreign_reader")
    foreign = await _make_notification(session, user_id=other.id)
    await session.commit()

    response = await auth_client.post(f"/api/internal-notifications/{foreign.id}/read")
    assert response.status_code == 404
    assert response.json()["detail"] == "Уведомление не найдено"

    await session.refresh(foreign)
    assert foreign.read_at is None


@pytest.mark.asyncio
async def test_mark_read_missing_notification_404(auth_client) -> None:
    response = await auth_client.post("/api/internal-notifications/999999/read")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_close_sets_read_at_and_closed_at(auth_client, session) -> None:
    current_user_id = await _testauth_id(session)
    notification = await _make_notification(session, user_id=current_user_id)
    await session.commit()

    response = await auth_client.post(f"/api/internal-notifications/{notification.id}/close")
    assert response.status_code == 200
    body = response.json()
    assert body["read_at"] is not None
    assert body["closed_at"] is not None

    await session.refresh(notification)
    assert notification.read_at is not None
    assert notification.closed_at is not None


@pytest.mark.asyncio
async def test_close_is_idempotent(auth_client, session) -> None:
    current_user_id = await _testauth_id(session)
    notification = await _make_notification(session, user_id=current_user_id)
    await session.commit()

    first = await auth_client.post(f"/api/internal-notifications/{notification.id}/close")
    await session.refresh(notification)
    first_closed_at = notification.closed_at
    assert first_closed_at is not None

    second = await auth_client.post(f"/api/internal-notifications/{notification.id}/close")
    assert second.status_code == 200
    assert second.json()["closed_at"] == first.json()["closed_at"]

    await session.refresh(notification)
    assert notification.closed_at == first_closed_at


@pytest.mark.asyncio
async def test_close_removes_from_active_list(auth_client, session) -> None:
    current_user_id = await _testauth_id(session)
    notification = await _make_notification(session, user_id=current_user_id, title="Закрываю")
    await session.commit()

    response = await auth_client.post(f"/api/internal-notifications/{notification.id}/close")
    assert response.status_code == 200

    list_response = await auth_client.get("/api/internal-notifications")
    assert list_response.status_code == 200
    data = list_response.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_close_foreign_personal_notification_404(auth_client, session) -> None:
    other = await _make_user(session, username="notif_foreign_closer")
    foreign = await _make_notification(session, user_id=other.id)
    await session.commit()

    response = await auth_client.post(f"/api/internal-notifications/{foreign.id}/close")
    assert response.status_code == 404

    await session.refresh(foreign)
    assert foreign.closed_at is None


@pytest.mark.asyncio
async def test_close_missing_notification_404(auth_client) -> None:
    response = await auth_client.post("/api/internal-notifications/999999/close")
    assert response.status_code == 404
