"""Env-файл приложения: путь и загрузка в процесс.

Источник правды для DSN и прочих настроек — файл (`.env.dev` по умолчанию,
`$ENV_FILE` для `.env.prod`/`.env.test`). Модуль существует отдельно от
`app.core.config`, потому что `Settings` при импорте сразу читает окружение
процесса, а pydantic отдаёт ему приоритет над файлом. Из-за этого устаревшая
`DATABASE_URL` в окружении (протечка из шелла, CI, редактора) молча уводила
`alembic` и dev-сервер на другую БД. `apply_env_file(override=True)` перекрывает
окружение файлом — вызывать её нужно **до** импорта приложения.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_ENV_FILE = BACKEND_DIR.parent / ".env.dev"


def env_file_path() -> Path:
    """`$ENV_FILE`, иначе `<repo>/.env.dev`."""
    return Path(os.getenv("ENV_FILE") or DEFAULT_ENV_FILE)


def apply_env_file(override: bool = True) -> Path:
    """Загрузить env-файл в `os.environ`; вернуть путь к файлу.

    Отсутствующий файл — no-op: в прод-контейнере DSN задаёт compose, и
    подменять его нечем.
    """
    path = env_file_path()
    if path.is_file():
        load_dotenv(path, override=override, encoding="utf-8")
    return path
