from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
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
from app.schemas.oidc_auth import (
    OidcCallbackRequest,
    OidcConfigResponse,
    OidcLogoutUrlResponse,
)
from app.schemas.session import LoginEventListOut
from app.seeds.canon.dependencies import get_plant_config
from app.seeds.canon.models import PlantConfig
from app.services import break_glass_service, profile_service, session_service
from app.services.oidc_auth_service import OidcAuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _request_meta(request: Request) -> tuple[str, str]:
    ip = request.client.host if request.client else "unknown"
    if forwarded := request.headers.get("X-Forwarded-For"):
        ip = forwarded.split(",")[0].strip()
    ua = request.headers.get("User-Agent", "unknown")
    return ip, ua


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

    Phase-1 SLO orchestrated in ``OidcAuthService.handle_backchannel_logout``:
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
    result = await service.handle_backchannel_logout(str(logout_token).strip())
    return JSONResponse(
        content=result,
        headers={"Cache-Control": "no-store"},
    )


# ─── Break glass ──────────────────────────────────────────────────────────────


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
    return await break_glass_service.break_glass_login(
        password=payload.password, ip=ip, user_agent=ua
    )


# ─── Sessions / logout ────────────────────────────────────────────────────────


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
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
    ip, ua = _request_meta(request)
    await session_service.logout(db, token=token, ip=ip, user_agent=ua)


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


# ─── Me / profile ─────────────────────────────────────────────────────────────


@router.get("/me", response_model=MeResponse)
async def me(
    refresh: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    """Current user; pulls unified profile from Authentik when linked + API configured."""
    return await profile_service.get_me(
        db,
        username=current_user.username,
        full_name=getattr(current_user, "full_name", None),
        is_break_glass=getattr(current_user, "is_break_glass", False),
        refresh=(refresh == 1),
    )


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
    return await profile_service.update_my_profile(
        db,
        username=current_user.username,
        is_break_glass=getattr(current_user, "is_break_glass", False),
        payload=payload,
    )


@router.patch("/me/avatar", response_model=ProfileUpdateResponse)
async def update_my_avatar(
    payload: AvatarSeedUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileUpdateResponse:
    """Установить или сбросить avatar_seed. При SSO — пишет в Authentik attributes."""
    return await profile_service.update_my_avatar(
        db,
        username=current_user.username,
        is_break_glass=getattr(current_user, "is_break_glass", False),
        avatar_seed=payload.avatar_seed,
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
    return await session_service.list_my_login_events(db, user_id=current_user.id)
