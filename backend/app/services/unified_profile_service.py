"""
Unified human profile — Authentik SoT, app DB cache.

Fields:
  full_name   → user.name
  email       → user.email
  avatar_seed → attributes.profile_avatar_seed
  locale      → attributes.profile_locale
  theme       → attributes.profile_theme

Link: users.authentik_sub == Authentik user.uuid
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.core.host_net import resolve_authentik_origin

logger = logging.getLogger(__name__)

ATTR_AVATAR_SEED = "profile_avatar_seed"
ATTR_LOCALE = "profile_locale"
ATTR_THEME = "profile_theme"

ALLOWED_LOCALES = frozenset({"ru", "en"})
ALLOWED_THEMES = frozenset({"system", "light", "dark"})


@dataclass
class UnifiedProfile:
    full_name: str | None
    avatar_seed: str | None
    email: str | None = None
    locale: str | None = None
    theme: str | None = None
    authentik_pk: int | None = None
    source: str = "local"


class AuthentikProfileError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _resolved_api_origin() -> str | None:
    return resolve_authentik_origin(
        settings.AUTHENTIK_API_URL,
        fallback_issuer=settings.AUTH_OIDC_ISSUER,
    )


def profile_sync_enabled() -> bool:
    if not settings.AUTH_OIDC_ENABLED:
        return False
    url = _resolved_api_origin()
    token = (settings.AUTHENTIK_API_TOKEN or "").strip()
    return bool(url and token)


def _api_base() -> str:
    raw = _resolved_api_origin()
    if not raw:
        raise AuthentikProfileError(
            "AUTHENTIK_API_URL is not configured and LAN IP could not be detected",
            status_code=503,
        )
    raw = raw.rstrip("/")
    if raw.endswith("/api/v3"):
        return raw
    return f"{raw}/api/v3"


def _headers() -> dict[str, str]:
    token = (settings.AUTHENTIK_API_TOKEN or "").strip()
    if not token:
        raise AuthentikProfileError("AUTHENTIK_API_TOKEN is not configured", status_code=503)
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


async def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> Any:
    base = _api_base()
    url = f"{base}{path}" if path.startswith("/") else f"{base}/{path}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.request(
                method,
                url,
                headers=_headers(),
                params=params,
                json=json_body,
            )
    except httpx.HTTPError as exc:
        raise AuthentikProfileError(f"Authentik unreachable: {exc}", status_code=502) from exc

    if resp.status_code >= 400:
        detail = resp.text[:500] if resp.text else resp.reason_phrase
        # Pass through 4xx (email uniqueness etc.) so API can surface clear errors
        code = resp.status_code if 400 <= resp.status_code < 500 else 502
        raise AuthentikProfileError(
            f"Authentik API error {resp.status_code}: {detail}",
            status_code=code,
        )
    if resp.status_code == 204 or not resp.content:
        return None
    try:
        return resp.json()
    except ValueError as exc:
        raise AuthentikProfileError("Invalid JSON from Authentik", status_code=502) from exc


async def _find_user_by_sub(authentik_sub: str) -> dict[str, Any] | None:
    sub = (authentik_sub or "").strip()
    if not sub:
        return None
    data = await _request("GET", "/core/users/", params={"uuid": sub, "page_size": 5})
    results = data.get("results") if isinstance(data, dict) else None
    if results:
        for u in results:
            if str(u.get("uuid") or "") == sub:
                return u
        return results[0]
    data = await _request("GET", "/core/users/", params={"search": sub, "page_size": 20})
    results = data.get("results") if isinstance(data, dict) else None
    if not results:
        return None
    for u in results:
        if str(u.get("uuid") or "") == sub:
            return u
    return None


def _attrs(user: dict[str, Any]) -> dict[str, Any]:
    raw = user.get("attributes")
    return dict(raw) if isinstance(raw, dict) else {}


def _norm_attr_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def profile_from_ak_user(user: dict[str, Any]) -> UnifiedProfile:
    attrs = _attrs(user)
    seed = _norm_attr_str(attrs.get(ATTR_AVATAR_SEED))
    locale = _norm_attr_str(attrs.get(ATTR_LOCALE))
    if locale and locale not in ALLOWED_LOCALES:
        locale = None
    theme = _norm_attr_str(attrs.get(ATTR_THEME))
    if theme and theme not in ALLOWED_THEMES:
        theme = None
    name = user.get("name")
    name_s = str(name).strip() if name else None
    email_raw = user.get("email")
    email_s = str(email_raw).strip() if email_raw else None
    pk = user.get("pk")
    try:
        pk_i = int(pk) if pk is not None else None
    except (TypeError, ValueError):
        pk_i = None
    return UnifiedProfile(
        full_name=name_s,
        avatar_seed=seed,
        email=email_s,
        locale=locale,
        theme=theme,
        authentik_pk=pk_i,
        source="idp",
    )


async def fetch_profile_by_sub(authentik_sub: str) -> UnifiedProfile | None:
    if not profile_sync_enabled():
        return None
    try:
        user = await _find_user_by_sub(authentik_sub)
    except AuthentikProfileError as exc:
        logger.warning("unified profile fetch failed: %s", exc.message)
        return None
    if not user:
        return None
    return profile_from_ak_user(user)


def _set_attr(attrs: dict[str, Any], key: str, value: str | None) -> None:
    if value is None:
        attrs.pop(key, None)
    else:
        attrs[key] = value


async def push_profile_by_sub(
    authentik_sub: str,
    *,
    full_name: str | None = None,
    avatar_seed: str | None | object = ...,
    email: str | None = None,
    locale: str | None = None,
    theme: str | None = None,
) -> UnifiedProfile:
    if not profile_sync_enabled():
        raise AuthentikProfileError(
            "IdP profile sync is not configured (AUTHENTIK_API_*)",
            status_code=503,
        )
    user = await _find_user_by_sub(authentik_sub)
    if not user:
        raise AuthentikProfileError(
            f"Authentik user not found for sub={authentik_sub!r}",
            status_code=404,
        )
    pk = user.get("pk")
    if pk is None:
        raise AuthentikProfileError("Authentik user missing pk", status_code=502)

    body: dict[str, Any] = {}
    if full_name is not None:
        body["name"] = full_name.strip()
    if email is not None:
        body["email"] = email.strip()

    attrs: dict[str, Any] | None = None

    def ensure_attrs() -> dict[str, Any]:
        nonlocal attrs
        if attrs is None:
            attrs = _attrs(user)
        return attrs

    if avatar_seed is not ...:
        a = ensure_attrs()
        if avatar_seed is None:
            a.pop(ATTR_AVATAR_SEED, None)
        else:
            seed_s = str(avatar_seed).strip()
            if not seed_s:
                a.pop(ATTR_AVATAR_SEED, None)
            else:
                if len(seed_s) > 64:
                    raise AuthentikProfileError("avatar_seed max length 64", status_code=400)
                a[ATTR_AVATAR_SEED] = seed_s

    if locale is not None:
        loc = locale.strip()
        if loc not in ALLOWED_LOCALES:
            raise AuthentikProfileError(
                f"locale must be one of {sorted(ALLOWED_LOCALES)}",
                status_code=400,
            )
        _set_attr(ensure_attrs(), ATTR_LOCALE, loc)

    if theme is not None:
        th = theme.strip()
        if th not in ALLOWED_THEMES:
            raise AuthentikProfileError(
                f"theme must be one of {sorted(ALLOWED_THEMES)}",
                status_code=400,
            )
        _set_attr(ensure_attrs(), ATTR_THEME, th)

    if attrs is not None:
        body["attributes"] = attrs

    if not body:
        return profile_from_ak_user(user)

    updated = await _request("PATCH", f"/core/users/{pk}/", json_body=body)
    if isinstance(updated, dict) and updated.get("pk") is not None:
        return profile_from_ak_user(updated)
    refreshed = await _request("GET", f"/core/users/{pk}/")
    if not isinstance(refreshed, dict):
        raise AuthentikProfileError("Empty response after profile PATCH", status_code=502)
    return profile_from_ak_user(refreshed)


async def sync_local_from_idp(
    *,
    authentik_sub: str | None,
    local_full_name: str | None,
    local_avatar_seed: str | None,
    local_locale: str | None = None,
    local_theme: str | None = None,
    local_email: str | None = None,
) -> UnifiedProfile | None:
    if not authentik_sub or not profile_sync_enabled():
        return None
    remote = await fetch_profile_by_sub(authentik_sub)
    if remote is None:
        return None

    if remote.avatar_seed is None and local_avatar_seed:
        try:
            remote = await push_profile_by_sub(
                authentik_sub,
                avatar_seed=local_avatar_seed,
            )
            remote.source = "bootstrap"
        except AuthentikProfileError as exc:
            logger.warning("avatar bootstrap push failed: %s", exc.message)
            return UnifiedProfile(
                full_name=remote.full_name or local_full_name,
                avatar_seed=local_avatar_seed,
                email=remote.email or local_email,
                locale=remote.locale or local_locale,
                theme=remote.theme or local_theme,
                authentik_pk=remote.authentik_pk,
                source="local",
            )

    return UnifiedProfile(
        full_name=(remote.full_name or local_full_name),
        avatar_seed=remote.avatar_seed if remote.avatar_seed is not None else local_avatar_seed,
        email=remote.email or local_email,
        locale=remote.locale if remote.locale is not None else local_locale,
        theme=remote.theme if remote.theme is not None else local_theme,
        authentik_pk=remote.authentik_pk,
        source=remote.source,
    )


def apply_profile_to_user(user: Any, profile: UnifiedProfile) -> bool:
    changed = False
    if profile.full_name and profile.full_name != (user.full_name or ""):
        user.full_name = profile.full_name
        changed = True
    if profile.avatar_seed != getattr(user, "avatar_seed", None):
        user.avatar_seed = profile.avatar_seed
        changed = True
    if hasattr(user, "locale") and profile.locale is not None:
        if profile.locale != getattr(user, "locale", None):
            user.locale = profile.locale
            changed = True
    if hasattr(user, "theme") and profile.theme is not None:
        if profile.theme != getattr(user, "theme", None):
            user.theme = profile.theme
            changed = True
    if profile.email is not None and hasattr(user, "email"):
        if profile.email != getattr(user, "email", None):
            user.email = profile.email
            changed = True
    return changed
