from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole


async def seed_users(db: AsyncSession) -> dict[int, User]:
    """Ensure system user exists with id=1 for dev-mode _fake_user(). Returns {id: user} map."""
    from sqlalchemy import text

    result: dict[int, User] = {}

    system_user = await db.scalar(select(User).where(User.email == "system@local"))
    if system_user is None:
        await db.execute(text("""
            INSERT INTO users (id, email, password_hash, full_name, role, is_active)
            OVERRIDING SYSTEM VALUE
            VALUES (1, 'system@local', '', 'System User', 'admin', true)
        """))
        await db.flush()
        system_user = await db.scalar(select(User).where(User.email == "system@local"))
    elif system_user.id != 1:
        # Delete existing user and recreate with id=1
        # Column id is GENERATED ALWAYS identity, so we need raw SQL with OVERRIDING SYSTEM VALUE
        await db.execute(text("DELETE FROM users WHERE email = 'system@local'"))
        await db.flush()

        await db.execute(text("""
            INSERT INTO users (id, email, password_hash, full_name, role, is_active)
            OVERRIDING SYSTEM VALUE
            VALUES (1, 'system@local', '', 'System User', 'admin', true)
        """))
        await db.flush()
        system_user = await db.scalar(select(User).where(User.email == "system@local"))

    result[system_user.id] = system_user
    return result
