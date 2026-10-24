"""Одноразовая база миграционного теста (``ktm_mig_<10 hex>``) + owner-строка.

``tests/test_migrations.py`` и ``tests/test_hanger_norm_key_migration_218.py``
поднимают себе базу под каждую проверку и гоняют на ней alembic. Раньше базу
создавали напрямую (``CREATE DATABASE`` на admin-подключении) и owner-строки не
писали — TTL-уборка (``scripts/test-db.py cleanup``) такую базу не видела, и
осиротевшую после прерванного прогона убирал только ``drop --force``.

Хелпер пишет owner-строку ДО ``CREATE DATABASE`` — в ту же таблицу и тем же
модулем, что и CLI (``scripts/test_db_owner.py``), — и по завершении снимает и
базу, и строку::

    db_name, target_url = await create_migration_db()
    try:
        ...
    finally:
        await drop_migration_db(db_name)

Вызов в ``finally`` — на стороне теста: у миграционных тестов уже есть свой
``try/finally`` (там же гасится их engine, до дропа базы), и хелпер не
навязывает им лишний уровень вложенности на тысячу строк. Страховка от
обрыва между create и drop — owner-строка: такая база остаётся видимой для
``python scripts/test-db.py drop <db>``.
"""

from __future__ import annotations

import importlib
import os
import socket
import subprocess
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import asyncpg

if TYPE_CHECKING:
    from types import ModuleType

#: Корень backend: из него запускается alembic (там `alembic.ini`).
BACKEND_DIR = Path(__file__).resolve().parents[2]

# `scripts/` — не пакет (CLI там называется `test-db.py`, имя с дефисом), а
# pytest запускается с `backend/` в sys.path: ни корень репозитория, ни
# `scripts/` в него не входят. Модуль подтягиваем функцией, а не инструкцией
# `import`: импорт после правки `sys.path` иначе выглядит как E402.
_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_owner: ModuleType = importlib.import_module("test_db_owner")

#: DSN тестового Postgres — тот же контракт, что у launcher'а и `conftest.py`.
DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ktm2000_user:ktm2000_pass_test@localhost:5441/ktm2000_test"
)


def migration_db_url() -> str:
    """DSN тестового Postgres: ``TEST_DATABASE_URL`` или тестовый контракт.

    Имя без префикса ``test_``: pytest собирает из модуля тестов всё, что
    подходит под ``test*``, — импортированное имя иначе стало бы «тестом».
    """
    return os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)


def alembic_command(*args: str) -> list[str]:
    """Команда alembic из интерпретатора теста, а не из PATH.

    ``alembic`` в PATH может оказаться чужим или устаревшим (системный Python
    без актуальной версии alembic), и тест упадёт на верном коде.
    ``sys.executable -m alembic`` гарантирует то же окружение, что у тестов.
    """
    return [sys.executable, "-m", "alembic", *args]


def alembic_env(target_url: str, tmp_path: Path) -> dict[str, str]:
    """Окружение подпроцесса alembic: целевая БД и несуществующий env-файл.

    ``alembic/env.py`` вызывает ``apply_env_file()``, а тот по умолчанию
    перекрывает ``DATABASE_URL`` содержимым ``$ENV_FILE`` (по умолчанию
    ``<repo>/.env.dev``): переданный тестом DSN уехал бы на dev-базу.
    Отсутствующий путь внутри ``tmp_path`` — документированный no-op, DSN
    остаётся тем, что дал тест, и на диск ничего не пишется.
    """
    return {
        **os.environ,
        "DATABASE_URL": target_url,
        "ENV_FILE": str(tmp_path / "absent.env"),
    }


def migration_db_reachable() -> bool:
    """Тестовый Postgres доступен? Host/port — из ``TEST_DATABASE_URL``."""
    parsed = urlparse(migration_db_url())
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def run_alembic(args: tuple[str, ...], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Запустить alembic в подпроцессе и упасть на ненулевом коде."""
    result = subprocess.run(
        alembic_command(*args),
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result


def _admin_dsn() -> str:
    """DSN служебной БД ``postgres`` в форме asyncpg (без суффикса драйвера)."""
    base = migration_db_url().rsplit("/", 1)[0]
    return f"{base}/postgres".replace("postgresql+asyncpg://", "postgresql://")


async def create_migration_db() -> tuple[str, str]:
    """Создать ``ktm_mig_<10 hex>`` и зарегистрировать её.

    Возвращает ``(имя базы, DSN базы)``. Имя строится тем же префиксом, что
    признаёт ``scripts/test_db_owner.py``, — иначе ``drop`` его не примет.
    """
    db_name = f"{_owner.MIG_DB_PREFIX}{uuid.uuid4().hex[:10]}"
    target_url = f"{migration_db_url().rsplit('/', 1)[0]}/{db_name}"
    conn = await asyncpg.connect(_admin_dsn())
    try:
        await _owner.ensure_owner_table(conn)
        await _owner.insert_owner_row(conn, db_name)
        await conn.execute(f'CREATE DATABASE "{db_name}"')
    except BaseException:
        # Базы не появилось — owner-строка не должна пережить попытку.
        await _owner.delete_owner_row(conn, db_name)
        raise
    finally:
        await conn.close()
    return db_name, target_url


async def drop_migration_db(db_name: str) -> None:
    """Дропнуть базу миграционного теста и её owner-строку (идемпотентно)."""
    if not _owner.MIG_DB_RE.fullmatch(db_name):
        raise ValueError(f"Not a migration-test database name: {db_name!r}")
    conn = await asyncpg.connect(_admin_dsn())
    try:
        await _owner.ensure_owner_table(conn)
        # Соединения теста (SQLAlchemy engine) могут быть ещё живы — гасим их
        # перед DROP, как это делает scripts/test-db.py.
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            db_name,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        await _owner.delete_owner_row(conn, db_name)
    finally:
        await conn.close()
