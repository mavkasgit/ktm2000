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
    """OTP login: generate code → login → JWT with sid claim."""
    from jose import jwt

    from app.core.config import settings
    from app.models.user_login_token import UserLoginToken
    from datetime import UTC, datetime, timedelta

    user = User(
        username="planner",
        email="planner@example.com",
        password_hash=get_password_hash("password123"),
        full_name="Plan User",
        role=UserRole.planner,
        is_active=True,
    )
    session.add(user)
    await session.flush()

    # Create OTP token directly (bypasses /generate auth requirement)
    otp_token = UserLoginToken(
        user_id=user.id,
        token="123456",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        session_duration_seconds=28800,
        is_used=False,
    )
    session.add(otp_token)
    await session.commit()

    # Login via OTP
    response = await client.post(
        "/api/auth/otp/login",
        json={"token": "123456"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    claims = jwt.get_unverified_claims(body["access_token"])
    assert claims.get("sid"), "OTP login JWT must include sid claim"
    assert claims.get("sub") == "planner"

    # Token is consumed — second login fails
    response2 = await client.post(
        "/api/auth/otp/login",
        json={"token": "123456"},
    )
    assert response2.status_code == 400


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
async def test_role_serialization_in_me(client, session, monkeypatch) -> None:
    """Valid JWT → /me returns authenticated user with role and section."""
    from app.core.config import settings
    from app.services.session_service import issue_app_token

    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)

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

    token = await issue_app_token(session, user=user, login_method="otp")
    await session.commit()

    me = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    body = me.json()
    assert body["username"] == "manager"
    assert body["role"] == "section_manager"
    assert body["section_id"] == section.id


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
async def test_magic_admin_rejected_when_strict(client, session, monkeypatch) -> None:
    """Literal Bearer 'admin' is rejected when DEV_BYPASS_AUTH is false (prod/strict)."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)

    admin = User(
        username="admin",
        email="admin@example.com",
        password_hash=get_password_hash("admin"),
        full_name="Admin",
        role=UserRole.admin,
        is_active=True,
    )
    session.add(admin)
    await session.commit()

    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer admin"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_magic_admin_allowed_when_dev_bypass(client, session, monkeypatch) -> None:
    """Literal Bearer 'admin' works only when DEV_BYPASS_AUTH is true."""
    from sqlalchemy import select

    from app.core.config import settings

    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", True)

    admin = await session.scalar(select(User).where(User.username == "admin"))
    if admin is None:
        admin = User(
            username="admin",
            email="admin_magic@example.com",
            password_hash=get_password_hash("admin"),
            full_name="Admin",
            role=UserRole.admin,
            is_active=True,
        )
        session.add(admin)
        await session.commit()

    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer admin"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "admin"


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
    """Valid token + active sid for disabled user must return 403."""
    from app.core.config import settings
    from app.services.session_service import issue_session

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

    # Create a valid token with active session for the disabled user
    usess = await issue_session(
        session,
        user_id=disabled_user.id,
        login_method="password",
        ttl_minutes=60,
    )
    await session.commit()
    token = create_access_token(
        subject=disabled_user.username, session_id=usess.id
    )

    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "User account is disabled"


@pytest.mark.asyncio
async def test_login_me_logout_session_flow(client, session, monkeypatch) -> None:
    """issue_app_token → /me ok → logout revokes → /me 401 (strict)."""
    from jose import jwt

    from app.core.config import settings
    from app.services.session_service import issue_app_token

    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)

    user = User(
        username="session_user",
        email="session_user@example.com",
        password_hash=get_password_hash("password123"),
        full_name="Session User",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.commit()

    token = await issue_app_token(session, user=user, login_method="otp")
    await session.commit()

    claims = jwt.get_unverified_claims(token)
    assert claims.get("sid")
    assert claims.get("sub") == "session_user"

    headers = {"Authorization": f"Bearer {token}"}
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["username"] == "session_user"

    logout = await client.post("/api/auth/logout", headers=headers)
    assert logout.status_code == 204

    me_after = await client.get("/api/auth/me", headers=headers)
    assert me_after.status_code == 401
    assert "Session" in me_after.json()["detail"] or "session" in me_after.json()["detail"].lower()


@pytest.mark.asyncio
async def test_strict_jwt_without_sid_returns_401(client, session, monkeypatch) -> None:
    """Strict mode rejects JWT without sid claim."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)

    user = User(
        username="nosid",
        email="nosid@example.com",
        password_hash=get_password_hash("password123"),
        full_name="No Sid",
        role=UserRole.viewer,
        is_active=True,
    )
    session.add(user)
    await session.commit()

    token = create_access_token(subject=user.username)
    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Session required"


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
    from decimal import Decimal

    from sqlalchemy import select

    from app.models.internal_plan import SectionPlanLine
    from app.models.section import Section
    from app.models.work_task import WorkTask
    from app.services.shopfloor.cache import _refresh_section_plan_line_cache
    from app.stock import StockCommand, StockCommandService, Reason
    from tests.test_plan_generation import _make_plan_position, _make_ready_product

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

    product, _sections, route = await _make_ready_product(session, "FG-TRANS")
    plan, pos = await _make_plan_position(session, product, route_id=route.id)
    await session.commit()

    create_response = await client.post(
        f"/api/production-plans/{plan.id}/release-batches",
        json={"positions": [{"plan_position_id": pos.id, "release_quantity": "100"}]},
    )
    assert create_response.status_code == 201
    batch = create_response.json()
    release_response = await client.post(f"/api/release-batches/{batch['id']}/release")
    assert release_response.status_code == 200

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

    admin_user = User(
        username="admin_test_t",
        email="admin_t@example.com",
        password_hash=get_password_hash("pass"),
        full_name="Admin T",
        role=UserRole.admin,
        is_active=True,
    )
    raw_stock = Section(code="FG-TRANS-STK", name="Stock", type="raw_stock", is_active=True)
    session.add_all([admin_user, raw_stock])
    await session.commit()

    admin_headers = {"Authorization": f"Bearer {create_access_token(subject=admin_user.username)}"}

    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=first_task.product_id,
            to_location_id=raw_stock.id,
            quantity=Decimal("100"),
            reason=Reason.MANUAL_IN,
            created_by=admin_user.id,
        ),
    )
    await svc.record(
        session,
        StockCommand(
            product_id=first_task.product_id,
            from_location_id=raw_stock.id,
            to_location_id=first_task.section_id,
            quantity=Decimal("100"),
            reason=Reason.TRANSFER_RECEIVE,
            task_id=first_task.id,
            created_by=admin_user.id,
        ),
    )
    await session.commit()
    await _refresh_section_plan_line_cache(session, first_task.section_plan_line_id)

    complete_response = await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/complete",
        json={"good_quantity": "100", "defect_quantity": "0"},
        headers=admin_headers,
    )
    assert complete_response.status_code == 200, complete_response.text

    transporter_headers = {
        "Authorization": f"Bearer {create_access_token(subject=transporter.username)}",
        "X-Shopfloor-Single-Section-Id": str(first_task.section_id),
    }

    transfer_response = await client.post(
        "/api/transfers",
        json={
            "from_task_id": first_task.id,
            "to_task_id": second_task.id,
            "quantity": "50",
        },
        headers=transporter_headers,
    )
    assert transfer_response.status_code == 200, transfer_response.text
    assert transfer_response.json()["status"] == "accepted"

    forbidden_response = await client.post(
        f"/api/shopfloor/tasks/{second_task.id}/complete",
        json={"good_quantity": "50", "defect_quantity": "0"},
        headers={"Authorization": transporter_headers["Authorization"]},
    )
    assert forbidden_response.status_code == 403
