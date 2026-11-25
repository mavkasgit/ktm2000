"""Миграция #455: ``product_1c_codes`` и поля источника строк импорта.

Проверяет: (1) таблица и колонки ``stock_import_rows.source_code`` /
``source_quantity_m`` есть, ``source_quantity_m`` — NUMERIC(18,4) NULL;
(2) код 1С уникален между артикулами, у одного артикула кодов несколько;
(3) удаление артикула каскадит ``product_1c_codes``, а строка импорта
остаётся историей с ``product_id IS NULL`` и сохранённым кодом;
(4) ``downgrade`` убирает таблицу и колонки, ``upgrade`` возвращает их.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.helpers.mig_db import (
    BACKEND_DIR,
    alembic_command,
    alembic_env,
    create_migration_db,
    drop_migration_db,
    migration_db_reachable,
)

pytestmark = pytest.mark.skipif(
    not migration_db_reachable(),
    reason="PostgreSQL server not reachable for migration test",
)

PREVIOUS_REVISION = "085_section_operation_updated_at"


async def _columns(conn, table: str) -> dict[str, dict]:
    return await conn.run_sync(
        lambda sync_conn: {
            column["name"]: column
            for column in inspect(sync_conn).get_columns(table)
        }
    )


async def _table_names(conn) -> set[str]:
    return await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))


@pytest.mark.asyncio
async def test_migration_086_product_1c_codes_and_import_source_fields(tmp_path: Path):
    db_name, target_url = await create_migration_db()

    env = alembic_env(target_url, tmp_path)

    def _run(*args: str) -> None:
        result = subprocess.run(
            alembic_command(*args),
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

        async with engine.connect() as conn:
            # head уезжает с каждой новой миграцией, поэтому сравнивать его с
            # литералом 086 нельзя: схема ниже — и есть доказательство, что
            # 086 применилась поверх своей предшественницы.
            head = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            assert head not in (None, PREVIOUS_REVISION)
            assert "product_1c_codes" in await _table_names(conn)
            code_columns = await _columns(conn, "product_1c_codes")
            row_columns = await _columns(conn, "stock_import_rows")
            indexes = await conn.run_sync(
                lambda sync_conn: {
                    index["name"]
                    for index in inspect(sync_conn).get_indexes("product_1c_codes")
                }
            )
            uniques = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_unique_constraints(
                    "product_1c_codes"
                )
            )

        assert set(code_columns) == {
            "id",
            "product_id",
            "code",
            "source",
            "created_by",
            "created_at",
        }
        assert code_columns["product_id"]["nullable"] is False
        assert code_columns["code"]["nullable"] is False
        assert code_columns["source"]["nullable"] is False
        assert code_columns["source"]["default"] == "'1c_osv'::character varying"
        assert code_columns["created_by"]["nullable"] is True
        assert code_columns["created_at"]["nullable"] is False
        assert "ix_product_1c_codes_product_id" in indexes
        assert any(
            unique["column_names"] == ["code"] for unique in uniques
        ), uniques

        assert row_columns["source_code"]["nullable"] is True
        assert row_columns["source_quantity_m"]["nullable"] is True
        assert row_columns["source_quantity_m"]["type"].precision == 18
        assert row_columns["source_quantity_m"]["type"].scale == 4

        async with engine.begin() as conn:
            first_id, second_id = (
                await conn.execute(
                    text(
                        "INSERT INTO products (sku, name, type, unit, is_active) VALUES "
                        "('MIG086-A', 'A', 'component', 'pcs', true), "
                        "('MIG086-B', 'B', 'component', 'pcs', true) "
                        "RETURNING id"
                    )
                )
            ).scalars().all()
            await conn.execute(
                text(
                    "INSERT INTO product_1c_codes (product_id, code) VALUES "
                    "(:first, '20933'), (:first, '22069')"
                ),
                {"first": first_id},
            )
            action_id = (
                await conn.execute(
                    text(
                        "INSERT INTO action_journal (action_type) "
                        "VALUES ('import_remainders') RETURNING id"
                    )
                )
            ).scalar_one()
            batch_id = (
                await conn.execute(
                    text(
                        "INSERT INTO stock_import_batches (action_id) "
                        "VALUES (:action_id) RETURNING id"
                    ),
                    {"action_id": action_id},
                )
            ).scalar_one()
            with_source = (
                await conn.execute(
                    text(
                        "INSERT INTO stock_import_rows "
                        "(batch_id, source_row_number, sku, product_id, status, "
                        " source_code, source_quantity_m) "
                        "VALUES (:batch_id, 2, 'MIG086-A', :product_id, 'valid', "
                        "        '20933', 6391.0) RETURNING id"
                    ),
                    {"batch_id": batch_id, "product_id": first_id},
                )
            ).scalar_one()
            without_source = (
                await conn.execute(
                    text(
                        "INSERT INTO stock_import_rows "
                        "(batch_id, source_row_number, sku, status) "
                        "VALUES (:batch_id, 3, 'MIG086-B', 'invalid') RETURNING id"
                    ),
                    {"batch_id": batch_id},
                )
            ).scalar_one()

        # Код 1С глобально уникален: второй артикул с тем же кодом отклонён.
        async with engine.begin() as conn:
            with pytest.raises(IntegrityError):
                await conn.execute(
                    text(
                        "INSERT INTO product_1c_codes (product_id, code) "
                        "VALUES (:product_id, '20933')"
                    ),
                    {"product_id": second_id},
                )

        # Удаление артикула: коды ушли каскадом, история импорта сохранена.
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM products WHERE id = :product_id"),
                {"product_id": first_id},
            )

        async with engine.connect() as conn:
            codes_left = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM product_1c_codes "
                        "WHERE product_id = :product_id"
                    ),
                    {"product_id": first_id},
                )
            ).scalar_one()
            kept = (
                await conn.execute(
                    text(
                        "SELECT product_id, source_code, source_quantity_m "
                        "FROM stock_import_rows WHERE id = :row_id"
                    ),
                    {"row_id": with_source},
                )
            ).one()
            empty = (
                await conn.execute(
                    text(
                        "SELECT source_code, source_quantity_m "
                        "FROM stock_import_rows WHERE id = :row_id"
                    ),
                    {"row_id": without_source},
                )
            ).one()

        assert codes_left == 0
        assert kept.product_id is None
        assert kept.source_code == "20933"
        assert float(kept.source_quantity_m) == 6391.0
        assert empty.source_code is None
        assert empty.source_quantity_m is None

        # downgrade убирает схему #455 целиком.
        _run("downgrade", PREVIOUS_REVISION)

        async with engine.connect() as conn:
            assert "product_1c_codes" not in await _table_names(conn)
            row_columns_after = await _columns(conn, "stock_import_rows")

        assert "source_code" not in row_columns_after
        assert "source_quantity_m" not in row_columns_after

        # Повторный upgrade возвращает таблицу и колонки.
        _run("upgrade", "head")

        async with engine.connect() as conn:
            assert "product_1c_codes" in await _table_names(conn)
            row_columns_again = await _columns(conn, "stock_import_rows")

        assert "source_code" in row_columns_again
        assert "source_quantity_m" in row_columns_again

        # Конвенция 052: повторный прогон поверх уже поднятой схемы безопасен.
        _run("stamp", PREVIOUS_REVISION)
        _run("upgrade", "head")

        async with engine.connect() as conn:
            assert "product_1c_codes" in await _table_names(conn)
            row_columns_rerun = await _columns(conn, "stock_import_rows")

        assert "source_code" in row_columns_rerun
        assert "source_quantity_m" in row_columns_rerun
    finally:
        await engine.dispose()
        await drop_migration_db(db_name)
