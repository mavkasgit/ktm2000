import logging
import socket
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import bcrypt
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from jose import jwt
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.config import settings
from app.core.security import TokenError, create_break_glass_token, decode_access_token
from app.models.user import User, UserRole
from app.models.user_session import UserSession
from app.schemas.auth import (
    AvatarSeedUpdate,
    BreakGlassLoginRequest,
    MeResponse,
    ProfileUpdateRequest,
    ProfileUpdateResponse,
    RoleSections,
    RolesResponse,
    TokenResponse,
)
from app.seeds.canon.dependencies import get_plant_config
from app.seeds.canon.models import PlantConfig
from app.schemas.oidc_auth import (
    OidcCallbackRequest,
    OidcConfigResponse,
    OidcLogoutUrlResponse,
)
from app.schemas.session import (
    LoginEventListOut,
    LoginEventOut,
    MAX_LOGIN_EVENTS_SHOWN,
)
from app.services.oidc_auth_service import OidcAuthService
from app.services.session_service import (
    revoke_session_simple,
    revoke_sessions_for_user,
    revoke_by_oidc_sid,
    revoke_all,
    is_logout_jti_used,
    mark_logout_jti_used,
    cleanup_logout_jti,
    record_login_event,
    list_login_events,
    device_label_from_ua,
)
from app.services.unified_profile_service import (
    apply_profile_to_user,
    profile_sync_enabled,
    push_profile_by_sub,
    sync_local_from_idp,
)
from app.services.authentik_client import AuthentikAdminError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _request_meta(request: Request) -> tuple[str, str]:
    ip = request.client.host if request.client else "unknown"
    if forwarded := request.headers.get("X-Forwarded-For"):
        ip = forwarded.split(",")[0].strip()
    ua = request.headers.get("User-Agent", "unknown")
    return ip, ua


def _is_db_port_open() -> bool:
    try:
        from urllib.parse import urlparse
        url_str = settings.DATABASE_URL
        if "+asyncpg" in url_str:
            url_str = url_str.replace("postgresql+asyncpg://", "http://")
        elif "postgresql://" in url_str:
            url_str = url_str.replace("postgresql://", "http://")
        parsed = urlparse(url_str)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 5432
        with socket.create_connection((host, port), timeout=0.1):
            return True
    except Exception:
        return False


def _record_break_glass_event(
    event_type: str,
    username_attempted: str,
    ip_address: str,
    user_agent: str,
    corr_id: str | None = None,
    details: dict | None = None,
):
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


# ─── OIDC / Authentik bridge ──────────────────────────────────────────────────


@router.get("/oidc/config", response_model=OidcConfigResponse)
async def oidc_config() -> OidcConfigResponse:
    """
    Public OIDC client config for FE (authorize URL + PKCE params).
    When disabled: ``enabled=false`` and null fields (break-glass login still available).
    """
    return OidcConfigResponse(**OidcAuthService.public_config())


@router.post("/oidc/callback", response_model=TokenResponse)
async def oidc_callback(
    payload: OidcCallbackRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Exchange authorization code (+ PKCE verifier), validate id_token via JWKS,
    link local User (authentik_sub → username/email → JIT), issue app JWT + sid.
    """
    ip, ua = _request_meta(request)
    service = OidcAuthService(db)
    result = await service.handle_callback(
        code=payload.code,
        code_verifier=payload.code_verifier,
        redirect_uri=payload.redirect_uri,
        ip=ip,
        user_agent=ua,
    )
    return TokenResponse(
        access_token=result["access_token"],
        token_type=result.get("token_type", "bearer"),
        id_token=result.get("id_token"),
    )


@router.get("/oidc/logout-url", response_model=OidcLogoutUrlResponse)
async def oidc_logout_url(
    id_token_hint: str | None = Query(None, description="OIDC id_token for Authentik end-session"),
    post_logout_redirect_uri: str | None = Query(
        None, description="Allowed post-logout landing (requires id_token_hint)"
    ),
) -> OidcLogoutUrlResponse:
    """Authentik end_session URL for FE.

    With registered post-logout URIs Authentik requires ``id_token_hint`` whenever
    ``post_logout_redirect_uri`` is set — otherwise 400 malformed.
    """
    if not OidcAuthService.is_enabled():
        return OidcLogoutUrlResponse(enabled=False, logout_url=None)
    return OidcLogoutUrlResponse(
        enabled=True,
        logout_url=OidcAuthService.logout_url(
            id_token_hint=id_token_hint,
            post_logout_redirect_uri=post_logout_redirect_uri,
        ),
    )


@router.get("/frontchannel-logout")
async def frontchannel_logout():
    """OIDC Front-Channel Logout (public). Authentik loads in iframe.

    Same-origin (http://192.168.100.200:8082) → can clear localStorage/sessionStorage.
    """
    return HTMLResponse(
        content="""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Logout</title></head>
<body><script>
for (const key of Object.keys(localStorage)) localStorage.removeItem(key);
for (const key of Object.keys(sessionStorage)) sessionStorage.removeItem(key);
</script></body></html>"""
    )


@router.post("/backchannel-logout")
async def backchannel_logout(
    logout_token: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """OIDC Back-Channel Logout (public). Authentik POSTs logout_token form field.

    Phase-1 SLO:
      - replay protection via jti (one-time use);
      - if sid present: revoke only sessions with that IdP sid (not all user sessions);
      - if sid absent (e.g. user deactivation): revoke all sessions by sub;
      - audit: session_revoke event with source="authentik_backchannel".

    Unknown sub is 200 no-op (no enumeration). Invalid token -> 400.
    """
    if not logout_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_logout_token",
        )

    service = OidcAuthService(db)
    try:
        claims = await service.validate_logout_token(str(logout_token).strip())
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_logout_token",
        ) from exc

    # Replay protection: jti is one-time use (OIDC Back-Channel Logout 1.0)
    if claims.jti and await is_logout_jti_used(db, claims.jti):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="replay_logout_token",
        )

    user = await db.scalar(select(User).where(User.authentik_sub == claims.sub))
    revoked = 0
    if user is not None:
        if claims.sid:
            revoked_ids = await revoke_by_oidc_sid(
                db, user_id=user.id, oidc_sid=claims.sid, reason="backchannel_logout"
            )
            revoked = len(revoked_ids)
        else:
            revoked = await revoke_all(
                db, user_id=user.id, reason="backchannel_logout"
            )
        await record_login_event(
            db,
            event_type="session_revoke",
            success=True,
            user_id=user.id,
            username_attempted=user.username,
            details={
                "reason": "backchannel_logout",
                "source": "authentik_backchannel",
                "oidc_sid": claims.sid,
                "revoked": revoked,
            },
        )

    # jti is recorded even for unknown sub: valid token is considered consumed.
    # Row lives until token exp — replay after that is impossible by definition.
    if claims.jti:
        exp_dt = (
            datetime.fromtimestamp(claims.exp, tz=timezone.utc)
            if claims.exp
            else datetime.now(timezone.utc) + timedelta(minutes=10)
        )
        try:
            await mark_logout_jti_used(db, claims.jti, expires_at=exp_dt)
        except IntegrityError as exc:
            # Race on duplicate delivery: jti already recorded -> replay
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="replay_logout_token",
            ) from exc
        await cleanup_logout_jti(db)

    return JSONResponse(
        content={"status": "ok", "revoked": revoked},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/break-glass/login", response_model=TokenResponse)
async def break_glass_login(
    payload: BreakGlassLoginRequest,
    request: Request,
) -> TokenResponse:
    """
    Аварийный (Break Glass) вход по паролю.
    Изолирован от таблицы users — используется, когда Authentik недоступен.
    """
    ip, ua = _request_meta(request)
    bg_user = settings.BREAK_GLASS_USER or "emergency_admin"

    if not settings.BREAK_GLASS_ENABLED:
        _record_break_glass_event(
            "login_disabled",
            username_attempted=bg_user,
            ip_address=ip,
            user_agent=ua,
            details={"reason": "break_glass_disabled"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Аварийный доступ отключен",
        )

    password_ok = False
    if settings.BREAK_GLASS_PASSWORD:
        password_ok = payload.password == settings.BREAK_GLASS_PASSWORD
    elif settings.BREAK_GLASS_PASSWORD_HASH:
        try:
            password_ok = bcrypt.checkpw(
                payload.password.encode("utf-8"),
                settings.BREAK_GLASS_PASSWORD_HASH.encode("utf-8"),
            )
        except Exception:
            password_ok = False

    if not password_ok:
        _record_break_glass_event(
            "login_failure",
            username_attempted=bg_user,
            ip_address=ip,
            user_agent=ua,
            details={"reason": "invalid_credentials"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный пароль аварийного доступа",
        )

    corr_id = str(uuid4())
    token = create_break_glass_token(bg_user, corr_id=corr_id)

    _record_break_glass_event(
        "login_success",
        username_attempted=bg_user,
        ip_address=ip,
        user_agent=ua,
        corr_id=corr_id,
        details={"method": "break_glass"},
    )

    return TokenResponse(access_token=token, token_type="bearer")


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Revoke current session (JWT claim sid). Auth required (Bearer).

    Idempotent 204: already-revoked / missing sid still 204 when JWT is valid.
    Missing or invalid token → 401. Magic ``admin`` under DEV_BYPASS → 204 no-op.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = auth_header[7:]
    if token == "admin":
        return

    try:
        payload = decode_access_token(token)
    except TokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Break Glass: no session/user tables to update
    if payload.get("is_break_glass") is True:
        ip, ua = _request_meta(request)
        _record_break_glass_event(
            "logout",
            username_attempted=payload.get("sub", "emergency_admin"),
            ip_address=ip,
            user_agent=ua,
            corr_id=payload.get("corr_id"),
            details={"source": "emergency_access", "method": "break_glass"},
        )
        return

    subject = payload.get("username") or payload.get("sub")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    sid_raw = payload.get("sid")
    session_id: UUID | None = None
    if sid_raw:
        try:
            session_id = UUID(str(sid_raw))
        except (ValueError, TypeError):
            session_id = None

    if session_id is None:
        return

    user = await db.scalar(
        select(User).where(or_(User.username == subject, User.email == subject))
    )
    if user is None:
        return

    session = await db.get(UserSession, session_id)
    if session is not None and session.user_id == user.id and session.revoked_at is None:
        await revoke_session_simple(db, session_id)


@router.get("/roles", response_model=RolesResponse)
async def roles(config: PlantConfig = Depends(get_plant_config)) -> RolesResponse:
    """Справочник ролей: коды, подписи и допустимые разделы навигации (публичный).

    Без ``require_role`` — каталог нужен любому авторизованному для построения
    навигации и подписей ролей на клиенте.
    Данные — DisplayCanon.roles из PlantConfig (ADR-0004, тикет #26).
    """
    return RolesResponse(
        roles=[
            RoleSections(code=entry.code, label=entry.label, sections=entry.sections)
            for entry in config.display.roles.roles
        ]
    )


@router.get("/me", response_model=MeResponse)
async def me(
    refresh: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    """Current user; pulls unified profile from Authentik when linked + API configured."""
    user = current_user

    if getattr(user, "is_break_glass", False):
        return MeResponse(
            id=0,
            username=user.username,
            email=None,
            full_name=user.full_name or "Emergency Access Admin",
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

    if user.authentik_sub and profile_sync_enabled():
        now = datetime.now(timezone.utc)
        ttl = settings.AUTHENTIK_PROFILE_TTL_SECONDS

        need_pull = True
        if refresh != 1 and ttl > 0 and user.profile_synced_at is not None:
            synced_at = user.profile_synced_at
            if synced_at.tzinfo is None:
                synced_at = synced_at.replace(tzinfo=timezone.utc)
            if (now - synced_at).total_seconds() < ttl:
                need_pull = False

        if need_pull:
            try:
                snapshot = await sync_local_from_idp(
                    authentik_sub=user.authentik_sub,
                    local_full_name=user.full_name,
                    local_avatar_seed=user.avatar_seed,
                    local_locale=user.locale,
                    local_theme=user.theme,
                    local_email=user.email,
                )
                if snapshot is not None:
                    apply_profile_to_user(user, snapshot)
                
                user.profile_synced_at = now
                db.add(user)
                await db.commit()
                await db.refresh(user)
            except Exception:
                try:
                    user.profile_synced_at = now
                    db.add(user)
                    await db.commit()
                    await db.refresh(user)
                except Exception:
                    pass

    data = MeResponse.model_validate(user)
    data.authentik_linked = bool(user.authentik_sub)
    data.profile_sot = (
        "authentik" if (user.authentik_sub and profile_sync_enabled()) else "local"
    )
    return data


@router.patch("/me/profile", response_model=ProfileUpdateResponse)
async def update_my_profile(
    payload: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileUpdateResponse:
    """Обновить display-профиль (locale / theme). SoT = Authentik.

    ФИО и email — read-only для пользователя (канон user-settings 2.0.0):
    они задаются администратором IdP, приложение только читает и кэширует.
    Попытка изменить → 403. Аватар редактируется через отдельный
    ``PATCH /auth/me/avatar``.
    """
    user = current_user
    if getattr(user, "is_break_glass", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Break glass users cannot update profile",
        )

    if payload.full_name is not None or payload.email is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Изменение ФИО/email недоступно, обратитесь к администратору",
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

    if user.authentik_sub and profile_sync_enabled():
        try:
            remote = await push_profile_by_sub(
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
            user.profile_synced_at = datetime.now(timezone.utc)
        except AuthentikAdminError as exc:
            raise HTTPException(
                status_code=exc.status_code or 502,
                detail=exc.message,
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


@router.patch("/me/avatar", response_model=ProfileUpdateResponse)
async def update_my_avatar(
    payload: AvatarSeedUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileUpdateResponse:
    """Установить или сбросить avatar_seed. При SSO — пишет в Authentik attributes."""
    user = current_user
    if getattr(user, "is_break_glass", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Break glass users cannot update profile",
        )

    if user.authentik_sub and profile_sync_enabled():
        try:
            remote = await push_profile_by_sub(
                user.authentik_sub,
                avatar_seed=payload.avatar_seed,
            )
            user.avatar_seed = remote.avatar_seed
            if remote.full_name:
                user.full_name = remote.full_name
            user.profile_synced_at = datetime.now(timezone.utc)
        except AuthentikAdminError as exc:
            raise HTTPException(
                status_code=exc.status_code or 502,
                detail=exc.message,
            ) from exc
    else:
        user.avatar_seed = payload.avatar_seed

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


@router.get("/me/links")
async def get_me_links(
    current_user: User = Depends(get_current_user),
) -> dict:
    """IdP deep-links для профиля (каноничный путь). Любой авторизованный пользователь."""
    from app.services.authentik_admin_service import idp_links_data

    return idp_links_data()


@router.get("/me/login-events", response_model=LoginEventListOut)
async def list_me_login_events(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LoginEventListOut:
    """История входов текущего пользователя (каноничный путь /auth/me/*).

    Контракт канона user-settings 2.1.0: {events: [...последние 10 по
    created_at DESC], total: N} — паритет с GET /auth/sessions.
    """
    events = await list_login_events(db, user_id=current_user.id)
    out = [
        LoginEventOut(
            id=e.id,
            event_type=e.event_type,
            success=e.success,
            ip_address=e.ip_address,
            device_label=device_label_from_ua(e.user_agent),
            login_method=(e.details or {}).get("method") if e.details else None,
            created_at=e.created_at,
            failure_reason=(e.details or {}).get("reason") if e.details else None,
        )
        for e in events
    ]
    return LoginEventListOut(
        events=out[:MAX_LOGIN_EVENTS_SHOWN],
        total=len(out),
    )
