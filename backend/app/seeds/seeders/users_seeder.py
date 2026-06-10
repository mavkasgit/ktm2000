from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.models.section import Section
from app.core.security import get_password_hash


async def seed_users(db: AsyncSession) -> dict[int, User]:
    """Ensure system user exists and seeds a base set of demo/dev users. Returns user map."""
    from sqlalchemy import text

    result: dict[int, User] = {}

    # 1. Системный пользователь (id=1) для автоматических действий
    system_user = await db.scalar(select(User).where(User.email == "system@local"))
    if system_user is None:
        await db.execute(text("""
            INSERT INTO users (id, username, email, password_hash, full_name, role, is_active)
            OVERRIDING SYSTEM VALUE
            VALUES (1, 'system', 'system@local', '', 'System User', 'admin', true)
        """))
        await db.flush()
        system_user = await db.scalar(select(User).where(User.email == "system@local"))
    elif system_user.id != 1:
        # Delete existing user and recreate with id=1
        await db.execute(text("DELETE FROM users WHERE email = 'system@local'"))
        await db.flush()

        await db.execute(text("""
            INSERT INTO users (id, username, email, password_hash, full_name, role, is_active)
            OVERRIDING SYSTEM VALUE
            VALUES (1, 'system', 'system@local', '', 'System User', 'admin', true)
        """))
        await db.flush()
        system_user = await db.scalar(select(User).where(User.email == "system@local"))

    result[system_user.id] = system_user

    # Находим первый активный участок для привязки менеджера и оператора
    section = await db.scalar(select(Section).where(Section.is_active == True).order_by(Section.id))
    section_id = section.id if section else None

    # Список базовых демонстрационных пользователей
    demo_users_data = [
        {
            "username": "admin",
            "email": "admin@ktm2000.local",
            "password": "admin",
            "full_name": "Администратор",
            "role": UserRole.admin,
            "section_id": None,
        },
        {
            "username": "planner",
            "email": "planner@ktm2000.local",
            "password": "planner",
            "full_name": "Планировщик Главный",
            "role": UserRole.planner,
            "section_id": None,
        },
        {
            "username": "manager",
            "email": "manager@ktm2000.local",
            "password": "manager",
            "full_name": "Начальник Участка",
            "role": UserRole.section_manager,
            "section_id": section_id,
        },
        {
            "username": "operator",
            "email": "operator@ktm2000.local",
            "password": "operator",
            "full_name": "Оператор Цеха",
            "role": UserRole.operator,
            "section_id": section_id,
        },
        {
            "username": "viewer",
            "email": "viewer@ktm2000.local",
            "password": "viewer",
            "full_name": "Наблюдатель",
            "role": UserRole.viewer,
            "section_id": None,
        },
    ]

    for data in demo_users_data:
        user = await db.scalar(select(User).where(User.username == data["username"]))
        if user is None:
            user = User(
                username=data["username"],
                email=data["email"],
                password_hash=get_password_hash(data["password"]),
                full_name=data["full_name"],
                role=data["role"],
                section_id=data["section_id"],
                is_active=True,
            )
            db.add(user)
            await db.flush()
            await db.refresh(user)
        result[user.id] = user

    return result
