"""OIDC / Authentik bridge: token exchange, id_token JWKS verify, user link → app JWT.

Flow (public SPA + PKCE):
  FE authorize → Authentik → FE /auth/callback → POST /api/auth/oidc/callback
  → exchange code → validate id_token → resolve User → issue_app_token (JWT+sid)

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
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

import httpx
from fastapi import HTTPException, status
from jose import JWTError, jwt
from jose.backends import RSAKey
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User, UserRole
from app.services.session_service import issue_app_token

logger = logging.getLogger(__name__)

# In-process JWKS cache: {url: (fetched_at_monotonic, jwks_dict)}
_JWKS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_JWKS_TTL_SECONDS = 3600

_VALID_ROLES = frozenset(r.value for r in UserRole)


@dataclass(frozen=True)
class OidcClaims:
    """Normalized claims extracted from validated id_token."""

    sub: str
    preferred_username: str | None
    email: str | None
    name: str | None
    groups: tuple[str, ...] = ()


class OidcAuthService:
    """Business logic for OIDC bridge (layer: service)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── config helpers ───────────────────────────────────────────────────

    @staticmethod
    def is_enabled() -> bool:
        return bool(settings.AUTH_OIDC_ENABLED)

    @staticmethod
    def _issuer() -> str:
        issuer = (settings.AUTH_OIDC_ISSUER or "").strip()
        if not issuer:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OIDC issuer not configured",
            )
        return issuer if issuer.endswith("/") else issuer + "/"

    @classmethod
    def _alt_issuer_hosts(cls) -> list[str]:
        """Hostnames that may appear in id_token.iss (LAN IP, localhost, docker)."""
        hosts: list[str] = []
        seen: set[str] = set()

        def add_host(h: str | None) -> None:
            if not h:
                return
            h = h.strip().lower().split("%")[0]
            if not h or h in seen:
                return
            seen.add(h)
            hosts.append(h)

        for fixed in ("localhost", "127.0.0.1", "host.docker.internal"):
            add_host(fixed)

        raw_issuer = (settings.AUTH_OIDC_ISSUER or "").strip()
        if raw_issuer:
            parsed = urlparse(raw_issuer if "://" in raw_issuer else f"http://{raw_issuer}")
            add_host(parsed.hostname)

        aliases = (settings.AUTH_OIDC_ISSUER_ALIASES or "").strip()
        for part in aliases.split(","):
            part = part.strip()
            if not part:
                continue
            if "://" in part:
                add_host(urlparse(part).hostname)
            else:
                # host or host:port
                add_host(part.split("/")[0].split(":")[0])

        return hosts

    @classmethod
    def _issuer_candidates(cls) -> list[str]:
        """Accept iss from browser host, LAN IP, Docker host-gateway, and aliases.

        Authentik sets id_token ``iss`` from the authorize request Host.
        SPA may open IdP as localhost:9000 or http://<LAN-IP>:9000 — both valid.
        """
        primary = cls._issuer()
        bare = primary.rstrip("/")
        out: list[str] = []
        seen: set[str] = set()

        def add(value: str) -> None:
            if value and value not in seen:
                seen.add(value)
                out.append(value)

        add(primary)
        add(bare)

        for base in (primary, bare):
            parsed = urlparse(base if "://" in base else f"http://{base}")
            if not parsed.hostname:
                continue
            path = parsed.path or ""
            for host in cls._alt_issuer_hosts():
                port = parsed.port
                netloc = f"{host}:{port}" if port else host
                rebuilt = urlunparse(
                    (parsed.scheme or "http", netloc, path, "", "", "")
                )
                add(rebuilt)
                add(rebuilt.rstrip("/"))
                if not rebuilt.endswith("/"):
                    add(rebuilt + "/")
        return out

    @classmethod
    def resolve_authorization_url(cls) -> str:
        if settings.AUTH_OIDC_AUTHORIZATION_URL:
            return settings.AUTH_OIDC_AUTHORIZATION_URL.rstrip("/")
        issuer = cls._issuer()
        # issuer = …/application/o/ktm2000/ → …/application/o/authorize/
        base = issuer.rsplit("/", 2)[0] + "/"
        return urljoin(base, "authorize/")

    @classmethod
    def resolve_token_url(cls) -> str:
        if settings.AUTH_OIDC_TOKEN_URL:
            return settings.AUTH_OIDC_TOKEN_URL
        issuer = cls._issuer()
        base = issuer.rsplit("/", 2)[0] + "/"
        return urljoin(base, "token/")

    @classmethod
    def resolve_jwks_url(cls) -> str:
        if settings.AUTH_OIDC_JWKS_URL:
            return settings.AUTH_OIDC_JWKS_URL
        return urljoin(cls._issuer(), "jwks/")

    @classmethod
    def resolve_end_session_url(cls) -> str:
        if settings.AUTH_OIDC_END_SESSION_URL:
            return settings.AUTH_OIDC_END_SESSION_URL
        return urljoin(cls._issuer(), "end-session/")

    @classmethod
    def public_config(cls) -> dict[str, Any]:
        """Payload for GET /auth/oidc/config (no secrets)."""
        if not cls.is_enabled():
            return {
                "enabled": False,
                "authorization_url": None,
                "client_id": None,
                "redirect_uri": None,
                "scopes": None,
                "issuer": None,
                "token_url": None,
            }
        try:
            auth_url = cls.resolve_authorization_url()
            token_url = cls.resolve_token_url()
            issuer = cls._issuer()
        except HTTPException:
            return {
                "enabled": True,
                "authorization_url": None,
                "client_id": settings.AUTH_OIDC_CLIENT_ID,
                "redirect_uri": settings.AUTH_OIDC_REDIRECT_URI,
                "scopes": settings.AUTH_OIDC_SCOPES,
                "issuer": settings.AUTH_OIDC_ISSUER,
                "token_url": settings.AUTH_OIDC_TOKEN_URL,
            }
        return {
            "enabled": True,
            "authorization_url": auth_url,
            "client_id": settings.AUTH_OIDC_CLIENT_ID,
            "redirect_uri": settings.AUTH_OIDC_REDIRECT_URI,
            "scopes": settings.AUTH_OIDC_SCOPES,
            "issuer": issuer.rstrip("/"),
            "token_url": token_url,
        }

    @classmethod
    def logout_url(
        cls,
        *,
        id_token_hint: str | None = None,
        post_logout_redirect_uri: str | None = None,
    ) -> str | None:
        if not cls.is_enabled():
            return None
        try:
            base = cls.resolve_end_session_url()
        except HTTPException:
            return None
        params: dict[str, str] = {}
        if id_token_hint:
            params["id_token_hint"] = id_token_hint
        if post_logout_redirect_uri:
            params["post_logout_redirect_uri"] = post_logout_redirect_uri
        elif settings.AUTH_OIDC_REDIRECT_URI:
            redirect = settings.AUTH_OIDC_REDIRECT_URI
            if "/auth/callback" in redirect:
                params["post_logout_redirect_uri"] = redirect.replace(
                    "/auth/callback", "/login"
                )
        if params:
            sep = "&" if "?" in base else "?"
            return f"{base}{sep}{urlencode(params)}"
        return base

    # ─── HTTP: token + JWKS ───────────────────────────────────────────────

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        """POST token_endpoint with authorization_code + PKCE."""
        token_url = self.resolve_token_url()
        client_id = settings.AUTH_OIDC_CLIENT_ID
        if not client_id:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OIDC client_id not configured",
            )
        data: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": code_verifier,
        }
        secret = (settings.AUTH_OIDC_CLIENT_SECRET or "").strip()
        if secret:
            data["client_secret"] = secret

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    token_url,
                    data=data,
                    headers={"Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            logger.warning("OIDC token exchange network error: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="OIDC token endpoint unreachable",
            ) from exc

        if resp.status_code >= 400:
            logger.warning(
                "OIDC token exchange failed status=%s body=%s",
                resp.status_code,
                resp.text[:500],
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_oidc_code",
            )

        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="OIDC token response invalid",
            ) from exc

        if "id_token" not in body:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_oidc_token_response",
            )
        return body

    async def fetch_jwks(self) -> dict[str, Any]:
        """Fetch JWKS with simple TTL cache."""
        url = self.resolve_jwks_url()
        now = time.monotonic()
        cached = _JWKS_CACHE.get(url)
        if cached and (now - cached[0]) < _JWKS_TTL_SECONDS:
            return cached[1]

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers={"Accept": "application/json"})
                resp.raise_for_status()
                jwks = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("OIDC JWKS fetch failed: %s", exc)
            if cached:
                return cached[1]
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="OIDC JWKS unavailable",
            ) from exc

        _JWKS_CACHE[url] = (now, jwks)
        return jwks

    @staticmethod
    def clear_jwks_cache() -> None:
        """Test helper / ops."""
        _JWKS_CACHE.clear()

    async def validate_id_token(self, id_token: str) -> OidcClaims:
        """Verify signature (JWKS), iss, aud, exp; return normalized claims."""
        client_id = settings.AUTH_OIDC_CLIENT_ID
        if not client_id:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OIDC client_id not configured",
            )

        try:
            header = jwt.get_unverified_header(id_token)
        except JWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_id_token",
            ) from exc

        kid = header.get("kid")
        alg = header.get("alg", "RS256")
        jwks = await self.fetch_jwks()
        keys = jwks.get("keys") or []
        matching = None
        for key in keys:
            if kid and key.get("kid") == kid:
                matching = key
                break
            if not kid and key.get("kty") == "RSA":
                matching = key
                break
        if matching is None and keys:
            matching = keys[0]
        if matching is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_id_token_key",
            )

        claims: dict[str, Any] | None = None
        last_err: Exception | None = None
        try:
            rsa_key = RSAKey(matching, algorithm=alg)
        except Exception as exc:  # noqa: BLE001
            logger.info("OIDC JWKS key load failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_id_token_key",
            ) from exc

        for issuer_candidate in self._issuer_candidates():
            try:
                claims = jwt.decode(
                    id_token,
                    rsa_key,
                    algorithms=[alg],
                    audience=client_id,
                    issuer=issuer_candidate,
                    options={
                        "verify_at_hash": False,
                        "require_exp": True,
                        "require_iat": False,
                        "require_nbf": False,
                    },
                )
                break
            except JWTError as exc:
                last_err = exc
                continue

        if claims is None:
            logger.info("OIDC id_token validation failed: %s", last_err)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_id_token",
            )

        sub = claims.get("sub")
        if not sub or not isinstance(sub, str):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_id_token_sub",
            )

        raw_groups = claims.get("groups") or claims.get("groups_list") or []
        groups: tuple[str, ...] = ()
        if isinstance(raw_groups, (list, tuple)):
            groups = tuple(str(g) for g in raw_groups if g)

        return OidcClaims(
            sub=sub,
            preferred_username=claims.get("preferred_username") or claims.get("nickname"),
            email=claims.get("email"),
            name=claims.get("name"),
            groups=groups,
        )

    # ─── user resolve / link ──────────────────────────────────────────────

    async def _get_by_authentik_sub(self, authentik_sub: str) -> User | None:
        return await self.db.scalar(
            select(User).where(User.authentik_sub == authentik_sub)
        )

    async def _link_authentik_sub(self, user: User, authentik_sub: str) -> User:
        """Persist Authentik subject on local user when empty (first successful link)."""
        if user.authentik_sub:
            return user
        user.authentik_sub = authentik_sub
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def resolve_or_provision_user(self, claims: OidcClaims) -> User:
        """
        Link order (canon R2):
        1. by authentik_sub == id_token.sub
        2. by preferred_username / email / email local-part → write sub if empty
        3. if AUTH_OIDC_ALLOW_JIT: create with authentik_sub
        4. else 403 oidc_user_not_linked
        """
        user = await self._get_by_authentik_sub(claims.sub)
        if user is not None:
            await self._maybe_sync_role(user, claims)
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
                await self._maybe_sync_role(found, claims)
                return found

        if not settings.AUTH_OIDC_ALLOW_JIT:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="oidc_user_not_linked",
            )

        username = await self._pick_username(candidates, claims.sub)
        role = self._role_from_claims(claims)
        full_name = (claims.name or username).strip()[:255] or username
        email = (claims.email or None)
        if email:
            email = email.strip()[:255] or None

        user = User(
            username=username[:255],
            email=email,
            password_hash="",  # SSO-only; password login will fail verify
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
                password_hash="",
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
        """Overwrite local MES role from IdP groups only when SYNC flag is true."""
        if not settings.AUTH_OIDC_SYNC_ROLE_FROM_IDP:
            return
        mapped = self._role_from_groups(claims)
        if mapped is None or user.role == mapped:
            return
        user.role = mapped
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)


    # ─── full callback ────────────────────────────────────────────────────

    async def handle_callback(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str | None = None,
    ) -> dict[str, Any]:
        """
        Exchange code → validate id_token → resolve user → issue app JWT.
        Returns TokenResponse-compatible dict (access_token, token_type).
        """
        if not self.is_enabled():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="OIDC login disabled",
            )

        redir = (redirect_uri or settings.AUTH_OIDC_REDIRECT_URI or "").strip()
        if not redir:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OIDC redirect_uri not configured",
            )

        token_body = await self.exchange_code(
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redir,
        )
        id_token = token_body["id_token"]
        claims = await self.validate_id_token(id_token)
        user = await self.resolve_or_provision_user(claims)

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is disabled",
            )

        token = await issue_app_token(self.db, user=user, login_method="oidc")
        return {
            "access_token": token,
            "token_type": "bearer",
            "username": user.username,
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "full_name": user.full_name or user.username,
        }
