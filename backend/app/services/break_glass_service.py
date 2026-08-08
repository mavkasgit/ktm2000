"""Аварийный (Break Glass) доступ — host-адаптер (KTM).

Изолирован от таблицы users и стандартного сервиса входа: проверка по env-конфигу
(BREAK_GLASS_*), сессий не создаёт, токен без ``sid`` (ADR-0006). Аудит — в лог
(CRITICAL на успешный вход). В отличие от HRMS — без записи login-events в БД.

Доменные ошибки — через ``KTMException`` (глобальный хендлер мапит в JSON);
роутер их не ловит.
"""

from __future__ import annotations

import logging
from uuid import uuid4

import bcrypt

from app.core.config import settings
from app.core.exceptions import KTMException
from app.core.security import create_break_glass_token
from app.schemas.auth import TokenResponse

logger = logging.getLogger(__name__)


def record_break_glass_event(
    event_type: str,
    username_attempted: str,
    ip_address: str,
    user_agent: str,
    corr_id: str | None = None,
    details: dict | None = None,
) -> None:
    level = logging.CRITICAL if event_type == "login_success" else logging.WARNING
    logger.log(
        level,
        "Break Glass %s | user=%s ip=%s ua=%s corr_id=%s details=%s",
        event_type,
        username_attempted,
        ip_address,
        user_agent,
        corr_id or "none",
        details or {},
    )


async def break_glass_login(
    *,
    password: str,
    ip: str,
    user_agent: str,
) -> TokenResponse:
    """Аварийный вход по паролю. Не создаёт запись в users и сессию."""
    bg_user = settings.BREAK_GLASS_USER or "emergency_admin"

    if not settings.BREAK_GLASS_ENABLED:
        record_break_glass_event(
            "login_disabled",
            username_attempted=bg_user,
            ip_address=ip,
            user_agent=user_agent,
            details={"reason": "break_glass_disabled"},
        )
        raise KTMException(
            "Аварийный доступ отключен",
            error_code="break_glass_disabled",
            status_code=401,
        )

    password_ok = False
    if settings.BREAK_GLASS_PASSWORD:
        password_ok = password == settings.BREAK_GLASS_PASSWORD
    elif settings.BREAK_GLASS_PASSWORD_HASH:
        try:
            password_ok = bcrypt.checkpw(
                password.encode("utf-8"),
                settings.BREAK_GLASS_PASSWORD_HASH.encode("utf-8"),
            )
        except Exception:
            password_ok = False

    if not password_ok:
        record_break_glass_event(
            "login_failure",
            username_attempted=bg_user,
            ip_address=ip,
            user_agent=user_agent,
            details={"reason": "invalid_credentials"},
        )
        raise KTMException(
            "Неверный пароль аварийного доступа",
            error_code="break_glass_invalid_credentials",
            status_code=401,
        )

    corr_id = str(uuid4())
    token = create_break_glass_token(bg_user, corr_id=corr_id)

    record_break_glass_event(
        "login_success",
        username_attempted=bg_user,
        ip_address=ip,
        user_agent=user_agent,
        corr_id=corr_id,
        details={"method": "break_glass"},
    )

    return TokenResponse(access_token=token, token_type="bearer")
