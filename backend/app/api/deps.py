from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Callable, Sequence

from app.core.database import get_db
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
    {UserRole.admin, UserRole.planner, UserRole.section_manager, UserRole.operator, UserRole.viewer}
)


def _fake_user() -> User:
    """Dev-mode placeholder user. email 'system@local' signals a fake/dev user."""
    return User(
        id=1,
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
            from fastapi import HTTPException, status
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user

    return _guard


async def get_current_user(
    db: AsyncSession = Depends(get_db),
) -> User:
    # TODO(auth): replace with real token validation + DB lookup
    return _fake_user()
