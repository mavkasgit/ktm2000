"""Профиль текущего пользователя — host-адаптер (KTM) поверх unified_profile_service.

Поля display-профиля (full_name/email/avatar_seed/locale/theme): SoT = Authentik,
локальная БД — кэш. Канон user-settings 2.0.0: ФИО/email read-only (403 при
попытке изменить), аватар — через отдельный ``PATCH /auth/me/avatar``.

Доменные ошибки — через ``KTMException``/``NotFoundError`` (глобальный хендлер);
роутер их не ловит.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import KTMException, NotFoundError
from app.models.user import User, UserRole
from app.schemas.auth import (
    MeResponse,
    ProfileUpdateRequest,
    ProfileUpdateResponse,
)
from app.services import unified_profile_service as ups
from app.services.authentik_client import AuthentikAdminError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _load_me_user(db: AsyncSession, username: str) -> User:
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalars().first()
    if not user:
        raise NotFoundError("Пользователь не найден")
    return user


async def get_me(
    db: AsyncSession,
    *,
    username: str,
    full_name: str | None = None,
    is_break_glass: bool = False,
    refresh: bool = False,
) -> MeResponse:
    """GET /auth/me — унифицированный профиль (IdP pull best-effort)."""
    if is_break_glass:
        return MeResponse(
            id=0,
            username=username,
            email=None,
            full_name=full_name or "Emergency Access Admin",
            role=UserRole.admin,
            section_id=None,
            is_active=True,
            avatar_seed="emergency",
            locale="ru",
            theme="light",
            authentik_linked=False,
            profile_sot="local",
            is_break_glass=True,
        )

    user = await _load_me_user(db, username)

    await ups.ensure_profile_fresh(db, user, refresh=refresh)

    data = MeResponse.model_validate(user)
    data.authentik_linked = bool(user.authentik_sub)
    data.profile_sot = (
        "authentik" if (user.authentik_sub and ups.profile_sync_enabled()) else "local"
    )
    return data


async def update_my_profile(
    db: AsyncSession,
    *,
    username: str,
    is_break_glass: bool,
    payload: ProfileUpdateRequest,
) -> ProfileUpdateResponse:
    """Обновить display-профиль (locale / theme). SoT = Authentik.

    ФИО и email — read-only для пользователя (канон user-settings 2.0.0):
    они задаются администратором IdP, приложение только читает и кэширует.
    Попытка изменить → 403. Аватар редактируется через отдельный
    ``PATCH /auth/me/avatar``.
    """
    if is_break_glass:
        raise KTMException(
            "Break glass users cannot update profile",
            error_code="break_glass_not_allowed",
            status_code=403,
        )

    user = await _load_me_user(db, username)

    if payload.full_name is not None or payload.email is not None:
        raise KTMException(
            "Изменение ФИО/email недоступно, обратитесь к администратору",
            error_code="read_only_field",
            status_code=403,
        )

    has_any = payload.locale is not None or payload.theme is not None
    if not has_any:
        return ProfileUpdateResponse(
            full_name=user.full_name,
            avatar_seed=user.avatar_seed,
            email=user.email,
            locale=user.locale,
            theme=user.theme,
        )

    want_locale = payload.locale
    want_theme = payload.theme
    email_out: str | None = user.email

    if user.authentik_sub and ups.profile_sync_enabled():
        try:
            remote = await ups.push_profile_by_sub(
                user.authentik_sub,
                locale=want_locale,
                theme=want_theme,
            )
            if remote.full_name:
                user.full_name = remote.full_name
            if want_locale is not None:
                user.locale = remote.locale or want_locale
            if want_theme is not None:
                user.theme = remote.theme or want_theme
            email_out = remote.email or user.email
            user.profile_synced_at = _utcnow()
        except AuthentikAdminError as exc:
            raise KTMException(
                exc.message,
                error_code="authentik_profile_error",
                status_code=exc.status_code or 502,
            ) from exc
    else:
        if want_locale is not None:
            user.locale = want_locale
        if want_theme is not None:
            user.theme = want_theme

    db.add(user)
    await db.commit()
    await db.refresh(user)
    return ProfileUpdateResponse(
        full_name=user.full_name,
        avatar_seed=user.avatar_seed,
        email=email_out,
        locale=user.locale,
        theme=user.theme,
    )


async def update_my_avatar(
    db: AsyncSession,
    *,
    username: str,
    is_break_glass: bool,
    avatar_seed: str | None,
) -> ProfileUpdateResponse:
    """Установить или сбросить avatar_seed. При SSO — пишет в Authentik attributes."""
    if is_break_glass:
        raise KTMException(
            "Break glass users cannot update profile",
            error_code="break_glass_not_allowed",
            status_code=403,
        )

    user = await _load_me_user(db, username)

    if user.authentik_sub and ups.profile_sync_enabled():
        try:
            remote = await ups.push_profile_by_sub(
                user.authentik_sub,
                avatar_seed=avatar_seed,
            )
            user.avatar_seed = remote.avatar_seed
            if remote.full_name:
                user.full_name = remote.full_name
            user.profile_synced_at = _utcnow()
        except AuthentikAdminError as exc:
            raise KTMException(
                exc.message,
                error_code="authentik_profile_error",
                status_code=exc.status_code or 502,
            ) from exc
    else:
        user.avatar_seed = avatar_seed

    db.add(user)
    await db.commit()
    await db.refresh(user)
    return ProfileUpdateResponse(
        full_name=user.full_name,
        avatar_seed=user.avatar_seed,
        email=user.email,
        locale=user.locale,
        theme=user.theme,
    )