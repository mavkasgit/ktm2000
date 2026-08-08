"""OIDC / Authentik bridge — KTM host adapter over the shared OIDC core.

Flow (public SPA + PKCE):
  FE authorize → Authentik → FE /auth/callback → POST /api/auth/oidc/callback
  → core.exchange_code → core.validate_id_token → resolve User → issue_app_token

The protocol machinery (issuer candidates, JWKS + TTL cache, exchange_code,
validate_id_token, validate_logout_token, logout_url, public_config) lives in
the must-match module app/services/oidc_core.py. This file wires the KTM
domain: role-mapping (ktm_role claim / groups), user-provisioning, session
issuance via the shared session-core, and the RU error dictionary.

Link order (canon R2):
  1. users.authentik_sub == id_token.sub
  2. secondary: preferred_username / email / email local-part → write sub if empty
  3. JIT if AUTH_OIDC_ALLOW_JIT else 403 oidc_user_not_linked

Roles (canon R3/R4): app DB is SoT for MES roles; soft group map only when
AUTH_OIDC_SYNC_ROLE_FROM_IDP=true (default false). No collapse to admin/viewer IdP.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy import or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User, UserRole
from app.services import session_service
from app.services.oidc_core import (
    LogoutClaims,
    OidcClaims,
    OidcCore,
    OidcCoreConfig,
    OidcHooks,
)
from app.services.session_service import (
    cleanup_logout_jti,
    is_logout_jti_used,
    mark_logout_jti_used,
    record_login_event,
    revoke_all,
    revoke_by_oidc_sid,
)

logger = logging.getLogger(__name__)

_VALID_ROLES = frozenset(r.value for r in UserRole)


def _ktm_role_from_claims(claims: OidcClaims) -> str | None:
    """Extract the KTM-specific role claim from the raw validated id_token claims."""
    raw = claims.raw.get("ktm_role")
    return str(raw).strip().lower() if raw else None


class OidcAuthService:
    """Business logic for the OIDC bridge — KTM host adapter (layer: service)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._oidc_core = OidcCore(self._core_config(), self._core_hooks())

    # ─── shared core wiring ───────────────────────────────────────────────

    @classmethod
    def _core_config(cls) -> OidcCoreConfig:
        lan: str | None = None
        try:
            from app.core.host_net import detect_lan_ip, env_lan_ip

            lan = env_lan_ip() or detect_lan_ip()
        except Exception:  # noqa: BLE001
            lan = None

        def resolve_auto_origin() -> str | None:
            try:
                from app.core.host_net import resolve_authentik_origin

                return resolve_authentik_origin(None)
            except Exception:  # noqa: BLE001
                return None

        return OidcCoreConfig(
            enabled=bool(settings.AUTH_OIDC_ENABLED),
            issuer=settings.AUTH_OIDC_ISSUER,
            client_id=settings.AUTH_OIDC_CLIENT_ID,
            client_secret=settings.AUTH_OIDC_CLIENT_SECRET,
            redirect_uri=settings.AUTH_OIDC_REDIRECT_URI,
            scopes=settings.AUTH_OIDC_SCOPES,
            issuer_aliases=settings.AUTH_OIDC_ISSUER_ALIASES,
            authorization_url=settings.AUTH_OIDC_AUTHORIZATION_URL,
            token_url=settings.AUTH_OIDC_TOKEN_URL,
            jwks_url=settings.AUTH_OIDC_JWKS_URL,
            end_session_url=settings.AUTH_OIDC_END_SESSION_URL,
            auto_issuer_client_id="ktm2000",
            resolve_auto_origin=resolve_auto_origin,
            extra_alt_hosts=(lan,) if lan else (),
            login_hint_enabled=bool(settings.AUTH_OIDC_LOGIN_HINT_ENABLED),
            sso_only=bool(settings.AUTH_SSO_ONLY),
        )

    def _core_hooks(self) -> OidcHooks:
        return OidcHooks(
            resolve_or_provision=self.resolve_or_provision_user,
            issue_token=self._issue_token,
            record_failed_login=self._record_failed_login,
        )

    @classmethod
    def _core(cls) -> OidcCore:
        return OidcCore(cls._core_config())

    # ─── config-only delegates (no db) ────────────────────────────────────

    @classmethod
    def is_enabled(cls) -> bool:
        return cls._core().is_enabled()

    @classmethod
    def resolve_authorization_url(cls) -> str:
        return cls._core().resolve_authorization_url()

    @classmethod
    def resolve_token_url(cls) -> str:
        return cls._core().resolve_token_url()

    @classmethod
    def resolve_jwks_url(cls) -> str:
        return cls._core().resolve_jwks_url()

    @classmethod
    def resolve_end_session_url(cls) -> str:
        return cls._core().resolve_end_session_url()

    @classmethod
    def public_config(cls) -> dict[str, Any]:
        return cls._core().public_config()

    @classmethod
    def logout_url(
        cls,
        *,
        id_token_hint: str | None = None,
        post_logout_redirect_uri: str | None = None,
    ) -> str | None:
        return cls._core().logout_url(
            id_token_hint=id_token_hint,
            post_logout_redirect_uri=post_logout_redirect_uri,
        )

    @classmethod
    def _issuer_candidates(cls) -> list[str]:
        return cls._core()._issuer_candidates()

    @classmethod
    def clear_jwks_cache(cls) -> None:
        OidcCore.clear_jwks_cache()

    # ─── instance delegates ───────────────────────────────────────────────

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        return await self._oidc_core.exchange_code(
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )

    async def fetch_jwks(self) -> dict[str, Any]:
        return await self._oidc_core.fetch_jwks()

    async def validate_id_token(self, id_token: str) -> OidcClaims:
        return await self._oidc_core.validate_id_token(id_token)

    async def validate_logout_token(self, logout_token: str) -> LogoutClaims:
        return await self._oidc_core.validate_logout_token(logout_token)

    # ─── hooks (host domain, wired into the shared core) ──────────────────

    async def _issue_token(
        self,
        user: User,
        claims: OidcClaims,
        *,
        ip: str | None,
        user_agent: str | None,
    ) -> str:
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is disabled",
            )
        return await session_service.issue_app_token(
            self.db,
            user=user,
            login_method="oidc",
            ip=ip,
            user_agent=user_agent,
            oidc_sid=claims.sid,
        )

    async def _record_failed_login(
        self,
        *,
        reason: str,
        username_attempted: str | None,
        ip: str | None,
        user_agent: str | None,
    ) -> None:
        try:
            await record_login_event(
                self.db,
                event_type="login_failure",
                success=False,
                user_id=None,
                username_attempted=username_attempted,
                ip_address=ip,
                user_agent=user_agent,
                details={"reason": reason, "method": "oidc"},
            )
        except Exception:  # noqa: BLE001 — audit must never break auth flow
            logger.warning("OIDC failed-login audit record failed", exc_info=True)

    # ─── user resolve / link ──────────────────────────────────────────────

    async def _get_by_authentik_sub(self, authentik_sub: str) -> User | None:
        return await self.db.scalar(
            select(User).where(User.authentik_sub == authentik_sub)
        )

    async def _link_authentik_sub(self, user: User, authentik_sub: str) -> User:
        """Persist/refresh Authentik subject on local user (always overwrite — IdP-authoritative).

        Authentik re-creation rotates user uuids; keeping the stale sub would silently
        break back-channel SLO (revoke lookup misses). Column is non-unique, so overwrite
        is safe — mirrors HRMS behaviour.
        """
        user.authentik_sub = authentik_sub
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def resolve_or_provision_user(self, claims: OidcClaims) -> User:
        """
        Link order (canon R2):
        1. by authentik_sub == id_token.sub
        2. by preferred_username / email / email local-part → write/refresh sub (always)
        3. if AUTH_OIDC_ALLOW_JIT: create with authentik_sub
        4. else 403 oidc_user_not_linked
        """
        user = await self._get_by_authentik_sub(claims.sub)
        if user is not None:
            await self._apply_role_sync(user, claims)
            return user

        candidates: list[str] = []
        if claims.preferred_username:
            candidates.append(claims.preferred_username.strip())
        if claims.email:
            email = claims.email.strip()
            if email and email not in candidates:
                candidates.append(email)
            local = email.split("@", 1)[0] if email else ""
            if local and local not in candidates:
                candidates.append(local)

        for name in candidates:
            if not name:
                continue
            key = name[:255]
            found = await self.db.scalar(
                select(User).where(
                    or_(
                        User.username == key,
                        User.email == key,
                        # Case-insensitive match (IdP usernames vary)
                        User.username.ilike(key),
                        User.email.ilike(key),
                    )
                )
            )
            if found is not None:
                await self._link_authentik_sub(found, claims.sub)
                await self._apply_role_sync(found, claims)
                return found

        if not settings.AUTH_OIDC_ALLOW_JIT:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="oidc_user_not_linked",
            )

        username = await self._pick_username(candidates, claims.sub)
        # When SYNC enabled: ktm_role claim is mandatory for JIT (fail-closed)
        if settings.AUTH_OIDC_SYNC_ROLE_FROM_IDP:
            ktm_role = _ktm_role_from_claims(claims)
            if ktm_role not in _VALID_ROLES:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No KTM role assigned. Contact admin.",
                )
            role = UserRole(ktm_role)
        else:
            role = self._role_from_claims(claims)
        full_name = (claims.name or username).strip()[:255] or username
        email = (claims.email or None)
        if email:
            email = email.strip()[:255] or None

        user = User(
            username=username[:255],
            email=email,
            full_name=full_name,
            role=role,
            is_active=True,
            authentik_sub=claims.sub,
        )
        self.db.add(user)
        try:
            await self.db.commit()
            await self.db.refresh(user)
            return user
        except Exception as exc:  # noqa: BLE001 — catch IntegrityError without hard import path issues
            await self.db.rollback()
            logger.warning("OIDC JIT insert failed (%s); re-lookup + seq resync", exc)
            # Sequence often lags after seed/manual ids → resync and retry once
            try:
                await self.db.execute(
                    text(
                        "SELECT setval("
                        "pg_get_serial_sequence('users', 'id'), "
                        "COALESCE((SELECT MAX(id) FROM users), 1))"
                    )
                )
                await self.db.commit()
            except Exception as seq_exc:  # noqa: BLE001
                logger.warning("users_id_seq resync failed: %s", seq_exc)
                await self.db.rollback()

            # Re-try by sub (race) then secondary keys
            by_sub = await self._get_by_authentik_sub(claims.sub)
            if by_sub is not None:
                return by_sub

            for name in (username, email or "", *candidates):
                if not name:
                    continue
                key = name[:255]
                found = await self.db.scalar(
                    select(User).where(
                        or_(User.username.ilike(key), User.email.ilike(key))
                    )
                )
                if found is not None:
                    await self._link_authentik_sub(found, claims.sub)
                    return found

            # Retry insert after sequence bump
            user2 = User(
                username=username[:255],
                email=email,
                full_name=full_name,
                role=role,
                is_active=True,
                authentik_sub=claims.sub,
            )
            self.db.add(user2)
            try:
                await self.db.commit()
                await self.db.refresh(user2)
                return user2
            except Exception as retry_exc:  # noqa: BLE001
                await self.db.rollback()
                logger.exception("OIDC JIT retry failed: %s", retry_exc)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="oidc_user_provision_failed",
                ) from retry_exc

    async def _pick_username(self, candidates: list[str], sub: str) -> str:
        for name in candidates:
            candidate = name.strip()[:255]
            if not candidate:
                continue
            existing = await self.db.scalar(select(User).where(User.username == candidate))
            if existing is None:
                return candidate
        safe = "".join(c for c in sub if c.isalnum())[:24] or "user"
        base = f"oidc_{safe}"[:255]
        existing = await self.db.scalar(select(User).where(User.username == base))
        if existing is None:
            return base
        return f"oidc_{safe}_{int(time.time()) % 100000}"[:255]

    def _default_role(self) -> UserRole:
        default = (settings.AUTH_OIDC_DEFAULT_ROLE or "viewer").strip()
        if default in _VALID_ROLES:
            return UserRole(default)
        return UserRole.viewer

    def _role_from_groups(self, claims: OidcClaims) -> UserRole | None:
        """Soft map IdP groups → MES role; None if no match (do not invent)."""
        group_set = {g.lower() for g in claims.groups}
        for role in UserRole:
            if role.value in group_set or f"ktm-{role.value}" in group_set:
                return role
            if f"ktm2000-{role.value}" in group_set:
                return role
        if "admin" in group_set or "ktm-admin" in group_set or "ktm2000-admin" in group_set:
            return UserRole.admin
        return None

    def _role_from_claims(self, claims: OidcClaims) -> UserRole:
        """JIT role: group map only when SYNC on; else AUTH_OIDC_DEFAULT_ROLE."""
        if settings.AUTH_OIDC_SYNC_ROLE_FROM_IDP:
            mapped = self._role_from_groups(claims)
            if mapped is not None:
                return mapped
        return self._default_role()

    async def _maybe_sync_role(self, user: User, claims: OidcClaims) -> None:
        """Overwrite local MES role from IdP groups only when SYNC flag is true (legacy group-based)."""
        if not settings.AUTH_OIDC_SYNC_ROLE_FROM_IDP:
            return
        mapped = self._role_from_groups(claims)
        if mapped is None or user.role == mapped:
            return
        user.role = mapped
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

    async def _sync_role_from_claim(self, user: User, claims: OidcClaims) -> None:
        """JIT overwrite role from ktm_role claim. Fail-closed when claim absent/invalid."""
        ktm_role = _ktm_role_from_claims(claims)
        if ktm_role in _VALID_ROLES:
            if user.role != UserRole(ktm_role):
                user.role = UserRole(ktm_role)
            user.is_active = True
            self.db.add(user)
            await self.db.commit()
            await self.db.refresh(user)
        elif ktm_role == "conflict":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Role conflict in IdP. Contact admin.",
            )
        else:
            # absent / no_access / garbage -> fail-closed
            user.is_active = False
            self.db.add(user)
            await self.db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No KTM role assigned. Contact admin.",
            )

    async def _apply_role_sync(self, user: User, claims: OidcClaims) -> None:
        """Dispatch role sync: claim-based (fail-closed) when SYNC on, else legacy group-based."""
        if settings.AUTH_OIDC_SYNC_ROLE_FROM_IDP:
            await self._sync_role_from_claim(user, claims)
        else:
            await self._maybe_sync_role(user, claims)

    # ─── full callback ────────────────────────────────────────────────────

    async def handle_callback(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        """
        Exchange code → validate id_token → resolve user → issue app JWT.
        Returns TokenResponse-compatible dict (access_token, token_type).
        """
        result = await self._oidc_core.handle_callback(
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            ip=ip,
            user_agent=user_agent,
        )
        user = result["user"]
        return {
            "access_token": result["access_token"],
            "token_type": result["token_type"],
            "username": user.username,
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "full_name": user.full_name or user.username,
            # For Authentik RP-initiated logout (id_token_hint + post_logout_redirect_uri)
            "id_token": result["id_token"],
        }

    # ─── back-channel logout (thin-route boundary) ────────────────────────

    async def handle_backchannel_logout(self, logout_token: str) -> dict[str, Any]:
        """OIDC Back-Channel Logout orchestration.

        Phase-1 SLO:
          - replay protection via jti (one-time use);
          - sid present → revoke only sessions with that IdP sid;
          - sid absent (e.g. user deactivation) → revoke all sessions by sub;
          - audit: session_revoke event with source="authentik_backchannel";
          - jti consumed even for unknown sub (no enumeration).

        Invalid token → HTTPException 400 invalid_logout_token;
        replayed jti → HTTPException 400 replay_logout_token.
        Returns {"status": "ok", "revoked": N}.
        """
        try:
            claims = await self.validate_logout_token(str(logout_token).strip())
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_logout_token",
            ) from exc

        # Replay protection: jti is one-time use (OIDC Back-Channel Logout 1.0)
        if claims.jti and await is_logout_jti_used(self.db, claims.jti):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="replay_logout_token",
            )

        user = await self.db.scalar(select(User).where(User.authentik_sub == claims.sub))
        revoked = 0
        if user is not None:
            if claims.sid:
                revoked_ids = await revoke_by_oidc_sid(
                    self.db,
                    user_id=user.id,
                    oidc_sid=claims.sid,
                    reason="backchannel_logout",
                )
                revoked = len(revoked_ids)
            else:
                revoked = await revoke_all(
                    self.db,
                    user_id=user.id,
                    reason="backchannel_logout",
                )
            await record_login_event(
                self.db,
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
                await mark_logout_jti_used(self.db, claims.jti, expires_at=exp_dt)
            except IntegrityError as exc:
                # Race on duplicate delivery: jti already recorded -> replay
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="replay_logout_token",
                ) from exc
            await cleanup_logout_jti(self.db)

        return {"status": "ok", "revoked": revoked}
