"""Business logic for user sessions and login audit events."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token
from app.models.user import User
from app.models.user_login_event import UserLoginEvent
from app.models.user_session import UserSession
from app.repositories.login_event_repository import LoginEventRepository
from app.repositories.logout_jti_repository import LogoutJtiRepository
from app.repositories.session_repository import SessionRepository

# --- string constants (validation / storage; not DB enums) ---

LOGIN_METHODS = frozenset({"oidc"})
EVENT_TYPES = frozenset({"login_success", "login_failure", "logout", "session_revoke"})
REVOKE_REASONS = frozenset(
    {"logout", "user_revoke", "admin", "expired", "backchannel_logout"}
)

session_repo = SessionRepository()
login_event_repo = LoginEventRepository()
logout_jti_repo = LogoutJtiRepository()


class SessionInactiveError(Exception):
    """Session missing, revoked, or past expires_at."""

    def __init__(self, message: str = "Session inactive", code: str = "session_inactive"):
        super().__init__(message)
        self.message = message
        self.code = code


async def issue_session(
    db: AsyncSession,
    *,
    user_id: int,
    login_method: str,
    ttl_minutes: int,
    ip: str | None = None,
    user_agent: str | None = None,
    oidc_sid: str | None = None,
) -> UserSession:
    """Insert session row; expires_at = now + ttl."""
    if login_method not in LOGIN_METHODS:
        raise ValueError(f"Unknown login_method: {login_method}")
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=max(1, int(ttl_minutes)))
    # Device label from UA (simple heuristic)
    device_label = device_label_from_ua(user_agent)
    return await session_repo.create_session(
        db,
        user_id=user_id,
        expires_at=expires_at,
        login_method=login_method,
        ip_address=ip,
        user_agent=user_agent,
        device_label=device_label,
        last_seen_at=now,
        oidc_sid=oidc_sid,
    )


async def get_session_by_id(db: AsyncSession, session_id: UUID) -> UserSession | None:
    return await session_repo.get_by_id(db, session_id)


async def assert_session_active(db: AsyncSession, session_id: UUID) -> UserSession:
    """Raise SessionInactiveError if missing / revoked / expired."""
    session = await session_repo.get_by_id(db, session_id)
    if session is None:
        raise SessionInactiveError("Session not found", "session_not_found")
    if session.revoked_at is not None:
        raise SessionInactiveError("Session revoked", "session_revoked")
    expires = session.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc):
        raise SessionInactiveError("Session expired", "session_expired")

    # Throttled last_seen update
    last_seen = session.last_seen_at
    if last_seen is not None and last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    throttle = getattr(settings, "SESSION_LAST_SEEN_THROTTLE_SECONDS", 300)
    if last_seen is None or (datetime.now(timezone.utc) - last_seen).total_seconds() >= throttle:
        await session_repo.touch_last_seen(db, session_id, when=datetime.now(timezone.utc))
        session.last_seen_at = datetime.now(timezone.utc)

    return session


async def revoke_session(
    db: AsyncSession,
    *,
    user_id: int,
    session_id: UUID,
    reason: str,
) -> None:
    """Revoke a session owned by user_id. Raises if not found / not owned."""
    if reason not in REVOKE_REASONS:
        raise ValueError(f"Unknown revoke reason: {reason}")
    session = await session_repo.get_by_id(db, session_id)
    if session is None or session.user_id != user_id:
        raise SessionInactiveError("Session not found", "session_not_found")
    if session.revoked_at is None:
        await session_repo.revoke(db, session_id, reason)


async def revoke_session_simple(db: AsyncSession, session_id: UUID) -> UserSession | None:
    """Soft-revoke by id. Returns row or None if missing. Idempotent if already revoked."""
    return await session_repo.revoke(db, session_id, "logout")


async def revoke_all(
    db: AsyncSession,
    *,
    user_id: int,
    reason: str,
) -> int:
    """Revoke all sessions for user including current. Returns revoked count."""
    if reason not in REVOKE_REASONS:
        raise ValueError(f"Unknown revoke reason: {reason}")
    return await session_repo.revoke_all_for_user(db, user_id, reason, except_id=None)


async def revoke_sessions_for_user(
    db: AsyncSession,
    *,
    user_id: int,
    except_id: UUID | None = None,
) -> int:
    """Revoke all non-revoked sessions for user. Returns count updated."""
    return await session_repo.revoke_all_for_user(db, user_id, "logout", except_id=except_id)


async def revoke_by_oidc_sid(
    db: AsyncSession,
    *,
    user_id: int,
    oidc_sid: str,
    reason: str,
) -> list[UUID]:
    """Revoke sessions of user tied to IdP sid (back-channel SLO). Returns ids."""
    if reason not in REVOKE_REASONS:
        raise ValueError(f"Unknown revoke reason: {reason}")
    return await session_repo.revoke_active_by_oidc_sid(
        db, user_id=user_id, oidc_sid=oidc_sid, reason=reason
    )


# --- Logout JTI replay protection ---

async def is_logout_jti_used(db: AsyncSession, jti: str) -> bool:
    return await logout_jti_repo.is_used(db, jti)


async def mark_logout_jti_used(
    db: AsyncSession, jti: str, *, expires_at: datetime
) -> None:
    await logout_jti_repo.mark_used(db, jti, expires_at=expires_at)


async def cleanup_logout_jti(db: AsyncSession) -> int:
    """Opportunistic purge of consumed jti with expired exp."""
    return await logout_jti_repo.delete_expired(db)


# --- Login events (audit) ---

async def record_login_event(
    db: AsyncSession,
    *,
    event_type: str,
    success: bool,
    user_id: int | None = None,
    username_attempted: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    session_id: UUID | None = None,
    details: dict | None = None,
):
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown event_type: {event_type}")
    return await login_event_repo.create_event(
        db,
        event_type=event_type,
        success=success,
        user_id=user_id,
        username_attempted=username_attempted,
        ip_address=ip_address,
        user_agent=user_agent,
        session_id=session_id,
        details=details,
    )


# --- Session list ---

async def list_active_sessions(db: AsyncSession, *, user_id: int) -> list[UserSession]:
    return await session_repo.list_active_for_user(db, user_id)


async def list_login_events(
    db: AsyncSession,
    *,
    user_id: int,
    limit: int = 50,
) -> list[UserLoginEvent]:
    """Login history window (retention days) for the user, newest first."""
    since = datetime.now(timezone.utc) - timedelta(days=settings.LOGIN_EVENTS_RETENTION_DAYS)
    safe_limit = max(1, min(int(limit), 200))
    return await login_event_repo.list_for_user(db, user_id, since=since, limit=safe_limit)


# --- Issue app token ---

def _ttl_minutes_from_delta(expires_delta: timedelta | None) -> int:
    if expires_delta is None:
        return settings.ACCESS_TOKEN_EXPIRE_MINUTES
    seconds = expires_delta.total_seconds()
    if seconds == -1:
        return 365 * 24 * 60
    if seconds <= 0:
        return settings.ACCESS_TOKEN_EXPIRE_MINUTES
    return max(1, int(seconds / 60))


async def issue_app_token(
    db: AsyncSession,
    *,
    user: User,
    login_method: str,
    ip: str | None = None,
    user_agent: str | None = None,
    expires_delta: timedelta | None = None,
    oidc_sid: str | None = None,
) -> str:
    """Create session + app JWT with claim sid. Returns access_token string."""
    session = await issue_session(
        db,
        user_id=user.id,
        login_method=login_method,
        ttl_minutes=_ttl_minutes_from_delta(expires_delta),
        ip=ip,
        user_agent=user_agent,
        oidc_sid=oidc_sid,
    )
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    return create_access_token(
        subject=user.username,
        role=role,
        full_name=user.full_name,
        expires_delta=expires_delta,
        session_id=session.id,
    )


# --- Helpers ---

def device_label_from_ua(ua: str | None) -> str | None:
    """Simple heuristic: extract browser + OS from User-Agent."""
    if not ua:
        return None
    ua_lower = ua.lower()
    if "mobile" in ua_lower or "android" in ua_lower:
        return "Mobile"
    if "windows" in ua_lower:
        return "Windows"
    if "mac os" in ua_lower or "macos" in ua_lower:
        return "macOS"
    if "linux" in ua_lower:
        return "Linux"
    return None
