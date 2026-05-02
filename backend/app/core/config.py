import os
from pathlib import Path

from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent.parent
_env_file = os.getenv("ENV_FILE") or str(BASE_DIR.parent / ".env.dev")


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://factoryflow_user:factoryflow_pass@localhost:5202/factoryflow_dev"
    ENV: str = "dev"

    SECRET_KEY: str = "factoryflow-dev-secret-change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    ALGORITHM: str = "HS256"

    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    SQL_ECHO: bool = False

    CORS_ORIGINS: str = "http://localhost:5202"
    IMPORT_STORAGE_DIR: str = str(BASE_DIR.parent / "storage" / "imports")
    PRODUCT_PHOTO_DIR: str = str(BASE_DIR.parent / "storage" / "products")

    model_config = {"env_file": _env_file, "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()




