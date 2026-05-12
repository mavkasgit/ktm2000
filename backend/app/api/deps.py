from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Callable, Sequence

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)

WRITER_ROLES: frozenset[UserRole] = frozenset(
    {UserRole.admin, UserRole.section_manager, UserRole.operator}
)
READER_ROLES: frozenset[UserRole] = frozenset(
    {UserRole.admin, UserRole.planner, UserRole.section_manager, UserRole.operator, UserRole.viewer}
)


def require_role(allowed_roles: Sequence[UserRole]) -> Callable:
    """Create a FastAPI dependency that checks the current user has one of the allowed roles."""

    async def _guard(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user

    return _guard


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        if settings.ENV != "dev":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        user = await db.scalar(select(User).where(User.is_active).limit(1))
        if user is None:
            user = User(
                email="dev@local",
                role=UserRole.admin,
                full_name="Dev User",
                is_active=True,
            )
            db.add(user)
            await db.flush()
        return user

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user_email = payload.get("sub")
    if not user_email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    user = await db.scalar(select(User).where(User.email == user_email))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is disabled")
    return user
