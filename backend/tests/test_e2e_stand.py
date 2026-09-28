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


def _dsn_from_env_file(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "DATABASE_URL":
            return value.strip()
    raise AssertionError(f"{path} не содержит DATABASE_URL")


def test_stand_database_is_not_the_dev_database() -> None:
    """За-commиченный конфиг стенда обязан указывать на отдельную БД."""
    stand = urlparse(_dsn_from_env_file(STAND_ENV_FILE))
    dev = urlparse(_dsn_from_env_file(DEV_ENV_FILE))
    assert stand.path.lstrip("/"), "DSN стенда без имени базы"
    assert stand.path.lstrip("/") != dev.path.lstrip("/"), (
        f"E2E-стенд указывает на общую dev-БД {dev.path!r} — прогон будет задевать чужую работу"
    )
    assert (stand.port, stand.hostname) != (dev.port, dev.hostname), (
        "E2E-стенд и devstack на одном Postgres: изоляция БД неполна"
    )


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
    assert "onnect" in output, output
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
