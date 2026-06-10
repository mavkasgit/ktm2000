import pytest

from app.core.security import get_password_hash, verify_password, create_access_token
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
        username="planner",
        email="planner@example.com",
        password_hash=get_password_hash("password123"),
        full_name="Plan User",
        role=UserRole.planner,
        is_active=True,
    )
    session.add(user)
    await session.commit()

    # 1. Проверяем вход по короткому логину (username)
    response = await client.post(
        "/api/auth/login",
        json={"username": "planner", "password": "password123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"

    # 2. Проверяем вход по email
    response_email = await client.post(
        "/api/auth/login",
        json={"username": "planner@example.com", "password": "password123"},
    )
    assert response_email.status_code == 200
    body_email = response_email.json()
    assert "access_token" in body_email


@pytest.mark.asyncio
async def test_login_rejects_disabled_user(client, session) -> None:
    user = User(
        username="disabled",
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
        json={"username": "disabled", "password": "password123"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_role_serialization_in_me(client, session) -> None:
    section = Section(code="CUT", name="Cutting", is_active=True)
    session.add(section)
    await session.flush()

    user = User(
        username="manager",
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
        json={"username": "manager", "password": "password123"},
    )
    assert login.status_code == 200

    # /me currently returns the fake dev admin user (get_current_user is not JWT-based yet)
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["username"] == "system"
    assert body["email"] == "system@local"
    assert body["role"] == "admin"


# ─── Strict auth tests (DEV_BYPASS_AUTH=False) ───────────────────────


@pytest.mark.asyncio
async def test_unauthenticated_request_returns_401(client, session, monkeypatch) -> None:
    """Request to a protected endpoint without token must return 401."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)

    response = await client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing authentication token"
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.asyncio
async def test_expired_token_returns_401(client, session, monkeypatch) -> None:
    """Request with an expired token must return 401."""
    from datetime import UTC, datetime, timedelta
    from jose import jwt
    from app.core.config import settings

    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)

    # Create a token that expired 1 hour ago
    expired_payload = {
        "sub": "system",
        "exp": datetime.now(UTC) - timedelta(hours=1),
    }
    expired_token = jwt.encode(expired_payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired token"


@pytest.mark.asyncio
async def test_disabled_user_token_returns_403(client, session, monkeypatch) -> None:
    """Valid token for disabled user must return 403."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)

    # Create a disabled user
    disabled_user = User(
        username="disabled_strict",
        email="disabled_strict@example.com",
        password_hash=get_password_hash("password123"),
        full_name="Disabled Strict User",
        role=UserRole.viewer,
        is_active=False,
    )
    session.add(disabled_user)
    await session.commit()

    # Create a valid token for the disabled user
    token = create_access_token(subject=disabled_user.username)

    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "User account is disabled"


@pytest.mark.asyncio
async def test_me_returns_authenticated_user(auth_client, session, monkeypatch) -> None:
    """/auth/me with valid token returns that user's data (not system@local)."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)

    response = await auth_client.get("/api/auth/me")

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "testauth"
    assert body["email"] == "testauth@example.com"
    assert body["full_name"] == "Test Auth User"
    assert body["role"] == "admin"
    assert body["is_active"] is True


@pytest.mark.asyncio
async def test_create_user_with_multiple_sections(auth_client, session) -> None:
    s1 = Section(code="S1", name="Section 1", is_active=True)
    s2 = Section(code="S2", name="Section 2", is_active=True)
    session.add_all([s1, s2])
    await session.commit()

    response = await auth_client.post(
        "/api/users",
        json={
            "username": "multisecuser",
            "email": "multisecuser@example.com",
            "password": "testpassword",
            "full_name": "Multi Section User",
            "role": "section_manager",
            "section_ids": [s1.id, s2.id]
        }
    )
    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "multisecuser"
    assert body["section_id"] == s1.id
    assert body["section_ids"] == [s1.id, s2.id]


@pytest.mark.asyncio
async def test_update_user_sections(auth_client, session) -> None:
    s1 = Section(code="S3", name="Section 3", is_active=True)
    s2 = Section(code="S4", name="Section 4", is_active=True)
    session.add_all([s1, s2])
    await session.commit()

    user = User(
        username="updatesecuser",
        email="updatesecuser@example.com",
        password_hash=get_password_hash("pass"),
        full_name="Update Sec User",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.commit()

    response = await auth_client.patch(
        f"/api/users/{user.id}",
        json={
            "section_ids": [s1.id, s2.id]
        }
    )
    assert response.status_code == 200
    body = response.json()
    assert body["section_id"] == s1.id
    assert body["section_ids"] == [s1.id, s2.id]

    response_legacy = await auth_client.patch(
        f"/api/users/{user.id}",
        json={
            "section_id": s2.id
        }
    )
    assert response_legacy.status_code == 200
    body_legacy = response_legacy.json()
    assert body_legacy["section_id"] == s2.id
    assert body_legacy["section_ids"] == [s2.id]


@pytest.mark.asyncio
async def test_transporter_can_manage_transfers_globally_but_not_shopfloor_tasks(session, client) -> None:
    from app.core.security import create_access_token
    from httpx import AsyncClient, ASGITransport
    from tests.test_shopfloor_api import _make_product_route_plan, _release_plan_position
    from app.main import app

    transporter = User(
        username="transporter_user",
        email="transporter@example.com",
        password_hash=get_password_hash("pass"),
        full_name="Transporter User",
        role=UserRole.transporter,
        is_active=True,
    )
    session.add(transporter)
    await session.commit()

    product, plan, pos = await _make_product_route_plan(session, "FG-TRANS")
    await _release_plan_position(client, plan.id, pos.id)

    from sqlalchemy import select
    from app.models.work_task import WorkTask
    from app.models.internal_plan import SectionPlanLine
    tasks = (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == pos.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()
    
    assert len(tasks) >= 2
    first_task, second_task = tasks[0], tasks[1]

    # Подготавливаем первую задачу через админа
    admin_user = User(
        username="admin_test_t",
        email="admin_t@example.com",
        password_hash=get_password_hash("pass"),
        full_name="Admin T",
        role=UserRole.admin,
        is_active=True,
    )
    session.add(admin_user)
    await session.commit()

    admin_token = create_access_token(subject=admin_user.username)
    admin_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    await admin_client.post(f"/api/shopfloor/tasks/{first_task.id}/issue", json={"quantity": "100"})
    await admin_client.post(f"/api/shopfloor/tasks/{first_task.id}/complete", json={"good_quantity": "100", "defect_quantity": "0"})

    # Клиент транспортировщика
    token = create_access_token(subject=transporter.username)
    t_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Трансфер
    response = await t_client.post(
        "/api/transfers",
        json={
            "from_task_id": first_task.id,
            "to_task_id": second_task.id,
            "quantity": 50,
        },
        headers={"X-Shopfloor-Single-Section-Id": str(first_task.section_id)}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"

    # Производственная операция (должна дать 403)
    response_issue = await t_client.post(
        f"/api/shopfloor/tasks/{second_task.id}/issue",
        json={
            "quantity": 50
        }
    )
    assert response_issue.status_code == 403
