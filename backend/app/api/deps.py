from dataclasses import dataclass, field
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Callable, Sequence
from uuid import UUID

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_access_token, TokenError
from app.models.user import User, UserRole
from app.services.session_service import SessionInactiveError, assert_session_active


@dataclass
class _BreakGlassUser:
    """Minimal User substitute for Break Glass emergency access — bypasses DB."""
    id: int = 0
    username: str = "emergency_admin"
    role: UserRole = UserRole.admin
    full_name: str = "Emergency Access Admin"
    email: str | None = None
    is_active: bool = True
    avatar_seed: str | None = "emergency"
    locale: str | None = "ru"
    theme: str | None = "system"
    authentik_sub: str | None = None
    profile_synced_at = None
    section_id: int | None = None
    section_ids: list[int] = field(default_factory=list)
    is_break_glass: bool = True


WRITER_ROLES: frozenset[UserRole] = frozenset(
    {UserRole.admin, UserRole.section_manager, UserRole.operator}
)
READER_ROLES: frozenset[UserRole] = frozenset(
    {UserRole.admin, UserRole.planner, UserRole.section_manager, UserRole.operator, UserRole.viewer, UserRole.transporter}
)
TRANSFER_WRITER_ROLES: frozenset[UserRole] = frozenset(
    WRITER_ROLES | {UserRole.transporter}
)


def require_role(allowed_roles: Sequence[UserRole]) -> Callable:
    """Create a FastAPI dependency that checks the current user has one of the allowed roles."""

    async def _guard(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user

    return _guard


async def _resolve_magic_admin(db: AsyncSession) -> User | None:
    """Literal Bearer 'admin' — only used when DEV_BYPASS_AUTH is true."""
    return await db.scalar(select(User).where(User.username == "admin"))


async def _load_user_by_subject(db: AsyncSession, subject: str) -> User | None:
    return await db.scalar(
        select(User).where(or_(User.username == subject, User.email == subject))
    )


async def _assert_sid_active(db: AsyncSession, payload: dict) -> UUID:
    """Require JWT claim sid and active server session (strict/prod)."""
    sid_raw = payload.get("sid")
    if not sid_raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        session_id = UUID(str(sid_raw))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        await assert_session_active(db, session_id)
    except SessionInactiveError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session revoked or expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return session_id


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | _BreakGlassUser:
    auth_header = request.headers.get("Authorization")

    # --- DEV bypass mode: JWT if valid (sid optional), magic admin, else system@local ---
    if settings.DEV_BYPASS_AUTH:
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            # Magic bearer (dev/test tools) — gated by DEV_BYPASS_AUTH
            if token == "admin":
                admin = await _resolve_magic_admin(db)
                if admin:
                    return admin
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Admin user not found in database",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            try:
                payload = decode_access_token(token)
                subject = payload.get("sub")
                if subject:
                    user = await _load_user_by_subject(db, subject)
                    if user:
                        return user
            except (TokenError, Exception):
                pass

        # Fallback to globally seeded system@local user if present in DB
        user = await db.scalar(
            select(User).where(
                or_(User.username == "system", User.email == "system@local")
            )
        )
        if user:
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="System user not found in database",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # --- Strict JWT auth mode (prod): require sid + active session ---
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header[7:]

    # Magic Bearer "admin" is dev-only; reject in strict/prod
    if token == "admin":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(token)
    except TokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    subject: str | None = payload.get("sub")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Break Glass (emergency) token: bypass users table & session assertion
    if payload.get("is_break_glass") is True:
        if not settings.BREAK_GLASS_ENABLED:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Break glass access is disabled",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return _make_break_glass_user()

    # Hybrid JWT + server session: claim sid required (except DEV_BYPASS / magic admin)
    await _assert_sid_active(db, payload)

    user = await _load_user_by_subject(db, subject)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    return user


@dataclass
class _BreakGlassUser:
    """Minimal User substitute for Break Glass emergency access — bypasses DB."""
    id: int = 0
    username: str = "emergency_admin"
    role: UserRole = UserRole.admin
    full_name: str = "Emergency Access Admin"
    email: str | None = None
    is_active: bool = True
    avatar_seed: str | None = "emergency"
    locale: str | None = "ru"
    theme: str | None = "system"
    authentik_sub: str | None = None
    profile_synced_at = None
    section_id: int | None = None
    section_ids: list[int] = field(default_factory=list)
    is_break_glass: bool = True


def _make_break_glass_user() -> _BreakGlassUser:
    return _BreakGlassUser()
