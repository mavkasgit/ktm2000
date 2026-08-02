import pytest
from sqlalchemy import select
from app.models.user import User, UserRole


async def _make_user(session, username: str, role: UserRole, tab_number: str | None = None) -> User:
    user = User(
        username=username,
        email=f"{username}@example.com",
        full_name=f"Full Name {username}",
        role=role,
        is_active=True,
        tab_number=tab_number,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_create_user_success(auth_client, session) -> None:
    response = await auth_client.post(
        "/api/users",
        json={
            "username": "new_user_1",
            "email": "new_1@example.com",
            "full_name": "New Employee 1",
            "role": "operator",
            "tab_number": "T-12345",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["tab_number"] == "T-12345"

    # Проверка в БД
    stmt = select(User).where(User.username == "new_user_1")
    res = await session.execute(stmt)
    user = res.scalars().first()
    assert user is not None
    assert user.tab_number == "T-12345"


@pytest.mark.asyncio
async def test_create_and_update_user_without_email(auth_client, session) -> None:
    # 1. Создаем пользователя без указания email
    response = await auth_client.post(
        "/api/users",
        json={
            "username": "no_email_user",
            "full_name": "No Email User",
            "role": "operator",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] is None
    assert data["username"] == "no_email_user"

    # 2. Обновляем email до None/null
    user_id = data["id"]
    response = await auth_client.patch(
        f"/api/users/{user_id}",
        json={"email": None},
    )
    assert response.status_code == 200
    assert response.json()["email"] is None

    # 3. Обновляем email на валидное значение
    response = await auth_client.patch(
        f"/api/users/{user_id}",
        json={"email": "new_email@example.com"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == "new_email@example.com"


@pytest.mark.asyncio
async def test_user_response_has_no_login_token_fields(auth_client, session) -> None:
    """SSO-only: в ответах /api/users не должно быть полей мёртвого OTP-флоу."""
    response = await auth_client.post(
        "/api/users",
        json={
            "username": "no_token_user",
            "full_name": "No Token User",
            "role": "viewer",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert "active_login_token" not in data

    listing = await auth_client.get("/api/users?search=no_token_user&limit=10&offset=0")
    assert listing.status_code == 200
    for user in listing.json()["users"]:
        assert "active_login_token" not in user


@pytest.mark.asyncio
async def test_user_login_token_model_removed(auth_client, session) -> None:
    """SSO-only: модель UserLoginToken удалена из реестра моделей."""
    import app.models as models_pkg

    assert "UserLoginToken" not in models_pkg.__all__
    assert "user_login_tokens" not in models_pkg.Base.metadata.tables
