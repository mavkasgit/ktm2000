"""
Authentik Admin API proxy (KTM) — тонкая обёртка над authentik_client.

Общий сетевой слой (httpx, заголовки, обработка ошибок, резолв origin) живёт в
``app.services.authentik_client`` (канон, копируется между приложениями).
Здесь остаётся KTM-специфика: deep-link URL-ы для профиля.
"""

from __future__ import annotations

from app.core.config import settings
from app.services.authentik_client import public_base_url

__all__ = ["idp_links_data", "user_settings_url"]


def idp_links_data() -> dict:
    """Deep-links payload профиля (общий для /auth/me/links)."""
    return {
        "oidc_enabled": bool(settings.AUTH_OIDC_ENABLED),
        "user_settings_url": user_settings_url(),
    }


def user_settings_url() -> str | None:
    base = public_base_url()
    return f"{base}/if/user/" if base else None
