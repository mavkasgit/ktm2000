from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.config import settings
from app.core.security import TokenError, decode_access_token, verify_password
from app.models.user import User
from app.models.user_session import UserSession
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    ProfileUpdateRequest,
    ProfileUpdateResponse,
    TokenResponse,
)
from app.schemas.oidc_auth import (
    OidcCallbackRequest,
    OidcConfigResponse,
    OidcLogoutUrlResponse,
)
from app.services.oidc_auth_service import OidcAuthService
from app.services.session_service import issue_app_token, revoke_session
from app.services.unified_profile_service import (
    AuthentikProfileError,
    apply_profile_to_user,
    profile_sync_enabled,
    push_profile_by_sub,
    sync_local_from_idp,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# ─── OIDC / Authentik bridge ──────────────────────────────────────────────────


@router.get("/oidc/config", response_model=OidcConfigResponse)
async def oidc_config() -> OidcConfigResponse:
    """
    Public OIDC client config for FE (authorize URL + PKCE params).
    When disabled: ``enabled=false`` and null fields (password/OTP login unchanged).
    """
    return OidcConfigResponse(**OidcAuthService.public_config())


@router.post("/oidc/callback", response_model=TokenResponse)
async def oidc_callback(
    payload: OidcCallbackRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Exchange authorization code (+ PKCE verifier), validate id_token via JWKS,
    link local User (authentik_sub → username/email → JIT), issue app JWT + sid.
    """
    service = OidcAuthService(db)
    result = await service.handle_callback(
        code=payload.code,
        code_verifier=payload.code_verifier,
        redirect_uri=payload.redirect_uri,
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


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    user = await db.scalar(
        select(User).where(
            or_(User.username == payload.username, User.email == payload.username)
        )
    )
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is disabled")

    token = await issue_app_token(db, user=user, login_method="password")
    return TokenResponse(access_token=token)


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
        await revoke_session(db, session_id)


@router.get("/me", response_model=MeResponse)
async def me(
    refresh: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    """Current user; pulls unified profile from Authentik when linked + API configured."""
    user = current_user
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
    """Update display name / email / locale / theme / avatar. SoT = Authentik when linked."""
    user = current_user
    want_name = payload.full_name.strip() if payload.full_name else None
    want_email = str(payload.email).strip() if payload.email is not None else None
    want_locale = payload.locale
    want_theme = payload.theme

    if payload.clear_avatar:
        avatar_arg: object = None
    elif payload.avatar_seed is not None:
        avatar_arg = payload.avatar_seed
    else:
        avatar_arg = ...

    if user.authentik_sub and profile_sync_enabled():
        try:
            remote = await push_profile_by_sub(
                user.authentik_sub,
                full_name=want_name,
                avatar_seed=avatar_arg,
                email=want_email,
                locale=want_locale,
                theme=want_theme,
            )
            if want_name:
                user.full_name = remote.full_name or want_name
            if avatar_arg is not ...:
                user.avatar_seed = remote.avatar_seed
            elif remote.full_name:
                user.full_name = remote.full_name
            if want_email is not None:
                user.email = remote.email or want_email
            if want_locale is not None:
                user.locale = remote.locale or want_locale
            if want_theme is not None:
                user.theme = remote.theme or want_theme
            user.profile_synced_at = datetime.now(timezone.utc)
        except AuthentikProfileError as exc:
            raise HTTPException(
                status_code=exc.status_code or 502,
                detail=exc.message,
            ) from exc
    else:
        if want_name:
            user.full_name = want_name
        if payload.clear_avatar:
            user.avatar_seed = None
        elif payload.avatar_seed is not None:
            user.avatar_seed = payload.avatar_seed
        if want_email is not None:
            user.email = want_email
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
        email=user.email,
        locale=user.locale,
        theme=user.theme,
    )


@router.patch("/me/avatar", response_model=ProfileUpdateResponse)
async def update_my_avatar(
    payload: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileUpdateResponse:
    """Shortcut: set/clear avatar_seed (null seed or clear_avatar → reset)."""
    clear = bool(payload.clear_avatar or payload.avatar_seed is None)
    return await update_my_profile(
        ProfileUpdateRequest(
            avatar_seed=None if clear else payload.avatar_seed,
            clear_avatar=clear,
        ),
        current_user,
        db,
    )
