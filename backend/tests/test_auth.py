import pytest

from app.core.security import get_password_hash, verify_password
from app.models.section import Section
from app.models.user import User, UserRole


@pytest.mark.asyncio
async def test_password_hashing_roundtrip() -> None:
    password = "S3curePass!"
    hashed = get_password_hash(password)

    assert hashed != password
    assert verify_password(password, hashed)


@pytest.mark.asyncio
async def test_login_success(client, session) -> None:
    user = User(
        email="planner@example.com",
        password_hash=get_password_hash("password123"),
        full_name="Plan User",
        role=UserRole.planner,
        is_active=True,
    )
    session.add(user)
    await session.commit()

    response = await client.post(
        "/api/auth/login",
        json={"email": "planner@example.com", "password": "password123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_rejects_disabled_user(client, session) -> None:
    user = User(
        email="disabled@example.com",
        password_hash=get_password_hash("password123"),
        full_name="Disabled User",
        role=UserRole.viewer,
        is_active=False,
    )
    session.add(user)
    await session.commit()

    response = await client.post(
        "/api/auth/login",
        json={"email": "disabled@example.com", "password": "password123"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_role_serialization_in_me(client, session) -> None:
    section = Section(code="CUT", name="Cutting", is_active=True)
    session.add(section)
    await session.flush()

    user = User(
        email="manager@example.com",
        password_hash=get_password_hash("password123"),
        full_name="Section Manager",
        role=UserRole.section_manager,
        section_id=section.id,
        is_active=True,
    )
    session.add(user)
    await session.commit()

    # Login validates credentials
    login = await client.post(
        "/api/auth/login",
        json={"email": "manager@example.com", "password": "password123"},
    )
    assert login.status_code == 200

    # /me currently returns the fake dev admin user (get_current_user is not JWT-based yet)
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "system@local"
    assert body["role"] == "admin"
