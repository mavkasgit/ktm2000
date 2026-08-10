from dataclasses import dataclass, field
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Callable, Sequence
from uuid import UUID

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_access_token, TokenError
from app.models.user import User, UserRole
from app.models.user_session import UserSession
from app.models.work_task import WorkTask
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


def _sid_claim(payload: dict) -> str | None:
    """The ``sid`` claim as a non-empty string, else None (single presence shape)."""
    return payload.get("sid") or None


async def _require_sid_active(db: AsyncSession, payload: dict) -> UserSession:
    """Require JWT claim sid naming an ACTIVE server session (regular kind).

    The ONLY sid validation in the auth gate — structurally unreachable from
    the break-glass path (ADR-0006). Returns the session so the caller can
    cross-check ownership against ``sub``.
    """
    sid_raw = _sid_claim(payload)
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
        return await assert_session_active(db, session_id)
    except SessionInactiveError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session revoked or expired",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def _decode_bearer_payload(request: Request) -> dict:
    """Strict-mode token extraction + verification (no sid semantics here)."""
    auth_header = request.headers.get("Authorization")
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
        return decode_access_token(token)
    except TokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | _BreakGlassUser:
    """Classify the token kind and apply its per-kind identity rules (ADR-0006).

    dev (DEV_BYPASS_AUTH) — escape hatch: sid optional, magic ``admin`` /
    ``system@local``. break glass — no sid, no session lookup. regular — the
    only path that requires an ACTIVE session and cross-checks ``sub`` vs
    the session owner.
    """
    if settings.DEV_BYPASS_AUTH:
        return await _get_current_user_dev(request, db)
    return await _get_current_user_strict(request, db)


async def _get_current_user_dev(
    request: Request,
    db: AsyncSession,
) -> User | _BreakGlassUser:
    """Dev/test escape hatch: JWT if valid (sid optional), magic admin, else system@local."""
    auth_header = request.headers.get("Authorization")

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


async def _get_current_user_strict(
    request: Request,
    db: AsyncSession,
) -> User | _BreakGlassUser:
    """Prod auth: decode, classify kind, then apply per-kind identity rules."""
    payload = await _decode_bearer_payload(request)

    subject: str | None = payload.get("sub")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Break Glass (emergency) token: no sid, bypasses users table & session assertion
    if payload.get("is_break_glass") is True:
        return await _strict_break_glass_identity(payload)

    return await _strict_regular_identity(db, payload, subject)


async def _strict_break_glass_identity(payload: dict) -> _BreakGlassUser:
    """Break-glass identity: gate on flag + config only; sid must be absent."""
    if not settings.BREAK_GLASS_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Break glass access is disabled",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Hybrid is_break_glass + sid is an anomaly: reject, never mask it (ADR-0006)
    if _sid_claim(payload):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _make_break_glass_user()


async def _strict_regular_identity(
    db: AsyncSession,
    payload: dict,
    subject: str,
) -> User:
    """Regular identity: the ONLY path that validates sid (active + owned by sub)."""
    session = await _require_sid_active(db, payload)

    user = await _load_user_by_subject(db, subject)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if session.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    return user


def _make_break_glass_user() -> _BreakGlassUser:
    return _BreakGlassUser()


# ─── Single-window lock (route-layer) ─────────────────────────────────────────


LOCKED_SECTION_ERROR = "Section is locked to single-window context"


def get_single_window_locked_section_id(
    x_shopfloor_single_section_id: int | None = Header(default=None, alias="X-Shopfloor-Single-Section-Id"),
) -> int | None:
    return x_shopfloor_single_section_id


def _ensure_section_lock(section_id: int | None, locked_section_id: int | None) -> None:
    if locked_section_id is not None and section_id != locked_section_id:
        raise HTTPException(status_code=403, detail=LOCKED_SECTION_ERROR)


async def _ensure_task_lock(
    db: AsyncSession,
    task_id: int,
    locked_section_id: int | None,
    current_user: User | None = None,
) -> None:
    if current_user is not None and current_user.role == UserRole.transporter:
        return
    if locked_section_id is None:
        return
    task_section_id = await db.scalar(select(WorkTask.section_id).where(WorkTask.id == task_id))
    if task_section_id is not None and task_section_id != locked_section_id:
        raise HTTPException(status_code=403, detail=LOCKED_SECTION_ERROR)
