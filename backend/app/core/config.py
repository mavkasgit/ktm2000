import os
from pathlib import Path

from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent.parent
_env_file = os.getenv("ENV_FILE") or str(BASE_DIR.parent / ".env.dev")


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://ktm2000_user:ktm2000_pass@localhost:5432/ktm2000_dev"
    ENV: str = "dev"

    SECRET_KEY: str = "ktm2000-dev-secret-change-me"
    INTEGRATION_TOKEN: str = "ktm2000-integration-token-default"
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

    # OIDC / Authentik bridge — dual-run; false = local password/OTP only
    AUTH_OIDC_ENABLED: bool = False
    AUTH_OIDC_ISSUER: str | None = None  # e.g. http://localhost:9000/application/o/ktm2000/
    AUTH_OIDC_CLIENT_ID: str | None = None
    AUTH_OIDC_CLIENT_SECRET: str | None = None  # empty for public+PKCE
    AUTH_OIDC_REDIRECT_URI: str | None = None  # e.g. http://localhost:8082/auth/callback
    AUTH_OIDC_SCOPES: str = "openid profile email"
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

    # Authentik Admin API — unified profile (name + avatar). Token never exposed to FE.
    # AUTHENTIK_*_URL: absolute URL or "auto" (detect host LAN IP at runtime)
    AUTHENTIK_API_URL: str | None = "auto"
    AUTHENTIK_API_TOKEN: str | None = None
    AUTHENTIK_PUBLIC_URL: str | None = "auto"

    model_config = {"env_file": _env_file, "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()



