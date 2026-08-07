"""Business logic for user sessions and login audit events (KTM host adapter).

Delegates the shared must-match module (app/services/session_core.py) and
keeps the KTM-specific session domain: login_method vocabulary, device-label
heuristic, JWT claim names and TTL policy.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User
from app.models.user_login_event import UserLoginEvent
from app.models.user_session import UserSession
from app.repositories.login_event_repository import LoginEventRepository
from app.repositories.logout_jti_repository import LogoutJtiRepository
from app.repositories.session_repository import SessionRepository
from app.services import session_core
from app.services.session_core import JwtConfig, SessionCoreConfig, SessionCoreError

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


def _core_config() -> SessionCoreConfig:
    return SessionCoreConfig(
        session_repo=session_repo,
        login_event_repo=login_event_repo,
        logout_jti_repo=logout_jti_repo,
        device_label_fn=device_label_from_ua,
        login_methods=LOGIN_METHODS,
        revoke_reasons=REVOKE_REASONS,
        event_types=EVENT_TYPES,
        last_seen_throttle_seconds=getattr(
            settings, "SESSION_LAST_SEEN_THROTTLE_SECONDS", 300
        ),
        min_ttl_minutes=1,
    )


def _jwt_config() -> JwtConfig:
    return JwtConfig(
        secret_key=settings.JWT_SECRET_KEY or settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
        default_ttl_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
    )


def _translate_input_error(exc: SessionCoreError) -> ValueError:
    """Map invalid-input SessionCoreError to the legacy ValueError contract."""
    return ValueError(exc.message)


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
    try:
        return await session_core.issue_session(
            _core_config(),
            db,
            user_id=user_id,
            login_method=login_method,
            ttl_minutes=ttl_minutes,
            ip=ip,
            user_agent=user_agent,
            oidc_sid=oidc_sid,
        )
    except SessionCoreError as exc:
        raise _translate_input_error(exc) from exc


async def get_session_by_id(db: AsyncSession, session_id: UUID) -> UserSession | None:
    return await session_repo.get_by_id(db, session_id)


async def assert_session_active(db: AsyncSession, session_id: UUID) -> UserSession:
    """Raise SessionInactiveError if missing / revoked / expired."""
    try:
        return await session_core.assert_session_active(_core_config(), db, session_id)
    except SessionCoreError as exc:
        raise SessionInactiveError(exc.message, exc.code) from exc


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
    try:
        return await session_core.revoke_by_oidc_sid(
            _core_config(),
            db,
            user_id=user_id,
            oidc_sid=oidc_sid,
            reason=reason,
        )
    except SessionCoreError as exc:
        raise _translate_input_error(exc) from exc


# --- Logout JTI replay protection ---

async def is_logout_jti_used(db: AsyncSession, jti: str) -> bool:
    return await session_core.is_logout_jti_used(_core_config(), db, jti)


async def mark_logout_jti_used(
    db: AsyncSession, jti: str, *, expires_at: datetime
) -> None:
    await session_core.mark_logout_jti_used(_core_config(), db, jti, expires_at=expires_at)


async def cleanup_logout_jti(db: AsyncSession) -> int:
    """Opportunistic purge of consumed jti with expired exp."""
    return await session_core.cleanup_logout_jti(_core_config(), db)


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
    try:
        return await session_core.record_login(
            _core_config(),
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
    except SessionCoreError as exc:
        raise _translate_input_error(exc) from exc


# --- Session list ---

async def list_active_sessions(db: AsyncSession, *, user_id: int) -> list[UserSession]:
    return await session_repo.list_active_for_user(db, user_id)


async def list_login_events(
    db: AsyncSession,
    *,
    user_id: int,
) -> list[UserLoginEvent]:
    """Login history window (retention days) for the user, newest first."""
    since = datetime.now(timezone.utc) - timedelta(days=settings.LOGIN_EVENTS_RETENTION_DAYS)
    return await login_event_repo.list_for_user(db, user_id, since=since)


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
    claims: dict = {"role": role}
    if user.full_name is not None:
        claims["full_name"] = user.full_name
    return session_core.create_access_token(
        _jwt_config(),
        subject=user.username,
        claims=claims,
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
