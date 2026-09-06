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
from app.services.hanger_quantity_calc import (
    HangerConfigError,
    compute_hanger_quantity,
)
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
async def test_migration_054_product_pairs_and_flag_drop():
    """#146 (ADR-0023): таблица product_pairs, флаг is_paired_profile дропнут (поверх 053).

    Миграция — чистый лист: данных из парных техкарт нет. Проверяем схему
    после upgrade head: колонки is_paired_profile на products нет, в
    product_pairs работают канонический порядок и уникальность неупорядоченной
    пары, ручная N по умолчанию — пустой словарь.
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
        async with engine.begin() as conn:
            columns = await conn.run_sync(
                lambda sync_conn: {
                    c["name"]
                    for c in inspect(sync_conn).get_columns("products")
                }
            )
            assert "is_paired_profile" not in columns

            a_id, b_id = (
                await conn.execute(
                    text(
                        "INSERT INTO products (sku, name, type, unit, is_active) "
                        "VALUES ('PAIR-MIG-A', 'A', 'component', 'pcs', true), "
                        "('PAIR-MIG-B', 'B', 'component', 'pcs', true) "
                        "RETURNING id"
                    )
                )
            ).scalars().all()
            pair_id = (
                await conn.execute(
                    text(
                        "INSERT INTO product_pairs (product_a_id, product_b_id) "
                        "VALUES (:a, :b) RETURNING id"
                    ),
                    {"a": min(a_id, b_id), "b": max(a_id, b_id)},
                )
            ).scalar_one()

            row = (
                await conn.execute(
                    text("SELECT quantity_per_hanger FROM product_pairs WHERE id = :id"),
                    {"id": pair_id},
                )
            ).one()
            assert row.quantity_per_hanger == {}

        # Обратный (не канонический) порядок и дубликат отклоняются схемой —
        # каждый в своей транзакции: после IntegrityError транзакция прервана.
        from sqlalchemy.exc import IntegrityError

        for bad_params in (
            {"a": max(a_id, b_id), "b": min(a_id, b_id)},
            {"a": min(a_id, b_id), "b": max(a_id, b_id)},
        ):
            async with engine.begin() as conn:
                with pytest.raises(IntegrityError):
                    await conn.execute(
                        text(
                            "INSERT INTO product_pairs (product_a_id, product_b_id) "
                            "VALUES (:a, :b)"
                        ),
                        bad_params,
                    )
        await engine.dispose()
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


@pytest.mark.asyncio
async def test_migration_048_product_hanger_mode_backfill():
    """#129: backfill hanger_mode — досчёт словаря и границы формулы движка.

    Покрывает: (1) SQL-формула 048 совпадает с ``compute_hanger_quantity``
    на границах — периметр×длина/1e6 > 13 м² → auto=0; mount_width+20 == 1450
    ровно → расчёт возможен (by_size=2); mount_width+20 > 1450 → auto=null
    (движок бросает HangerConfigError); (2) дыра backfill: артикул с
    заполненными auto-полями, но БЕЗ per-length dict, получает словарь из
    product_lengths (auto по формуле, manual=null); legacy-числовой скаляр
    сохраняется в manual первой длины по возрастанию (семантика 032);
    (3) bare-``{auto, manual}``-словарь legacy-скаляра шагом 1 переносится
    как есть (не-числовые ключи не трогаются); (4) повторный запуск 048
    идемпотентен — шаги защищены отсутствием ключа ``hanger_mode``.
    """
    db_name = f"ktm_mig_{uuid.uuid4().hex[:10]}"
    admin_url = _test_db_url().rsplit("/", 1)[0] + "/postgres"
    target_url = _test_db_url().rsplit("/", 1)[0] + f"/{db_name}"

    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    await admin_engine.dispose()

    env = {**os.environ, "DATABASE_URL": target_url}

    def _expected_auto(perimeter_mm: float, mount_width_mm: float, length_mm: float):
        """Ожидаемый auto по независимому движку (#62): total или None.

        Несовместимые габариты (mount_width+20 > 1450) движок отвергает
        исключением — миграция в этом случае оставляет auto=null.
        """
        try:
            calc = compute_hanger_quantity(
                perimeter_mm=perimeter_mm,
                mount_width_mm=mount_width_mm,
                length_mm=length_mm,
            )
        except HangerConfigError:
            return None
        return calc.total if calc.is_calculable else None

    async def _fetch_attrs(sku_prefix: str) -> dict:
        engine = create_async_engine(target_url)
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT sku, attributes FROM products "
                            "WHERE sku LIKE :prefix ORDER BY sku"
                        ),
                        {"prefix": sku_prefix},
                    )
                ).all()
            return {r.sku: r.attributes for r in rows}
        finally:
            await engine.dispose()

    try:
        # 1. До 048 (047) — ключа hanger_mode ещё нет в цепочке.
        result = subprocess.run(
            ["alembic", "upgrade", "047_transfer_status_amended"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout

        # 2. Фикстуры: границы формулы + варианты отсутствия per-length dict.
        engine = create_async_engine(target_url)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO products (sku, name, type, unit, is_active, attributes) VALUES "
                    # Граница площади: 1000×13500/1e6 = 13.5 м² > 13 → by_area = 0.
                    "('MIG048-AREA-OVER', 'A', 'component', 'pcs', true, "
                    "'{\"perimeter_mm\": 1000, \"mount_width_mm\": 50}'::jsonb), "
                    # Граница размера: 1430+20 == 1450 ровно → by_size = 2, расчёт возможен.
                    "('MIG048-SIZE-BOUNDARY', 'S', 'component', 'pcs', true, "
                    "'{\"perimeter_mm\": 20, \"mount_width_mm\": 1430}'::jsonb), "
                    # Дыра backfill: поля заполнены, quantity_per_hanger отсутствует.
                    "('MIG048-NO-DICT', 'N', 'component', 'pcs', true, "
                    "'{\"perimeter_mm\": 60, \"mount_width_mm\": 15}'::jsonb), "
                    # Несовместимый габарит: 1500+20 > 1450 → auto = null.
                    "('MIG048-INCOMPATIBLE', 'I', 'component', 'pcs', true, "
                    "'{\"perimeter_mm\": 60, \"mount_width_mm\": 1500}'::jsonb), "
                    # Legacy-скаляр числом: сохранить в manual первой длины (032).
                    "('MIG048-SCALAR', 'L', 'component', 'pcs', true, "
                    "'{\"perimeter_mm\": 60, \"mount_width_mm\": 15, "
                    "\"quantity_per_hanger\": 71}'::jsonb), "
                    # Bare-{auto,manual} legacy-скаляра — шагом 1 не трогается.
                    "('MIG048-BARE', 'B', 'component', 'pcs', true, "
                    "'{\"perimeter_mm\": 60, \"mount_width_mm\": 15, "
                    "\"quantity_per_hanger\": {\"auto\": null, \"manual\": 71}}'::jsonb), "
                    # Неполные поля → manual, без словаря.
                    "('MIG048-MANUAL-PARTIAL', 'P', 'component', 'pcs', true, "
                    "'{\"perimeter_mm\": 60}'::jsonb)"
                )
            )
            # NO-DICT и SCALAR — две длины вставкой не по возрастанию;
            # остальным авто-кейсам — по одной длине; MANUAL-PARTIAL — ни одной.
            await conn.execute(
                text(
                    "INSERT INTO product_lengths (product_id, length_mm) "
                    "SELECT p.id, l.length_mm FROM products p "
                    "JOIN (VALUES ('MIG048-NO-DICT', 3500.0::float8), "
                    "      ('MIG048-NO-DICT', 2800.0), "
                    "      ('MIG048-SCALAR', 3500.0), "
                    "      ('MIG048-SCALAR', 2800.0), "
                    "      ('MIG048-AREA-OVER', 13500.0), "
                    "      ('MIG048-SIZE-BOUNDARY', 2000.0), "
                    "      ('MIG048-INCOMPATIBLE', 3000.0), "
                    "      ('MIG048-BARE', 2800.0)) AS l(sku, length_mm) "
                    "ON l.sku = p.sku"
                )
            )
        await engine.dispose()

        # 3. Upgrade до head → 048 проставляет режимы и досчитывает словари.
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout

        attrs_by_sku = await _fetch_attrs("MIG048-%")
        assert len(attrs_by_sku) == 7

        # Граница площади: 13.5 м² > 13 → by_area = 0, итог 0 (SQL и движок).
        area_over = attrs_by_sku["MIG048-AREA-OVER"]
        assert area_over["hanger_mode"] == "auto"
        assert _expected_auto(1000, 50, 13500) == 0
        assert area_over["quantity_per_hanger"]["13500"] == {"auto": 0, "manual": None}

        # Граница размера: 1430+20 == 1450 ровно → by_size = 2, лимитер size.
        size_boundary = attrs_by_sku["MIG048-SIZE-BOUNDARY"]
        assert size_boundary["hanger_mode"] == "auto"
        calc = compute_hanger_quantity(perimeter_mm=20, mount_width_mm=1430, length_mm=2000)
        assert calc.is_calculable and calc.limiter == "size" and calc.total == 2
        assert size_boundary["quantity_per_hanger"]["2000"] == {"auto": 2, "manual": None}

        # Дыра backfill: dict создан из product_lengths, auto по движку,
        # ручных значений не было → manual=null у обеих длин.
        no_dict = attrs_by_sku["MIG048-NO-DICT"]
        assert no_dict["hanger_mode"] == "auto"
        qph = no_dict["quantity_per_hanger"]
        assert set(qph) == {"2800", "3500"}
        for length in (2800, 3500):
            assert qph[str(length)] == {
                "auto": _expected_auto(60, 15, length),
                "manual": None,
            }

        # Несовместимый габарит: движок отказ, миграция ставит auto=null.
        incompatible = attrs_by_sku["MIG048-INCOMPATIBLE"]
        assert incompatible["hanger_mode"] == "auto"
        with pytest.raises(HangerConfigError):
            compute_hanger_quantity(perimeter_mm=60, mount_width_mm=1500, length_mm=3000)
        assert incompatible["quantity_per_hanger"]["3000"] == {"auto": None, "manual": None}

        # Legacy-скаляр числом: dict из длин, скаляр 71 → manual первой
        # длины по возрастанию (2800, семантика 032), остальные manual=null.
        scalar = attrs_by_sku["MIG048-SCALAR"]
        assert scalar["hanger_mode"] == "auto"
        assert scalar["quantity_per_hanger"]["2800"] == {
            "auto": _expected_auto(60, 15, 2800),
            "manual": 71,
        }
        assert scalar["quantity_per_hanger"]["3500"] == {
            "auto": _expected_auto(60, 15, 3500),
            "manual": None,
        }

        # Bare-{auto,manual} legacy-скаляра: перенесён как есть, режим auto.
        bare = attrs_by_sku["MIG048-BARE"]
        assert bare["hanger_mode"] == "auto"
        assert bare["quantity_per_hanger"] == {"auto": None, "manual": 71}

        # Неполные поля → manual; словарь не создаётся.
        manual_partial = attrs_by_sku["MIG048-MANUAL-PARTIAL"]
        assert manual_partial["hanger_mode"] == "manual"
        assert "quantity_per_hanger" not in manual_partial

        # 4. Идемпотентность: повторный запуск 048 ничего не меняет
        # (шаги защищены отсутствием ключа hanger_mode).
        snapshot_before = attrs_by_sku
        result = subprocess.run(
            ["alembic", "stamp", "047_transfer_status_amended"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout

        attrs_after_rerun = await _fetch_attrs("MIG048-%")
        assert attrs_after_rerun == snapshot_before
    finally:
        admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin_engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        await admin_engine.dispose()


@pytest.mark.asyncio
async def test_migration_053_product_composition_schema():
    """#147: таблица состава ГП — констрейнты и триггер-инварианты.

    Покрывает: (1) таблица product_compositions с CHECK quantity > 0 и
    UNIQUE (product_id, component_product_id); (2) BEFORE-триггер
    fn_check_product_composition_invariants: компонент — только сырьё
    (type=component), самоссылка запрещена, третья строка владельца
    (INSERT) и перенос строки владельцу, у которого уже два компонента
    (UPDATE product_id), отклоняются; (3) unique отвергает дубликат
    компонента; (4) CHECK отвергает quantity = 0; (5) FK product_id
    каскадит удаление владельца; (6) повторный прогон 053 безопасен.
    """
    db_name = f"ktm_mig_{uuid.uuid4().hex[:10]}"
    admin_url = _test_db_url().rsplit("/", 1)[0] + "/postgres"
    target_url = _test_db_url().rsplit("/", 1)[0] + f"/{db_name}"

    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    await admin_engine.dispose()

    env = {**os.environ, "DATABASE_URL": target_url}

    def _run(*args: str) -> None:
        result = subprocess.run(
            ["alembic", *args],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout

    engine = create_async_engine(target_url)
    try:
        _run("upgrade", "head")

        # Фикстуры: два владельца ГП + три компонента.
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO products (sku, name, type, unit, is_active) VALUES "
                "('MIG053-FG', 'Готовый профиль', 'finished_good', 'pcs', true), "
                "('MIG053-FG2', 'Второй профиль', 'finished_good', 'pcs', true), "
                "('MIG053-C1', 'Сырьё 1', 'component', 'm', true), "
                "('MIG053-C2', 'Сырьё 2', 'component', 'pcs', true), "
                "('MIG053-C3', 'Сырьё 3', 'component', 'pcs', true)"
            ))

        async with engine.connect() as conn:
            rows = (await conn.execute(text(
                "SELECT sku, id FROM products WHERE sku LIKE 'MIG053-%'"
            ))).all()
        ids = {r.sku: r.id for r in rows}
        fg, fg2 = ids["MIG053-FG"], ids["MIG053-FG2"]
        c1, c2, c3 = ids["MIG053-C1"], ids["MIG053-C2"], ids["MIG053-C3"]

        async def _exec(sql: str, **params):
            async with engine.begin() as conn:
                await conn.execute(text(sql), params)

        # Два компонента на владельца — разрешено.
        await _exec(
            "INSERT INTO product_compositions (product_id, component_product_id, quantity) "
            "VALUES (:pid, :cid, 2), (:pid, :cid2, 1)",
            pid=fg, cid=c1, cid2=c2,
        )

        # Компонент — только сырьё: finished_good компонентом быть не может.
        with pytest.raises(Exception, match="type=component"):
            await _exec(
                "INSERT INTO product_compositions (product_id, component_product_id, quantity) "
                "VALUES (:pid, :cid, 1)",
                pid=fg2, cid=fg,
            )

        # Самоссылка запрещена.
        with pytest.raises(Exception, match="own component"):
            await _exec(
                "INSERT INTO product_compositions (product_id, component_product_id, quantity) "
                "VALUES (:pid, :cid, 1)",
                pid=fg, cid=fg,
            )

        # Третий компонент — триггер check_violation.
        with pytest.raises(Exception, match="at most 2 components"):
            await _exec(
                "INSERT INTO product_compositions (product_id, component_product_id, quantity) "
                "VALUES (:pid, :cid, 1)",
                pid=fg, cid=c3,
            )

        # UPDATE product_id не переводит строку владельцу, у которого уже 2.
        await _exec(
            "INSERT INTO product_compositions (product_id, component_product_id, quantity) "
            "VALUES (:pid, :cid, 1)",
            pid=fg2, cid=c3,
        )
        with pytest.raises(Exception, match="at most 2 components"):
            await _exec(
                "UPDATE product_compositions SET product_id = :target "
                "WHERE product_id = :src AND component_product_id = :cid",
                target=fg, src=fg2, cid=c3,
            )

        # Дубликат компонента в составе одного владельца — unique
        # (у fg2 один компонент, триггер пропускает, unique отклоняет).
        with pytest.raises(Exception, match="uq_product_compositions_component"):
            await _exec(
                "INSERT INTO product_compositions (product_id, component_product_id, quantity) "
                "VALUES (:pid, :cid, 1)",
                pid=fg2, cid=c3,
            )

        # quantity = 0 — CHECK.
        with pytest.raises(Exception, match="ck_product_compositions_quantity_positive"):
            await _exec(
                "INSERT INTO product_compositions (product_id, component_product_id, quantity) "
                "VALUES (:pid, :cid, 0)",
                pid=c1, cid=c3,
            )

        # Каскад: удаление владельца уносит его строки состава.
        await _exec("DELETE FROM products WHERE id = :pid", pid=fg)
        async with engine.connect() as conn:
            left = (await conn.execute(text(
                "SELECT count(*) FROM product_compositions WHERE product_id = :pid"
            ), {"pid": fg})).scalar()
        assert left == 0

        # 6. Повторный прогон 053 безопасен (конвенция 052, проверка как в 048):
        # stamp назад + upgrade head не спотыкается о create_table.
        _run("stamp", "052_idempotency_backstops")
        _run("upgrade", "head")
    finally:
        await engine.dispose()
        admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin_engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        await admin_engine.dispose()
