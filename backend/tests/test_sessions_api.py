import pytest
from uuid import uuid4
from datetime import UTC, datetime, timedelta
from jose import jwt

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.models.user_session import UserSession
from app.services.session_service import issue_app_token, issue_session, get_session_by_id


@pytest.mark.asyncio
async def test_sessions_list_requires_auth(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)

    response = await client.get("/api/auth/sessions")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_sessions_list_returns_active_sessions(client, session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)

    user = User(
        username="testuser",
        email="testuser@example.com",
        password_hash=get_password_hash("password123"),
        full_name="Test User",
        role=UserRole.planner,
        is_active=True,
    )
    session.add(user)
    await session.commit()

    token = await issue_app_token(session, user=user, login_method="oidc")

    response = await client.get(
        "/api/auth/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["is_current"] is True
    assert body[0]["login_method"] == "oidc"


@pytest.mark.asyncio
async def test_revoke_session_success(client, session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)

    user = User(
        username="testuser2",
        email="testuser2@example.com",
        password_hash=get_password_hash("password123"),
        full_name="Test User 2",
        role=UserRole.planner,
        is_active=True,
    )
    session.add(user)
    await session.commit()

    token = await issue_app_token(session, user=user, login_method="oidc")
    
    # Получим список сессий
    list_res = await client.get(
        "/api/auth/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_res.status_code == 200
    sessions_list = list_res.json()
    assert len(sessions_list) == 1
    session_id = sessions_list[0]["id"]

    # Отзываем её
    revoke_res = await client.delete(
        f"/api/auth/sessions/{session_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert revoke_res.status_code == 204

    # Проверяем в базе
    db_session = await get_session_by_id(session, session_id)
    assert db_session is not None
    assert db_session.revoked_at is not None


@pytest.mark.asyncio
async def test_revoke_other_sessions_success(client, session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)

    user = User(
        username="testuser3",
        email="testuser3@example.com",
        password_hash=get_password_hash("password123"),
        full_name="Test User 3",
        role=UserRole.planner,
        is_active=True,
    )
    session.add(user)
    await session.commit()

    # Создаем 3 сессии для пользователя
    # 1. С помощью issue_app_token (будет current)
    token = await issue_app_token(session, user=user, login_method="oidc")
    
    # 2. Еще две сессии
    s2 = await issue_session(session, user_id=user.id, login_method="oidc", ttl_minutes=60)
    s3 = await issue_session(session, user_id=user.id, login_method="oidc", ttl_minutes=60)
    await session.commit()

    # Проверяем, что в списке 3 активных сессии
    list_res = await client.get(
        "/api/auth/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_res.status_code == 200
    assert len(list_res.json()) == 3

    # Отзываем others
    revoke_res = await client.delete(
        "/api/auth/sessions/others",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert revoke_res.status_code == 200
    assert revoke_res.json() == {"count": 2}

    # Проверяем список теперь
    list_res2 = await client.get(
        "/api/auth/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_res2.status_code == 200
    active_sessions = list_res2.json()
    assert len(active_sessions) == 1
    assert active_sessions[0]["is_current"] is True


@pytest.mark.asyncio
async def test_revoke_nonexistent_or_foreign_session_returns_404(client, session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)

    user1 = User(
        username="user1",
        email="user1@example.com",
        password_hash=get_password_hash("password123"),
        full_name="User 1",
        role=UserRole.planner,
        is_active=True,
    )
    user2 = User(
        username="user2",
        email="user2@example.com",
        password_hash=get_password_hash("password123"),
        full_name="User 2",
        role=UserRole.planner,
        is_active=True,
    )
    session.add(user1)
    session.add(user2)
    await session.commit()

    token1 = await issue_app_token(session, user=user1, login_method="oidc")
    token2 = await issue_app_token(session, user=user2, login_method="oidc")

    # Получим ID сессии пользователя 2
    list_res2 = await client.get(
        "/api/auth/sessions",
        headers={"Authorization": f"Bearer {token2}"},
    )
    session2_id = list_res2.json()[0]["id"]

    # Пытаемся отозвать её от имени пользователя 1
    revoke_res = await client.delete(
        f"/api/auth/sessions/{session2_id}",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert revoke_res.status_code == 404

    # Пытаемся отозвать несуществующий UUID
    fake_uuid = str(uuid4())
    revoke_fake = await client.delete(
        f"/api/auth/sessions/{fake_uuid}",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert revoke_fake.status_code == 404
