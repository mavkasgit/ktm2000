"""App sessions: issue / assert / revoke. JWT claim `sid` = user_sessions.id."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token
from app.models.user import User
from app.models.user_session import UserSession

LOGIN_METHODS = frozenset({"password", "otp", "oidc", "setup_password"})


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
) -> UserSession:
    """Insert session row; expires_at = now + ttl_minutes."""
    if login_method not in LOGIN_METHODS:
        raise ValueError(f"Unknown login_method: {login_method}")
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=max(1, int(ttl_minutes)))
    row = UserSession(
        user_id=user_id,
        expires_at=expires_at,
        login_method=login_method,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def assert_session_active(db: AsyncSession, session_id: UUID) -> UserSession:
    """Raise SessionInactiveError if missing / revoked / expired."""
    session = await db.get(UserSession, session_id)
    if session is None:
        raise SessionInactiveError("Session not found", "session_not_found")
    if session.revoked_at is not None:
        raise SessionInactiveError("Session revoked", "session_revoked")
    expires = session.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= datetime.now(UTC):
        raise SessionInactiveError("Session expired", "session_expired")
    return session


async def revoke_session(db: AsyncSession, session_id: UUID) -> UserSession | None:
    """Soft-revoke by id. Returns row or None if missing. Idempotent if already revoked."""
    session = await db.get(UserSession, session_id)
    if session is None:
        return None
    if session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
        db.add(session)
        await db.flush()
        await db.refresh(session)
    return session


async def revoke_sessions_for_user(
    db: AsyncSession,
    *,
    user_id: int,
    except_id: UUID | None = None,
) -> int:
    """Revoke all non-revoked sessions for user. Returns count updated."""
    now = datetime.now(UTC)
    conditions = [
        UserSession.user_id == user_id,
        UserSession.revoked_at.is_(None),
    ]
    if except_id is not None:
        conditions.append(UserSession.id != except_id)
    result = await db.execute(
        update(UserSession).where(*conditions).values(revoked_at=now)
    )
    await db.flush()
    return int(result.rowcount or 0)


def _ttl_minutes_from_delta(expires_delta: timedelta | None) -> int:
    if expires_delta is None:
        return settings.ACCESS_TOKEN_EXPIRE_MINUTES
    seconds = expires_delta.total_seconds()
    if seconds == -1:
        # JWT without exp — keep a long-lived session row
        return 365 * 24 * 60
    if seconds <= 0:
        return settings.ACCESS_TOKEN_EXPIRE_MINUTES
    return max(1, int(seconds / 60))


async def issue_app_token(
    db: AsyncSession,
    *,
    user: User,
    login_method: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Create session + app JWT with claim sid. Returns access_token string."""
    session = await issue_session(
        db,
        user_id=user.id,
        login_method=login_method,
        ttl_minutes=_ttl_minutes_from_delta(expires_delta),
    )
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    return create_access_token(
        subject=user.username,
        role=role,
        full_name=user.full_name,
        expires_delta=expires_delta,
        session_id=session.id,
    )


async def get_session_by_id(
    db: AsyncSession, session_id: UUID
) -> UserSession | None:
    return await db.get(UserSession, session_id)


async def list_active_sessions(db: AsyncSession, *, user_id: int) -> list[UserSession]:
    now = datetime.now(UTC)
    result = await db.execute(
        select(UserSession)
        .where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
        .order_by(UserSession.created_at.desc())
    )
    return list(result.scalars().all())
