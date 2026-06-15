import os
from pathlib import Path

from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent.parent
_env_file = os.getenv("ENV_FILE") or str(BASE_DIR.parent / ".env.dev")


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://ktm2000_user:ktm2000_pass@localhost:5432/ktm2000_dev"
    ENV: str = "dev"

    SECRET_KEY: str = "ktm2000-dev-secret-change-me"
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

    model_config = {"env_file": _env_file, "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()



