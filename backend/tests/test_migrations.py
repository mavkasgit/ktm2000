"""Проверка что Alembic-цепочка поднимает схему с нуля."""

from __future__ import annotations

import json
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

    Миграция — чистый лист: парных данных прошлой модели нет. Проверяем схему
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


@pytest.mark.asyncio
async def test_migration_058_product_pair_quantity_norms():
    """#177 (Q13): нормы парных профилей из файла справочника → product_pairs.

    Миграция — разовый перенос значений, которых в БД не было (импорт формат
    «ЮП-2616, 30» не читает, #177 Q1), поэтому проверяется поведение в БД:
    (1) все пять пар тикета получают ``{"2750": {"manual": N}}``, и ``manual``
    в JSONB — ЧИСЛО, а не строка (bind-параметр int; строка не прошла бы
    сравнение с int); пары связываются по каноническому порядку LEAST/GREATEST,
    а не по порядку id: ЮП-3158 получает id меньше ЮП-2616, поэтому у пары
    ЮП-2616↔ЮП-3158 порядок колонок обратен порядку SKU в списке норм;
    (2) 2750 мм обязан быть у ОБОИХ артикулов пары: у одного длины нет вовсе
    (ЮП-2878), у другого есть только другая длина (ЮП-2604: 3000) → норма не
    пишется; покрыты обе стороны EXISTS-проверки — в паре ЮП-2604↔ЮП-2616
    длины нет у первого SKU списка норм, в паре ЮП-2695↔ЮП-2878 — у второго;
    (3) пара с уже проставленной нормой (99) не перезаписывается, а повторный
    прогон 058 (stamp назад + upgrade head) ничего не меняет;
    (4) пары ЮП-3452↔ЮП-3453 нет в БД вовсе (SKU не заведены) — upgrade не
    падает и остальные пары обрабатывает;
    (5) downgrade очищает словарь ровно тех пар, где стоит записанная
    миграцией норма; чужая норма 99 и пара вне миграции (7) остаются.
    """
    db_name = f"ktm_mig_{uuid.uuid4().hex[:10]}"
    admin_url = _test_db_url().rsplit("/", 1)[0] + "/postgres"
    target_url = _test_db_url().rsplit("/", 1)[0] + f"/{db_name}"

    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    await admin_engine.dispose()

    env = {**os.environ, "DATABASE_URL": target_url}

    # (SKU A, SKU B, ручная N на 2750 мм) — значения из файла справочника (#177).
    norms: list[tuple[str, str, int]] = [
        ("ЮП-2604", "ЮП-2616", 30),
        ("ЮП-2616", "ЮП-3158", 32),
        ("ЮП-2616", "ЮП-3098", 35),
        ("ЮП-2695", "ЮП-2878", 24),
        ("ЮП-3452", "ЮП-3453", 26),
    ]
    foreign_pair = ("MIG058-OTHER-A", "MIG058-OTHER-B")
    foreign_norm = {"2750": {"manual": 7}}
    # Порядок вставки задаёт id. ЮП-3158 получает id меньше ЮП-2616: у пары
    # ЮП-2616↔ЮП-3158 канонический порядок колонок обратен порядку SKU в списке
    # норм — такая пара связывается только через LEAST/GREATEST.
    skus = [
        "ЮП-3158", "ЮП-2616", "ЮП-2604", "ЮП-3098", "ЮП-2695",
        "ЮП-2878", "ЮП-3452", "ЮП-3453", foreign_pair[0], foreign_pair[1],
    ]

    def _key(sku_a: str, sku_b: str) -> tuple[str, str]:
        """Ключ пары, не зависящий от того, кто из артикулов product_a."""
        return tuple(sorted((sku_a, sku_b)))

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

    async def _pair_row(sku_a: str, sku_b: str):
        """Норма пары по двум её SKU (порядок SKU не важен), или None."""
        async with engine.connect() as conn:
            return (
                await conn.execute(
                    text(
                        "SELECT pp.quantity_per_hanger AS qph "
                        "FROM product_pairs pp "
                        "JOIN products a ON a.id = pp.product_a_id "
                        "JOIN products b ON b.id = pp.product_b_id "
                        "WHERE (a.sku, b.sku) IN ((:a, :b), (:b, :a))"
                    ),
                    {"a": sku_a, "b": sku_b},
                )
            ).one_or_none()

    async def _norms_snapshot() -> dict:
        """Все нормы пар в БД: {пара SKU: quantity_per_hanger}."""
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT a.sku AS sku_a, b.sku AS sku_b, "
                        "pp.quantity_per_hanger AS qph "
                        "FROM product_pairs pp "
                        "JOIN products a ON a.id = pp.product_a_id "
                        "JOIN products b ON b.id = pp.product_b_id"
                    )
                )
            ).all()
        return {_key(r.sku_a, r.sku_b): r.qph for r in rows}

    async def _set_norm(sku_a: str, sku_b: str, norm: dict) -> None:
        """Проставить паре норму вручную (фикстура «норма уже есть»)."""
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE product_pairs pp SET quantity_per_hanger = CAST(:norm AS jsonb) "
                    "FROM products a, products b "
                    "WHERE a.sku = :a AND b.sku = :b "
                    "  AND pp.product_a_id = LEAST(a.id, b.id) "
                    "  AND pp.product_b_id = GREATEST(a.id, b.id)"
                ),
                {"a": sku_a, "b": sku_b, "norm": json.dumps(norm)},
            )
        assert result.rowcount == 1, f"фикстура: пара {sku_a}↔{sku_b} не найдена"

    try:
        # 1. Состояние до 058: пары есть, норм нет (переносить их было неоткуда).
        _run("upgrade", "057_plan_change_set_applied_at")

        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO products (sku, name, type, unit, is_active) VALUES "
                + ", ".join(f"('{sku}', '{sku}', 'component', 'pcs', true)" for sku in skus)
            ))
            # 2750 мм у обоих артикулов каждой пары — пересечение длин A∩B.
            await conn.execute(text(
                "INSERT INTO product_lengths (product_id, length_mm) "
                "SELECT p.id, 2750.0 FROM products p "
                "WHERE p.sku = ANY (ARRAY["
                + ", ".join(f"'{sku}'" for sku in skus) + "])"
            ))
            await conn.execute(text(
                "INSERT INTO product_pairs (product_a_id, product_b_id) "
                "SELECT LEAST(a.id, b.id), GREATEST(a.id, b.id) "
                "FROM (VALUES "
                + ", ".join(f"('{a}', '{b}')" for a, b, _manual in norms) + ") AS v(sku_a, sku_b) "
                "JOIN products a ON a.sku = v.sku_a "
                "JOIN products b ON b.sku = v.sku_b"
            ))
            # Пара вне миграции: чужая норма — её не должен трогать ни upgrade, ни downgrade.
            await conn.execute(text(
                "INSERT INTO product_pairs (product_a_id, product_b_id, quantity_per_hanger) "
                "SELECT LEAST(a.id, b.id), GREATEST(a.id, b.id), '{\"2750\": {\"manual\": 7}}'::jsonb "
                "FROM products a, products b WHERE a.sku = :a AND b.sku = :b"
            ), {"a": foreign_pair[0], "b": foreign_pair[1]})

        # 2. upgrade head → 058 переносит нормы файла в БД.
        _run("upgrade", "head")

        for sku_a, sku_b, manual in norms:
            row = await _pair_row(sku_a, sku_b)
            assert row is not None, f"{sku_a}↔{sku_b}: пара не найдена"
            # manual — число: строка «30» в JSONB декодируется как str и здесь не равна int.
            assert row.qph == {"2750": {"manual": manual}}, f"{sku_a}↔{sku_b}"

        assert (await _pair_row(*foreign_pair)).qph == foreign_norm

        # 3. Пара с уже проставленной нормой + повторный прогон 058 (stamp назад).
        await _set_norm("ЮП-2616", "ЮП-3098", {"2750": {"manual": 99}})
        expected_filled = {_key(a, b): {"2750": {"manual": n}} for a, b, n in norms}
        expected_filled[_key("ЮП-2616", "ЮП-3098")] = {"2750": {"manual": 99}}
        expected_filled[_key(*foreign_pair)] = foreign_norm

        _run("stamp", "057_plan_change_set_applied_at")
        _run("upgrade", "head")
        # Повторный прогон: значения те же, 99 не перезаписана.
        assert await _norms_snapshot() == expected_filled

        # 4. downgrade чистит ровно записанные миграцией нормы: 99 и 7 остаются.
        _run("downgrade", "057_plan_change_set_applied_at")

        expected_cleared = {_key(a, b): {} for a, b, _n in norms}
        expected_cleared[_key("ЮП-2616", "ЮП-3098")] = {"2750": {"manual": 99}}
        expected_cleared[_key(*foreign_pair)] = foreign_norm
        assert await _norms_snapshot() == expected_cleared

        # 5. Грязные кейсы на 057 (после downgrade все нормы миграции снова пусты).
        async with engine.begin() as conn:
            # (а) длина есть, но не 2750: EXISTS по product_lengths не срабатывает.
            result = await conn.execute(text(
                "UPDATE product_lengths l SET length_mm = 3000.0 FROM products p "
                "WHERE p.id = l.product_id AND p.sku = :sku AND l.length_mm = 2750.0"
            ), {"sku": "ЮП-2604"})
            assert result.rowcount == 1, "фикстура: у ЮП-2604 не нашлась длина 2750"
            # (б) строк длин нет вовсе у второго артикула пары.
            result = await conn.execute(text(
                "DELETE FROM product_lengths l USING products p "
                "WHERE p.id = l.product_id AND p.sku = :sku"
            ), {"sku": "ЮП-2878"})
            assert result.rowcount == 1, "фикстура: у ЮП-2878 не нашлась длина 2750"
            # (в) пары нет в БД вовсе — её SKU не заведены.
            result = await conn.execute(text(
                "DELETE FROM product_pairs pp USING products a, products b "
                "WHERE pp.product_a_id = LEAST(a.id, b.id) "
                "  AND pp.product_b_id = GREATEST(a.id, b.id) "
                "  AND (a.sku, b.sku) IN (('ЮП-3452', 'ЮП-3453'), ('ЮП-3453', 'ЮП-3452'))"
            ))
            assert result.rowcount == 1, "фикстура: пара ЮП-3452↔ЮП-3453 не нашлась"
            await conn.execute(text(
                "DELETE FROM product_lengths l USING products p "
                "WHERE p.id = l.product_id AND p.sku IN ('ЮП-3452', 'ЮП-3453')"
            ))
            result = await conn.execute(text(
                "DELETE FROM products WHERE sku IN ('ЮП-3452', 'ЮП-3453')"
            ))
            assert result.rowcount == 2, "фикстура: артикулы ЮП-3452/ЮП-3453 не удалились"

        # upgrade head не падает на отсутствующих SKU и пишет только пару, у
        # которой 2750 есть у обоих артикулов.
        _run("upgrade", "head")

        expected_dirty = {
            _key("ЮП-2616", "ЮП-3158"): {"2750": {"manual": 32}},
            _key("ЮП-2604", "ЮП-2616"): {},
            _key("ЮП-2695", "ЮП-2878"): {},
            _key("ЮП-2616", "ЮП-3098"): {"2750": {"manual": 99}},
            _key(*foreign_pair): foreign_norm,
        }
        assert await _norms_snapshot() == expected_dirty
    finally:
        await engine.dispose()
        admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin_engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        await admin_engine.dispose()
