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


@pytest.mark.asyncio
async def test_migration_032_scalar_quantity_per_hanger_to_per_length():
    """#60: скаляр quantity_per_hanger в attributes → {первая_длина: {auto, manual}}."""
    db_name = f"ktm_mig_{uuid.uuid4().hex[:10]}"
    admin_url = _test_db_url().rsplit("/", 1)[0] + "/postgres"
    target_url = _test_db_url().rsplit("/", 1)[0] + f"/{db_name}"

    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    await admin_engine.dispose()

    env = {**os.environ, "DATABASE_URL": target_url}
    try:
        # 1. До нужной ревизии (031) — скалярная форма ещё актуальна.
        result = subprocess.run(
            ["alembic", "upgrade", "031_users_profile_sync_failed_at"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout

        # 2. Вставляем продукт со скаляром quantity_per_hanger и двумя длинами.
        engine = create_async_engine(target_url)
        async with engine.begin() as conn:
            product_id = (
                await conn.execute(
                    text(
                        "INSERT INTO products (sku, name, type, unit, is_active, attributes) "
                        "VALUES ('RAW-LEGACY', 'Legacy', 'component', 'pcs', true, "
                        "'{\"quantity_per_hanger\": 25}'::jsonb) RETURNING id"
                    )
                )
            ).scalar_one()
            await conn.execute(
                text(
                    "INSERT INTO product_lengths (product_id, length_mm) VALUES "
                    "(:pid, 3500), (:pid, 2800)"
                ),
                {"pid": product_id},
            )
        await engine.dispose()

        # 3. Upgrade до head → скаляр мигрируется в {первая_длина: {auto, manual}}.
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
            attrs = (
                await conn.execute(
                    text("SELECT attributes FROM products WHERE id = :pid"),
                    {"pid": product_id},
                )
            ).scalar_one()
        await engine.dispose()

        qph = attrs["quantity_per_hanger"]
        # Первая длина по возрастанию = 2800 → ручной fallback туда.
        assert qph == {"2800": {"auto": None, "manual": 25}}
    finally:
        admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin_engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        await admin_engine.dispose()


@pytest.mark.asyncio
async def test_migration_036_primary_length_backfill():
    """#81: is_primary на product_lengths — основной становится первая длина по возрастанию."""
    db_name = f"ktm_mig_{uuid.uuid4().hex[:10]}"
    admin_url = _test_db_url().rsplit("/", 1)[0] + "/postgres"
    target_url = _test_db_url().rsplit("/", 1)[0] + f"/{db_name}"

    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    await admin_engine.dispose()

    env = {**os.environ, "DATABASE_URL": target_url}
    try:
        # 1. До 036 (035) — колонки is_primary ещё нет.
        result = subprocess.run(
            ["alembic", "upgrade", "035_internal_notifications"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout

        # 2. Два продукта с длинами не по возрастанию вставки.
        engine = create_async_engine(target_url)
        async with engine.begin() as conn:
            p1 = (
                await conn.execute(
                    text(
                        "INSERT INTO products (sku, name, type, unit, is_active, attributes) "
                        "VALUES ('RAW-PRIM-M1', 'P1', 'component', 'pcs', true, '{}'::jsonb) RETURNING id"
                    )
                )
            ).scalar_one()
            p2 = (
                await conn.execute(
                    text(
                        "INSERT INTO products (sku, name, type, unit, is_active, attributes) "
                        "VALUES ('RAW-PRIM-M2', 'P2', 'component', 'pcs', true, '{}'::jsonb) RETURNING id"
                    )
                )
            ).scalar_one()
            await conn.execute(
                text(
                    "INSERT INTO product_lengths (product_id, length_mm) VALUES "
                    "(:p1, 3500), (:p1, 2800), (:p2, 3000), (:p2, 5000)"
                ),
                {"p1": p1, "p2": p2},
            )
        await engine.dispose()

        # 3. Upgrade до head → основная = первая длина по возрастанию (2800, 3000).
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
            rows = (
                await conn.execute(
                    text(
                        "SELECT product_id, length_mm FROM product_lengths "
                        "WHERE is_primary = true ORDER BY product_id"
                    )
                )
            ).all()
            # Ровно по одной основной на продукт.
            assert [r.product_id for r in rows] == [p1, p2]
            assert [r.length_mm for r in rows] == [2800, 3000]
        await engine.dispose()
    finally:
        admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin_engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        await admin_engine.dispose()


@pytest.mark.asyncio
async def test_migration_038_paired_quantity_min():
    """#67: «разное кол-во» парной техкарты → общее N = min(оба).

    quantity_a_per_item != quantity_b_per_item приводятся к min; если задано
    только одно поле — оно копируется в оба; quantity_total, равный старой
    сумме a+b, пересчитывается в N×2. Стандартные техкарты не трогаются.
    """
    db_name = f"ktm_mig_{uuid.uuid4().hex[:10]}"
    admin_url = _test_db_url().rsplit("/", 1)[0] + "/postgres"
    target_url = _test_db_url().rsplit("/", 1)[0] + f"/{db_name}"

    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    await admin_engine.dispose()

    env = {**os.environ, "DATABASE_URL": target_url}
    try:
        # 1. До 038 (037) — «разное кол-во» ещё возможно.
        result = subprocess.run(
            ["alembic", "upgrade", "037_notification_state"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout

        # 2. Парные техкарты с разным / равным / частичным / расходящимся кол-вом.
        engine = create_async_engine(target_url)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO techcards "
                    "(product_id, version, processing_type, is_active, quantity_total, quantity_a_per_item, quantity_b_per_item) VALUES "
                    "(NULL, 'v1', 'paired_processing', true, 20, 8, 12),"
                    "(NULL, 'v2', 'paired_processing', true, 16, 8, 8),"
                    "(NULL, 'v3', 'paired_processing', true, NULL, 8, NULL),"
                    "(NULL, 'v4', 'standart_processing', true, 20, 8, 12),"
                    "(NULL, 'v5', 'paired_processing', true, 99, 8, 8)"
                )
            )
        await engine.dispose()

        # 3. Upgrade до head → миграция 038 применяется.
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
            rows = (
                await conn.execute(
                    text(
                        "SELECT version, quantity_total, quantity_a_per_item, quantity_b_per_item "
                        "FROM techcards ORDER BY version"
                    )
                )
            ).all()
        await engine.dispose()

        by_version = {r.version: r for r in rows}
        # Разное кол-во (8/12) → min = 8; общее 20 = 8+12 → N×2 = 16.
        v1 = by_version["v1"]
        assert (v1.quantity_a_per_item, v1.quantity_b_per_item) == (8, 8)
        assert v1.quantity_total == 16
        # Уже равные и согласованные не трогаются.
        v2 = by_version["v2"]
        assert (v2.quantity_a_per_item, v2.quantity_b_per_item) == (8, 8)
        assert v2.quantity_total == 16
        # Частичное значение копируется в оба поля; total из NULL → N×2.
        v3 = by_version["v3"]
        assert (v3.quantity_a_per_item, v3.quantity_b_per_item) == (8, 8)
        assert v3.quantity_total == 16
        # Равная пара с расходящимся общим кол-вом → общее приводится к N×2.
        v5 = by_version["v5"]
        assert (v5.quantity_a_per_item, v5.quantity_b_per_item) == (8, 8)
        assert v5.quantity_total == 16
        # Стандартная техкарта не трогается.
        v4 = by_version["v4"]
        assert (v4.quantity_a_per_item, v4.quantity_b_per_item) == (8, 12)
        assert v4.quantity_total == 20
    finally:
        admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin_engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        await admin_engine.dispose()

@pytest.mark.asyncio
async def test_migration_046_replay_of_action_id_roundtrip():
    """#121: replay_of_action_id + индекс; downgrade снимает их чисто."""
    db_name = f"ktm_mig_{uuid.uuid4().hex[:10]}"
    admin_url = _test_db_url().rsplit("/", 1)[0] + "/postgres"
    target_url = _test_db_url().rsplit("/", 1)[0] + f"/{db_name}"

    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    await admin_engine.dispose()

    env = {**os.environ, "DATABASE_URL": target_url}

    async def _columns_and_indexes(engine):
        async with engine.connect() as conn:
            cols = await conn.run_sync(
                lambda c: [col["name"] for col in inspect(c).get_columns("action_journal")]
            )
            idx = await conn.run_sync(
                lambda c: inspect(c).get_indexes("action_journal")
            )
        return cols, {i["name"] for i in idx}

    engine = create_async_engine(target_url)
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
        cols, indexes = await _columns_and_indexes(engine)
        assert "replay_of_action_id" in cols
        assert "ix_action_journal_replay_of_action_id" in indexes

        # downgrade до 045: колонки и индекс быть не должно.
        result = subprocess.run(
            ["alembic", "downgrade", "045_hard_purge_status_index"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        cols, indexes = await _columns_and_indexes(engine)
        assert "replay_of_action_id" not in cols
        assert "ix_action_journal_replay_of_action_id" not in indexes

        # повторный upgrade: колонка и индекс возвращаются.
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        cols, indexes = await _columns_and_indexes(engine)
        assert "replay_of_action_id" in cols
        assert "ix_action_journal_replay_of_action_id" in indexes
    finally:
        await engine.dispose()
        admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin_engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        await admin_engine.dispose()
