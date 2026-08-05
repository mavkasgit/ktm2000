"""Проверка что Alembic-цепочка поднимает схему с нуля."""

from __future__ import annotations

import os
import socket
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.models.base import Base
import app.models  # noqa: F401

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _test_db_url() -> str:
    """The pytest postgres (localhost:5441) — not the stale dev default (5432).

    Honors TEST_DATABASE_URL set by the npm scripts; falls back to the test
    compose contract (port 5441 / ktm2000_pass_test) so the migration test
    runs against the same server conftest targets.
    """
    return os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://ktm2000_user:ktm2000_pass_test@localhost:5441/ktm2000_test",
    )


def _db_reachable() -> bool:
    """Check if the PostgreSQL server is reachable (host:port from DATABASE_URL)."""
    parsed = urlparse(_test_db_url())
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _db_reachable(),
    reason="PostgreSQL server not reachable for migration test",
)


@pytest.mark.asyncio
async def test_alembic_upgrade_head_creates_full_schema():
    db_name = f"ktm_mig_{uuid.uuid4().hex[:10]}"
    admin_url = _test_db_url().rsplit("/", 1)[0] + "/postgres"
    target_url = _test_db_url().rsplit("/", 1)[0] + f"/{db_name}"

    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    await admin_engine.dispose()

    env = {**os.environ, "DATABASE_URL": target_url}
    try:
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout

        engine = create_async_engine(target_url)
        async with engine.connect() as conn:
            table_names = set(await conn.run_sync(
                lambda sync_conn: set(inspect(sync_conn).get_table_names())
            ))
            row = (
                await conn.execute(
                    text(
                        "SELECT id, username, email FROM users "
                        "WHERE username = 'system' OR email = 'system@local'"
                    )
                )
            ).one()
        await engine.dispose()

        expected = {t.name for t in Base.metadata.sorted_tables}
        missing = expected - table_names
        assert not missing, f"Tables missing after alembic upgrade: {sorted(missing)}"
        assert row.id == 1
        assert row.username == "system"
        assert row.email == "system@local"
    finally:
        admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin_engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        await admin_engine.dispose()