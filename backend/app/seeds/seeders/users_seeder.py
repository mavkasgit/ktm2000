from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole


async def seed_users(db: AsyncSession, force: bool = False) -> dict[int, User]:
    """Ensure system user exists for dev-mode _fake_user(). Returns {id: user} map."""
    result: dict[int, User] = {}

    system_user = await db.scalar(select(User).where(User.email == "system@local"))
    if system_user is None:
        system_user = User(
            email="system@local",
            password_hash="",
            role=UserRole.admin,
            full_name="System User",
            is_active=True,
        )
        db.add(system_user)
        await db.flush()

    result[system_user.id] = system_user
    return result
