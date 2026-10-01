"""Вход в тестах: пользователь нужной роли и его Bearer-заголовок.

Тест-хелпер, а не фикстура: ролей в одном тесте бывает несколько, а создание
пользователя — часть сетапа самого теста (`session` уже открыт).
"""
from __future__ import annotations

from app.models.user import User, UserRole
from app.services.session_service import issue_app_token
from sqlalchemy.ext.asyncio import AsyncSession


async def user_headers(
    session: AsyncSession,
    role: UserRole,
    username: str,
) -> tuple[User, dict[str, str]]:
    """Пользователь роли `role` + заголовок с его токеном.

    Токен — настоящий app-токен с claim `sid`: в strict-режиме
    (`DEV_BYPASS_AUTH=false`) серверная сессия обязательна, и голый
    `create_access_token` там даёт 401 (ADR-0006).
    """
    user = User(
        username=username,
        email=f"{username}@example.com",
        full_name=f"User {username}",
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    token = await issue_app_token(session, user=user, login_method="oidc")
    await session.commit()
    return user, {"Authorization": f"Bearer {token}"}
