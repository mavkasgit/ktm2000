"""Seed system user for dev-mode _fake_user(). Remove after real auth is in place."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User, UserRole

router = APIRouter(prefix="/users-seed", tags=["users-seed"])


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def seed_system_user(db: AsyncSession = Depends(get_db)) -> UserOut:
    """Create system user (id=1) if it doesn't exist."""
    existing = await db.scalar(select(User).where(User.id == 1))
    if existing:
        return UserOut.model_validate(existing, from_attributes=True)

    user = User(
        id=1,
        email="system@local",
        password_hash="",
        role=UserRole.admin,
        full_name="System User",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return UserOut.model_validate(user, from_attributes=True)
