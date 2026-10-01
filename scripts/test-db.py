"""CLI for per-run isolated test databases (KTM-2000).

The test launcher (scripts/test-run.ps1) owns the lifecycle of a run-DB:

    test-db.py create  <db>    -- create run-DB + record owner row
    test-db.py verify  <db>    -- SELECT 1 against the run-DB
    test-db.py drop    <db>    -- terminate conns, drop a DB whose owner row
                                  matches, clear that row (run-DB or
                                  ktm_mig_* registered by the tests)
    test-db.py drop --force <db> -- drop a DB without an owner row (legacy
                                  ktm_mig_* left by an interrupted run from
                                  before migration tests wrote owner rows)
    test-db.py cleanup          -- drop orphan run-DBs (by TTL or unowned) and
                                  registered `ktm_mig_*` by TTL, plus stale test
                                  storage dirs (ktm2000_pytest_storage*)

The owner row is written BEFORE ``CREATE DATABASE``, so an interrupted run
always leaves either no DB or a DB with an owner row that the TTL cleanup can
age — both for run-DBs (this CLI) and for ``ktm_mig_*`` (tests create them via
``tests/helpers/mig_db.py``, which writes the same owner row through
``scripts/test_db_owner.py``). ``drop`` only removes a DB whose owner row
matches, and TTL cleanup skips any DB with active connections; test storage
dirs are removed by mtime once they are older than the TTL (a live run keeps
its dir fresh).

Names are strictly validated: only ``ktm2000_test_<12 hex>`` and
``ktm_mig_<10 hex>`` are ever touched. ``--force`` skips the owner-row check
(legacy DBs), never the name check. Protected names
(``postgres``/``template0``/``template1``) are refused either way.

The owner table itself — its DDL, name patterns and ``run_id`` derivation —
lives in ``scripts/test_db_owner.py`` (single source of truth: the same module
is imported by ``tests/helpers/mig_db.py``).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import os
import pathlib
import shutil
import sys
import tempfile

import asyncpg

# Owner-таблица, регекспы имён и вывод `run_id` — в scripts/test_db_owner.py
# (единственный источник правды; тот же модуль импортирует
# tests/helpers/mig_db.py). Скрипт запускается как `python scripts/test-db.py`,
# поэтому каталог scripts/ уже первый в sys.path.
from test_db_owner import (
    MIG_DB_PREFIX,
    MIG_DB_RE,
    OWNER_TABLE,
    RUN_DB_PREFIX,
    RUN_DB_RE,
    delete_owner_row,
    ensure_owner_table,
    insert_owner_row,
)

# --- Config (env-overridable; matches infra/compose/docker-compose.test.yml) ---
POSTGRES_HOST = os.getenv("TEST_DB_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("TEST_DB_PORT", "5441"))
POSTGRES_USER = os.getenv("TEST_DB_ADMIN_USER", "ktm2000_user")
POSTGRES_PASSWORD = os.getenv("TEST_DB_ADMIN_PASSWORD", "ktm2000_pass_test")
POSTGRES_ADMIN_DB = os.getenv("TEST_DB_ADMIN_DATABASE", "postgres")

#: Каталог storage тестов (`conftest.py`): `ktm2000_pytest_storage_<tag>`, а у
#: прогонов до изоляции — общий `ktm2000_pytest_storage`.
STORAGE_DIR_PREFIX = "ktm2000_pytest_storage"
#: Служебные базы: не трогаются даже с --force. Тот же набор, что в
#: scripts/e2e-db.py (PROTECTED_DB_NAMES).
PROTECTED_DB_NAMES = frozenset({"postgres", "template0", "template1"})
DEFAULT_TTL_HOURS = float(os.getenv("TEST_DB_CLEANUP_TTL_HOURS", "24"))


def validate_run_db_name(db_name: str) -> None:
    if not RUN_DB_RE.fullmatch(db_name):
        raise ValueError(
            f"Refusing to touch unsafe database name {db_name!r}: "
            f"must match {RUN_DB_RE.pattern}"
        )


def validate_drop_db_name(db_name: str) -> None:
    """Проверка имени для `drop`: run-DB или база миграционного теста.

    Годится и без ``--force``: у ``ktm_mig_*`` owner-строка есть (её пишут
    ``tests/helpers/mig_db.py`` и этот CLI), а ``_drop_owned`` всё равно
    отказывает базе без совпадающей owner-строки.
    """
    if db_name in PROTECTED_DB_NAMES:
        raise ValueError(f"Refusing to drop protected database {db_name!r}")
    if RUN_DB_RE.fullmatch(db_name) or MIG_DB_RE.fullmatch(db_name):
        return
    raise ValueError(
        f"Refusing to touch unsafe database name {db_name!r}: "
        f"must match {RUN_DB_RE.pattern} or {MIG_DB_RE.pattern}"
    )


async def _admin_conn() -> asyncpg.Connection:
    return await asyncpg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        database=POSTGRES_ADMIN_DB,
    )


async def _terminate_and_drop(conn: asyncpg.Connection, db_name: str) -> None:
    await conn.execute(
        "SELECT pg_terminate_backend(pid) "
        "FROM pg_stat_activity "
        "WHERE datname = $1 AND pid <> pg_backend_pid()",
        db_name,
    )
    await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')


async def create(db_name: str) -> None:
    validate_run_db_name(db_name)
    conn = await _admin_conn()
    try:
        await ensure_owner_table(conn)
        await insert_owner_row(conn, db_name)
        try:
            await conn.execute(f'CREATE DATABASE "{db_name}"')
        except asyncpg.DuplicateDatabaseError:
            pass
    except BaseException:
        await delete_owner_row(conn, db_name)
        raise
    finally:
        await conn.close()
    print(f"Created test database: {db_name}")


async def verify(db_name: str) -> None:
    validate_run_db_name(db_name)
    conn = await asyncpg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        database=db_name,
    )
    try:
        value = await conn.fetchval("SELECT 1")
        if value != 1:
            raise RuntimeError(f"SELECT 1 on {db_name} returned {value!r}")
    finally:
        await conn.close()
    print(f"Verified test database: {db_name}")


async def _drop_owned(conn: asyncpg.Connection, db_name: str) -> bool:
    """Только база со своей owner-строкой: её пишут до ``CREATE DATABASE``.

    Для ``ktm_mig_*`` owner-строку пишут тесты (``tests/helpers/mig_db.py``),
    для run-DB — ``create``; база без строки (легаси) требует ``--force``.
    """
    owned = await conn.fetchval(
        f"SELECT 1 FROM {OWNER_TABLE} WHERE db_name = $1", db_name
    )
    if not owned:
        print(f"Skip drop {db_name}: no owner row")
        return False
    await _terminate_and_drop(conn, db_name)
    await delete_owner_row(conn, db_name)
    return True


async def _drop_forced(conn: asyncpg.Connection, db_name: str) -> bool:
    """Уборка базы без owner-строки (`ktm_mig_*` от прерванного прогона).

    Активные соединения — отказ, как и в `cleanup`: живую чужую базу не трогаем.
    """
    exists = await conn.fetchval(
        "SELECT 1 FROM pg_database WHERE datname = $1", db_name
    )
    if not exists:
        print(f"Skip drop {db_name}: no such database")
        return False
    active = await conn.fetchval(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE datname = $1 AND pid <> pg_backend_pid()",
        db_name,
    )
    if active:
        print(f"Skip drop {db_name}: active connections ({active})")
        return False
    await _terminate_and_drop(conn, db_name)
    await delete_owner_row(conn, db_name)
    return True


async def drop(db_name: str, force: bool = False) -> None:
    validate_drop_db_name(db_name)
    conn = await _admin_conn()
    try:
        await ensure_owner_table(conn)
        dropped = (
            await _drop_forced(conn, db_name)
            if force
            else await _drop_owned(conn, db_name)
        )
    finally:
        await conn.close()
    if dropped:
        print(f"Dropped test database: {db_name}")


async def cleanup(ttl_hours: float, dry_run: bool = False) -> None:
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        hours=ttl_hours
    )
    conn = await _admin_conn()
    dropped = 0
    try:
        await ensure_owner_table(conn)
        rows = await conn.fetch(
            "SELECT datname FROM pg_database WHERE datname LIKE $1",
            f"{RUN_DB_PREFIX}%",
        )
        for row in rows:
            db_name = row["datname"]
            if not RUN_DB_RE.fullmatch(db_name):
                continue
            active = await conn.fetchval(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                db_name,
            )
            if active:
                print(f"SKIP  {db_name}: active connections ({active})")
                continue
            has_owner = await conn.fetchval(
                f"SELECT 1 FROM {OWNER_TABLE} WHERE db_name = $1", db_name
            )
            if has_owner:
                old = await conn.fetchval(
                    f"SELECT 1 FROM {OWNER_TABLE} "
                    "WHERE db_name = $1 AND created_at < $2",
                    db_name,
                    cutoff,
                )
                if not old:
                    print(f"SKIP  {db_name}: younger than {ttl_hours:g}h TTL")
                    continue
                reason = f"older than {ttl_hours:g}h TTL"
            else:
                reason = "unowned orphan"
            if dry_run:
                print(f"DRY   {db_name}: {reason}")
            else:
                print(f"DROP  {db_name}: {reason}")
                await _terminate_and_drop(conn, db_name)
                await delete_owner_row(conn, db_name)
                dropped += 1

        # Базы миграционных тестов (`ktm_mig_<10 hex>`) регистрируются helper'ом
        # `tests/helpers/mig_db.py` в той же owner-таблице, но под префикс run-DB
        # не попадают — их берём из owner-таблицы по TTL. Легаси-базу без
        # owner-строки (созданную до конверсии тестов) cleanup не трогает: для
        # неё остаётся `drop --force`.
        mig_rows = await conn.fetch(
            f"SELECT db_name, created_at FROM {OWNER_TABLE} WHERE db_name LIKE $1",
            f"{MIG_DB_PREFIX}%",
        )
        for row in mig_rows:
            db_name = row["db_name"]
            if not MIG_DB_RE.fullmatch(db_name):
                continue
            if row["created_at"] >= cutoff:
                print(f"SKIP  {db_name}: younger than {ttl_hours:g}h TTL")
                continue
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", db_name
            )
            if not exists:
                # Базу уже убрали (например, `drop`) — снимаем висячую owner-строку.
                await delete_owner_row(conn, db_name)
                continue
            active = await conn.fetchval(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                db_name,
            )
            if active:
                print(f"SKIP  {db_name}: active connections ({active})")
                continue
            reason = f"migration DB older than {ttl_hours:g}h TTL"
            if dry_run:
                print(f"DRY   {db_name}: {reason}")
            else:
                print(f"DROP  {db_name}: {reason}")
                await _terminate_and_drop(conn, db_name)
                await delete_owner_row(conn, db_name)
                dropped += 1
    finally:
        await conn.close()
    print(f"Cleanup finished. Dropped {dropped} database(s).")
    _cleanup_storage_dirs(ttl_hours, dry_run)


def _cleanup_storage_dirs(ttl_hours: float, dry_run: bool) -> None:
    """Убирает каталоги storage тестов старше TTL (те, что оставили прерванные прогоны).

    Каталог у каждого прогона свой (`conftest.py`: `ktm2000_pytest_storage_<tag>`)
    и удаляется по завершении, но прерванный прогон оставить его может — а
    старый (до этой изоляции) общий каталог `ktm2000_pytest_storage` не убирался
    вообще. Возраст берём по mtime каталога: у живого прогона он свежий.
    """
    temp_root = pathlib.Path(tempfile.gettempdir())
    cutoff = datetime.datetime.now().timestamp() - ttl_hours * 3600
    removed = 0
    for path in sorted(temp_root.glob(f"{STORAGE_DIR_PREFIX}*")):
        if not path.is_dir():
            continue
        age_ok = path.stat().st_mtime < cutoff
        if not age_ok:
            print(f"SKIP  {path.name}: younger than {ttl_hours:g}h TTL")
            continue
        if dry_run:
            print(f"DRY   {path.name}: storage older than {ttl_hours:g}h TTL")
            continue
        shutil.rmtree(path, ignore_errors=True)
        print(f"DROP  {path.name}: storage older than {ttl_hours:g}h TTL")
        removed += 1
    print(f"Cleanup finished. Removed {removed} storage dir(s).")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="test-db.py",
        description="Per-run isolated test databases (KTM-2000).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="create a run-DB")
    p_create.add_argument("db_name")

    p_verify = sub.add_parser("verify", help="SELECT 1 against a run-DB")
    p_verify.add_argument("db_name")

    p_drop = sub.add_parser("drop", help="drop a test DB that has an owner row")
    p_drop.add_argument("db_name")
    p_drop.add_argument(
        "--force",
        action="store_true",
        help=(
            "drop a database that has no owner row (legacy ktm_mig_* left by an "
            "interrupted run from before migration tests registered owner rows); "
            "refuses while it has active connections"
        ),
    )

    p_cleanup = sub.add_parser(
        "cleanup",
        help="drop orphan run-DBs and stale test storage dirs by TTL",
    )
    p_cleanup.add_argument("--ttl-hours", type=float, default=DEFAULT_TTL_HOURS)
    p_cleanup.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    async def _run() -> None:
        if args.command == "create":
            await create(args.db_name)
        elif args.command == "verify":
            await verify(args.db_name)
        elif args.command == "drop":
            await drop(args.db_name, args.force)
        elif args.command == "cleanup":
            await cleanup(args.ttl_hours, args.dry_run)
        else:  # pragma: no cover
            parser.error(f"Unknown command: {args.command}")

    try:
        asyncio.run(_run())
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
