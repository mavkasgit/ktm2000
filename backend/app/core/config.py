import os
from pathlib import Path

import re

from pydantic import model_validator
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent.parent
_env_file = os.getenv("ENV_FILE") or str(BASE_DIR.parent / ".env.dev")


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://ktm2000_user:ktm2000_pass@localhost:5432/ktm2000_dev"
    ENV: str = "dev"

    SECRET_KEY: str = "ktm2000-dev-secret-change-me"
    JWT_SECRET_KEY: str | None = None
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    ALGORITHM: str = "HS256"
    DEV_BYPASS_AUTH: bool = False

    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    SQL_ECHO: bool = False

    CORS_ORIGINS: str = "*"
    IMPORT_STORAGE_DIR: str = "/app/storage/imports"
    PRODUCT_PHOTO_DIR: str = "/app/storage/products"
    BACKUPS_PATH: str = "/app/storage/backups"
    POSTGRES_CONTAINER_NAME: str = "ktm2000-postgres"

    # HRMS integration — employee sync
    HRMS_BASE_URL: str | None = None
    HRMS_API_TOKEN: str = "admin"

    # OIDC / Authentik bridge — false = break-glass login only
    AUTH_OIDC_ENABLED: bool = False
    AUTH_OIDC_ISSUER: str | None = None  # e.g. http://localhost:9000/application/o/ktm2000/
    AUTH_OIDC_CLIENT_ID: str | None = None
    AUTH_OIDC_CLIENT_SECRET: str | None = None  # empty for public+PKCE
    AUTH_OIDC_REDIRECT_URI: str | None = None  # e.g. http://localhost:8082/auth/callback
    AUTH_OIDC_SCOPES: str = "openid profile email ktm_access"
    # Comma-separated extra hosts (or full URLs) accepted in id_token.iss
    AUTH_OIDC_ISSUER_ALIASES: str | None = None
    AUTH_OIDC_AUTHORIZATION_URL: str | None = None
    AUTH_OIDC_TOKEN_URL: str | None = None
    AUTH_OIDC_JWKS_URL: str | None = None
    AUTH_OIDC_END_SESSION_URL: str | None = None
    AUTH_OIDC_ALLOW_JIT: bool = False
    AUTH_OIDC_DEFAULT_ROLE: str = "viewer"
    # When true, soft-map IdP groups → users.role on link/JIT; default false = app SoT
    AUTH_OIDC_SYNC_ROLE_FROM_IDP: bool = False
    # SSO-only mode (informational flag in /auth/oidc/config): password paths removed
    AUTH_SSO_ONLY: bool = False
    AUTH_OIDC_LOGIN_HINT_ENABLED: bool = True

    # Break Glass (emergency) access — bypass Authentik when IdP is unreachable.
    BREAK_GLASS_ENABLED: bool = True
    BREAK_GLASS_USER: str = "emergency_admin"
    BREAK_GLASS_PASSWORD: str = "break-glass-dev"
    BREAK_GLASS_PASSWORD_HASH: str = ""

    # Authentik Admin API — unified profile (name + avatar). Token never exposed to FE.
    # AUTHENTIK_*_URL: absolute URL or "auto" (detect host LAN IP at runtime)
    AUTHENTIK_API_URL: str | None = "auto"
    AUTHENTIK_API_TOKEN: str | None = None
    AUTHENTIK_PUBLIC_URL: str | None = "auto"
    AUTHENTIK_PROFILE_TTL_SECONDS: int = 300

    # Login history window for /auth/me/login-events (days).
    LOGIN_EVENTS_RETENTION_DAYS: int = 90

    @model_validator(mode="after")
    def _resolve_variable_interpolation(self) -> "Settings":
        """Resolve ${VAR} references in string fields using already-loaded values.

        pydantic-settings reads .env files as literal key-value pairs — shell-style
        ``${VAR}`` syntax is NOT resolved.  This validator walks every string field
        and replaces ``${NAME}`` with the value of an already-set field or (as
        fallback) an OS environment variable.
        """
        resolved = {}
        # Collect all current string values for lookup.
        for name in self.model_fields:
            val = getattr(self, name, None)
            if isinstance(val, str):
                resolved[name] = val
                # Also expose under alias / env-name for robustness.
        for name in self.model_fields:
            raw = getattr(self, name, None)
            if not isinstance(raw, str):
                continue

            def _replace(m: re.Match) -> str:
                varname = m.group(1)
                # 1. Already-set field value.
                if varname in resolved:
                    return resolved[varname]
                # 2. OS environment fallback.
                fallback = os.environ.get(varname)
                if fallback is not None:
                    return fallback
                # Leave unresolved — pydantic will keep the literal text.
                return m.group(0)

            new_val = re.sub(r"\$\{(\w+)\}", _replace, raw)
            if new_val != raw:
                setattr(self, name, new_val)
                resolved[name] = new_val
        return self

    model_config = {"env_file": _env_file, "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()



