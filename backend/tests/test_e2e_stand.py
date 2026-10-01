"""E2E-стенд не имеет права работать на общей dev-БД (#220).

Проверяется то, что реально ломает чужую работу: DSN стенда из
`<repo>/.env.e2e` и команда `scripts/e2e-db.py ensure`, которая готовит его БД
(и должна отказаться, если её направили на dev-БД).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
STAND_ENV_FILE = REPO_ROOT / ".env.e2e"
DEV_ENV_FILE = REPO_ROOT / ".env.dev"
E2E_DB_SCRIPT = REPO_ROOT / "scripts" / "e2e-db.py"

EXIT_GUARD = 2
"""Код возврата guard'а «стенд нацелен на чужую БД»."""

# Подстраховка на случай, если `.env.dev` локально отсутствует или переименован:
# файл gitignored (`.gitignore:9 .env.*`) и создаётся руками по
# docs/GETTING_STARTED.md. Тот же набор, что в `scripts/e2e-db.py` — конвенция
# на репозиторий одна, а не две.
FALLBACK_DEV_DB_NAMES = {"ktm2000_dev"}
FALLBACK_DEV_ENDPOINTS = {("localhost", 5440), ("127.0.0.1", 5440)}


def _env_values(path: Path) -> dict[str, str]:
    """Минимальный разбор `KEY=VALUE` (без dotenv: тесту нужны три ключа)."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        key = key.strip()
        if key and not key.startswith("#"):
            values[key] = value.strip()
    return values


def _required_dsn(path: Path) -> str:
    dsn = _env_values(path).get("DATABASE_URL")
    if not dsn:
        raise AssertionError(f"{path} не содержит DATABASE_URL")
    return dsn


def _endpoint(dsn: str) -> tuple[str, int]:
    parsed = urlparse(dsn)
    return (parsed.hostname or "localhost", parsed.port or 5432)


def _dev_databases(env_file: Path = DEV_ENV_FILE) -> tuple[set[str], set[tuple[str, int]]]:
    """Имена баз и endpoint'ы, занятые devstack'ом (семантика `dev_databases()`
    из `scripts/e2e-db.py`): набор начинается с fallback'а и дополняется
    содержимым `.env.dev`, если файл есть. Отсутствие файла — не ошибка.
    """
    names = set(FALLBACK_DEV_DB_NAMES)
    endpoints = set(FALLBACK_DEV_ENDPOINTS)
    if not env_file.is_file():
        return names, endpoints
    values = _env_values(env_file)
    dsn = values.get("DATABASE_URL")
    if dsn:
        names.add(urlparse(dsn).path.lstrip("/"))
        endpoints.add(_endpoint(dsn))
    else:
        if values.get("POSTGRES_DB"):
            names.add(values["POSTGRES_DB"])
        if values.get("DEV_POSTGRES_PORT"):
            endpoints.add(("localhost", int(values["DEV_POSTGRES_PORT"])))
    return names, endpoints


def test_stand_database_is_not_the_dev_database() -> None:
    """За-commиченный конфиг стенда обязан указывать на отдельную БД.

    Сравнение идёт с набором dev-баз/endpoint'ов (fallback + `.env.dev`, если он
    есть): без локального `.env.dev` тест не падает, но проверка остаётся.
    """
    stand_dsn = _required_dsn(STAND_ENV_FILE)
    stand = urlparse(stand_dsn)
    stand_name = stand.path.lstrip("/")
    assert stand_name, "DSN стенда без имени базы"

    dev_names, dev_endpoints = _dev_databases()
    assert stand_name not in dev_names, (
        f"E2E-стенд указывает на общую dev-БД {stand_name!r} — прогон будет задевать чужую работу"
    )
    assert _endpoint(stand_dsn) not in dev_endpoints, (
        "E2E-стенд и devstack на одном Postgres: изоляция БД неполна"
    )


def test_dev_databases_falls_back_without_env_dev(tmp_path: Path) -> None:
    """Нет `.env.dev` — набор dev-целей не пуст: иначе проверку не с чем делать."""
    names, endpoints = _dev_databases(tmp_path / ".env.dev")
    assert names == FALLBACK_DEV_DB_NAMES
    assert endpoints == FALLBACK_DEV_ENDPOINTS


def test_dev_databases_reads_database_url(tmp_path: Path) -> None:
    """Локальный `.env.dev` расширяет набор, а не заменяет fallback."""
    env_file = tmp_path / ".env.dev"
    env_file.write_text(
        "DATABASE_URL=postgresql+asyncpg://ktm2000_user:ktm2000_pass@127.0.0.1:5440/ktm2000_local\n",
        encoding="utf-8",
    )
    names, endpoints = _dev_databases(env_file)
    assert "ktm2000_local" in names
    assert ("127.0.0.1", 5440) in endpoints
    assert names >= FALLBACK_DEV_DB_NAMES
    assert endpoints >= FALLBACK_DEV_ENDPOINTS


def test_dev_databases_reads_postgres_db_and_port_without_url(tmp_path: Path) -> None:
    """`.env.dev` без `DATABASE_URL`: имя базы и порт берутся из отдельных ключей."""
    env_file = tmp_path / ".env.dev"
    env_file.write_text("POSTGRES_DB=ktm2000_other\nDEV_POSTGRES_PORT=5555\n", encoding="utf-8")
    names, endpoints = _dev_databases(env_file)
    assert "ktm2000_other" in names
    assert ("localhost", 5555) in endpoints


def test_ensure_refuses_dev_database(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.e2e"
    env_file.write_text(
        "DATABASE_URL=postgresql+asyncpg://ktm2000_user:ktm2000_pass@localhost:5440/ktm2000_dev\n",
        encoding="utf-8",
    )
    result = _run_ensure(env_file)
    assert result.returncode == EXIT_GUARD, result.stdout + result.stderr
    assert "ktm2000_dev" in result.stdout + result.stderr


def test_ensure_lets_isolated_database_through(tmp_path: Path) -> None:
    """Свой Postgres недоступен — это сетевая ошибка (код 1), а не отказ guard'а."""
    env_file = tmp_path / ".env.e2e"
    env_file.write_text(
        "DATABASE_URL=postgresql+asyncpg://ktm2000_user:ktm2000_pass_test@localhost:1/ktm2000_e2e\n",
        encoding="utf-8",
    )
    result = _run_ensure(env_file)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    # DSN приходит в SQLAlchemy-виде (`+asyncpg`): asyncpg такой схемы не
    # понимает, и без перевода он спотыкается ещё до попытки подключиться.
    assert "invalid DSN" not in output, output
    # Признак того, что дошли до попытки подключения, а остановились на
    # guard'е, — ветка `except Exception` вокруг `ensure_database` в
    # scripts/e2e-db.py: её префикс задан в репозитории. Текст исключения
    # внутри локализован Windows ("отклонил это сетевое подключение"), поэтому
    # искать в нём английскую подстроку "onnect" бессмысленно.
    assert "[e2e-db] не удалось подготовить БД стенда" in output, output
    assert "ktm2000_dev" not in output, output


def _run_ensure(env_file: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(E2E_DB_SCRIPT), "ensure", "--env-file", str(env_file)],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
