"""GET /auth/me/links and GET /auth/me/login-events — каноничный контракт профиля."""

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.user import User
from app.services.session_service import record_login_event


@pytest.mark.asyncio
async def test_me_links_returns_idp_deep_links(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_OIDC_ENABLED", True)
    monkeypatch.setattr(settings, "AUTHENTIK_API_URL", "http://localhost:9000")
    monkeypatch.setattr(settings, "AUTHENTIK_PUBLIC_URL", "http://localhost:9000")

    response = await auth_client.get("/api/auth/me/links")
    assert response.status_code == 200
    body = response.json()
    assert body["oidc_enabled"] is True
    assert body["user_settings_url"] == "http://localhost:9000/if/user/#/settings"
    assert body["sso_dashboard_url"] == "http://localhost:9000/if/user/"


@pytest.mark.asyncio
async def test_me_links_oidc_disabled(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_OIDC_ENABLED", False)
    monkeypatch.setattr(settings, "AUTHENTIK_API_URL", "http://localhost:9000")

    response = await auth_client.get("/api/auth/me/links")
    assert response.status_code == 200
    assert response.json()["oidc_enabled"] is False


@pytest.mark.asyncio
async def test_me_login_events_returns_history(auth_client, session):
    res = await session.execute(select(User).where(User.username == "testauth"))
    user = res.scalar_one()
    await record_login_event(
        session,
        event_type="login_success",
        success=True,
        user_id=user.id,
        username_attempted="testauth",
        ip_address="10.0.0.1",
        user_agent="Mozilla/5.0 (Windows NT 10.0) AppleWebKit Chrome/120.0 Safari/537.36",
        details={"method": "oidc"},
    )
    await session.commit()

    response = await auth_client.get("/api/auth/me/login-events")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["events"]) == 1
    event = body["events"][0]
    assert event["success"] is True
    assert event["event_type"] == "login_success"
    assert event["ip_address"] == "10.0.0.1"
    assert event["device_label"] is not None
    assert event["login_method"] == "oidc"
    assert event["failure_reason"] is None


@pytest.mark.asyncio
async def test_me_login_events_empty(auth_client):
    response = await auth_client.get("/api/auth/me/login-events")
    assert response.status_code == 200
    assert response.json() == {"events": [], "total": 0}
