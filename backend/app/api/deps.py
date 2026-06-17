from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Callable, Sequence

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_access_token, TokenError
from app.models.user import User, UserRole

# TODO(auth): This module centralises authentication.
# Currently get_current_user returns a fake admin user for development.
# To restore real JWT/token auth, replace the body of get_current_user only.
# All routes already use Depends(get_current_user) — no other changes needed.
# See also: migration 012_seed_system_user (seeds id=1, system@local).

WRITER_ROLES: frozenset[UserRole] = frozenset(
    {UserRole.admin, UserRole.section_manager, UserRole.operator}
)
READER_ROLES: frozenset[UserRole] = frozenset(
    {UserRole.admin, UserRole.planner, UserRole.section_manager, UserRole.operator, UserRole.viewer, UserRole.transporter}
)
TRANSFER_WRITER_ROLES: frozenset[UserRole] = frozenset(
    WRITER_ROLES | {UserRole.transporter}
)


def _fake_user() -> User:
    """Dev-mode placeholder user. email 'system@local' signals a fake/dev user."""
    return User(
        id=1,
        username="system",
        email="system@local",
        password_hash="",
        role=UserRole.admin,
        full_name="System User",
        is_active=True,
    )


def require_role(allowed_roles: Sequence[UserRole]) -> Callable:
    """Create a FastAPI dependency that checks the current user has one of the allowed roles."""

    async def _guard(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user

    return _guard


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    auth_header = request.headers.get("Authorization")

    # --- DEV bypass mode: fallback to system@local ---
    if settings.DEV_BYPASS_AUTH:
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                payload = decode_access_token(token)
                subject = payload.get("sub")
                if subject:
                    user = await db.scalar(
                        select(User).where(
                            or_(User.username == subject, User.email == subject)
                        )
                    )
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
        return _fake_user()

    # --- Strict JWT auth mode ---
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header[7:]

    # Bypass for testing, internal communication, and dev tools (matching HRMS)
    if token == "admin":
        user = await db.scalar(select(User).where(User.username == "admin"))
        if user:
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin user not found in database",
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

    user = await db.scalar(
        select(User).where(
            or_(User.username == subject, User.email == subject)
        )
    )
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
