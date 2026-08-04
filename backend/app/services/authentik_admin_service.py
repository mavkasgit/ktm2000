"""
Authentik Admin API proxy (KTM) — тонкая обёртка над authentik_client.

Общий сетевой слой (httpx, заголовки, обработка ошибок, резолв origin) живёт в
``app.services.authentik_client`` (канон, копируется между приложениями).
Здесь остаётся KTM-специфика: deep-link URL-ы для профиля.
"""

from __future__ import annotations

from app.core.config import settings
from app.services.authentik_client import public_base_url

__all__ = ["idp_links_data", "sso_dashboard_url", "user_settings_url"]


def idp_links_data() -> dict:
    """Deep-links payload профиля (общий для /auth/me/links).

    Канон user-settings 2.0.0: две кнопки в блоке «Способы входа в систему» —
    дашборд SSO (``sso_dashboard_url``) и сразу настройки входа
    (``user_settings_url``).
    """
    return {
        "oidc_enabled": bool(settings.AUTH_OIDC_ENABLED),
        "user_settings_url": user_settings_url(),
        "sso_dashboard_url": sso_dashboard_url(),
    }


def user_settings_url() -> str | None:
    """Страница настроек входа Authentik (таргет кнопки «Открыть настройки входа»)."""
    base = public_base_url()
    return f"{base}/if/user/#/settings" if base else None


def sso_dashboard_url() -> str | None:
    """Дашборд Authentik (таргет кнопки «Дашборд SSO»)."""
    base = public_base_url()
    return f"{base}/if/user/" if base else None
