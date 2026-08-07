"""Minimal unit/integration tests for the session core via the host adapter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import TokenError, create_access_token, decode_access_token
from app.models.user import User, UserRole
from app.services import session_service


async def _create_user(db: AsyncSession, username: str = "session_user") -> User:
    user = User(
        username=username,
        email=f"{username}@example.com",
        full_name="Session Test User",
        role=UserRole.planner,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


# ─── JWT (unified issuance via app.core.security shim) ───────────────────────


def test_create_access_token_includes_sid():
    sid = uuid4()
    token = create_access_token(
        subject="admin", role="admin", full_name="Admin", session_id=sid
    )
    secret = settings.JWT_SECRET_KEY or settings.SECRET_KEY
    payload = jwt.decode(token, secret, algorithms=[settings.ALGORITHM])
    assert payload["sid"] == str(sid)
    assert payload["sub"] == "admin"
    assert payload["role"] == "admin"
    assert payload["full_name"] == "Admin"


def test_create_access_token_without_sid():
    token = create_access_token(subject="admin")
    secret = settings.JWT_SECRET_KEY or settings.SECRET_KEY
    payload = jwt.decode(token, secret, algorithms=[settings.ALGORITHM])
    assert "sid" not in payload


def test_decode_access_token_roundtrip_and_invalid():
    token = create_access_token(subject="viewer")
    payload = decode_access_token(token)
    assert payload["sub"] == "viewer"
    with pytest.raises(TokenError):
        decode_access_token("not-a-token")


def test_device_label_heuristic():
    assert (
        session_service.device_label_from_ua("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        == "Windows"
    )
    assert (
        session_service.device_label_from_ua("Mozilla/5.0 (X11; Linux x86_64)")
        == "Linux"
    )
    assert session_service.device_label_from_ua(None) is None


# ─── service + repo (DB) ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_issue_list_assert_revoke(session: AsyncSession):
    user = await _create_user(session)
    s = await session_service.issue_session(
        session,
        user_id=user.id,
        ip="10.0.0.5",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        login_method="oidc",
        ttl_minutes=60,
    )
    assert s.id is not None
    assert s.device_label == "Windows"
    assert s.ip_address == "10.0.0.5"
    assert s.revoked_at is None

    active = await session_service.list_active_sessions(session, user_id=user.id)
    assert len(active) == 1
    assert active[0].id == s.id

    loaded = await session_service.assert_session_active(session, s.id)
    assert loaded.id == s.id

    await session_service.revoke_session(
        session, user_id=user.id, session_id=s.id, reason="user_revoke"
    )
    with pytest.raises(session_service.SessionInactiveError):
        await session_service.assert_session_active(session, s.id)


@pytest.mark.asyncio
async def test_issue_unknown_login_method_rejected(session: AsyncSession):
    user = await _create_user(session)
    with pytest.raises(ValueError):
        await session_service.issue_session(
            session, user_id=user.id, login_method="bad", ttl_minutes=10
        )


@pytest.mark.asyncio
async def test_assert_missing_session_raises(session: AsyncSession):
    with pytest.raises(session_service.SessionInactiveError):
        await session_service.assert_session_active(session, uuid4())


@pytest.mark.asyncio
async def test_revoke_by_oidc_sid_only_matching(session: AsyncSession):
    user = await _create_user(session)
    s1 = await session_service.issue_session(
        session, user_id=user.id, login_method="oidc", ttl_minutes=60, oidc_sid="sid-1"
    )
    await session_service.issue_session(
        session, user_id=user.id, login_method="oidc", ttl_minutes=60, oidc_sid="sid-2"
    )
    ids = await session_service.revoke_by_oidc_sid(
        session, user_id=user.id, oidc_sid="sid-1", reason="backchannel_logout"
    )
    assert ids == [s1.id]
    active = await session_service.list_active_sessions(session, user_id=user.id)
    assert len(active) == 1
    assert active[0].oidc_sid == "sid-2"


@pytest.mark.asyncio
async def test_logout_jti_replay_protection(session: AsyncSession):
    jti = "jti-123"
    assert await session_service.is_logout_jti_used(session, jti) is False
    await session_service.mark_logout_jti_used(
        session, jti, expires_at=datetime.now(timezone.utc) + timedelta(minutes=10)
    )
    assert await session_service.is_logout_jti_used(session, jti) is True


@pytest.mark.asyncio
async def test_record_and_list_login_events(session: AsyncSession):
    user = await _create_user(session)
    s = await session_service.issue_session(
        session, user_id=user.id, login_method="oidc", ttl_minutes=60
    )
    await session_service.record_login_event(
        session,
        event_type="login_success",
        success=True,
        user_id=user.id,
        username_attempted=user.username,
        session_id=s.id,
        details={"method": "oidc"},
    )
    await session_service.record_login_event(
        session,
        event_type="login_failure",
        success=False,
        user_id=user.id,
        username_attempted=user.username,
    )
    events = await session_service.list_login_events(session, user_id=user.id)
    types = {e.event_type for e in events}
    assert {"login_success", "login_failure"} <= types


@pytest.mark.asyncio
async def test_expired_session_not_active(session: AsyncSession):
    user = await _create_user(session)
    s = await session_service.issue_session(
        session, user_id=user.id, login_method="oidc", ttl_minutes=1
    )
    s.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    session.add(s)
    await session.flush()

    active = await session_service.list_active_sessions(session, user_id=user.id)
    assert all(x.id != s.id for x in active)
    with pytest.raises(session_service.SessionInactiveError):
        await session_service.assert_session_active(session, s.id)
