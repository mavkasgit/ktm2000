"""Миграция 089: ``ALS-1290 → ALS1290`` в ``sku`` и в массиве эквивалентов.

Канон серии ALS — без дефиса (#474). Дефис между буквой и цифрой остаётся
допустимым *написанием* при сопоставлении (``sku_loose``), но не формой
хранения. Миграция 083 разворачивала это направление и отменяется осознанно;
исторические таблицы (``plan_positions.source_sku``/``output_sku``,
``stock_import_rows``, ``audit_logs``) — снимок источника и не переписываются.

Проверяются границы самой миграции:

* дефисный ``sku`` переименовывается, слитный — уже канон и не меняется;
* дефисный элемент ``aliases`` нормализуется, порядок элементов сохраняется;
* соседний элемент с запятой внутри (``Ш-15,6_8,8``) не трогается — массив
  разворачивается по элементам, а не по разделителю;
* ``ALS-917``/``ALS917`` внутри одного массива схлопываются в один элемент;
* повтор не-ALS алиаса (``["481", "481"]``) сохраняется: дедуп касается только
  целевой ALS-формы;
* ``downgrade`` возвращает дефис всем каноническим ALS, а не только
  переименованным этой миграцией: журнала переименований нет (B3);
* дефис между цифрами (``12-34``) и нижний регистр не трогаются;
* столкновение с уже существующим ``ALS1103`` — падение с внятным сообщением,
  а не молчаливый пропуск: слияние двух строк — решение про данные, которого
  у миграции нет;
* повторный проход ничего не меняет, ``downgrade`` симметричен.

База — одноразовая ``ktm_mig_*`` через ``tests/helpers/mig_db.py``, как у 083.
"""
from __future__ import annotations

import asyncio
import importlib.util
import subprocess
from pathlib import Path

import asyncpg
import pytest

from tests.helpers.mig_db import (
    BACKEND_DIR,
    alembic_command,
    alembic_env,
    create_migration_db,
    drop_migration_db,
    migration_db_reachable,
    run_alembic,
)

#: Версия непосредственно перед проверяемой миграцией.
REVISION_BEFORE = "088_product_1c_skipped"

#: Дефисная форма в ``sku`` + дефисные элементы в ``aliases`` + исключения.
SEED_ROWS: list[tuple[str, list[str]]] = [
    ("ALS-1290", []),
    ("ALS1103", []),
    ("335", ["ALS-917"]),
    ("ПТ40", ["ЮП-3035", "ALS-1103"]),
    ("ЮП-048", ["Ш-15,6_8,8", "ALS-915"]),
    ("ЮП-049", ["ALS-917", "ALS917"]),
    ("als-917", []),
    # Повтор не-ALS алиаса — не ALS-дубль: миграция обязана сохранить оба.
    ("ЮП-2974", ["481", "481"]),
    ("12-34", ["12-34", "ALS-916"]),
]

EXPECTED_AFTER_UPGRADE: dict[str, list[str]] = {
    "ALS1290": [],
    # Уже канон: миграция его не трогает и столкновением не считает.
    "ALS1103": [],
    "335": ["ALS917"],
    "ПТ40": ["ЮП-3035", "ALS1103"],
    "ЮП-048": ["Ш-15,6_8,8", "ALS915"],
    "ЮП-049": ["ALS917"],
    "als-917": [],
    # Не-ALS повтор остаётся повтором: дедуп касается только целевой формы.
    "ЮП-2974": ["481", "481"],
    "12-34": ["12-34", "ALS916"],
}

EXPECTED_AFTER_ROLLBACK: dict[str, list[str]] = {
    # B3: downgrade возвращает дефисную форму ВСЕМ каноническим ALS, включая
    # тот ALS, что существовал до upgrade (upgrade его не переименовывал).
    # Журнала переименований нет, поэтому провенанс неотличим; тест фиксирует
    # это поведение, а не побайтовый возврат к посеву.
    "ALS-1290": [],
    "ALS-1103": [],
    "335": ["ALS-917"],
    "ПТ40": ["ЮП-3035", "ALS-1103"],
    "ЮП-048": ["Ш-15,6_8,8", "ALS-915"],
    # Схлопнутый дубль обратно не разворачивается: идемпотентность важнее
    # побайтового возврата к посеву.
    "ЮП-049": ["ALS-917"],
    "als-917": [],
    "ЮП-2974": ["481", "481"],
    "12-34": ["12-34", "ALS-916"],
}


pytestmark = pytest.mark.skipif(
    not migration_db_reachable(),
    reason="PostgreSQL server not reachable for migration test",
)


def _asyncpg_dsn(target_url: str) -> str:
    return target_url.replace("postgresql+asyncpg://", "postgresql://")


async def _seed(conn: asyncpg.Connection, rows: list[tuple[str, list[str]]]) -> None:
    for sku, aliases in rows:
        await conn.execute(
            """
            INSERT INTO products (sku, name, type, aliases)
            VALUES ($1, $2, 'finished_good', $3::varchar[])
            """,
            sku,
            f"Миграция 089: {sku}",
            aliases,
        )


async def _state(
    conn: asyncpg.Connection, skus: list[str] | None = None
) -> dict[str, list[str]]:
    """Состояние ``products``: всё или только перечисленные SKU.

    ``upgrade head`` тянет миграции после 089, а они могут добавлять свои
    артикулы (090 заводит ``1212``). Проверка 089 смотрит только свои строки,
    иначе чужая data-миграция роняет тест.
    """
    if skus is None:
        rows = await conn.fetch("SELECT sku, aliases FROM products ORDER BY sku")
    else:
        rows = await conn.fetch(
            "SELECT sku, aliases FROM products WHERE sku = ANY($1::varchar[]) ORDER BY sku",
            skus,
        )
    return {row["sku"]: list(row["aliases"] or []) for row in rows}


def _migration_sql() -> tuple[str, str]:
    """SQL-константы самой миграции — для проверки повторного прохода."""
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "089_als_sku_without_dash.py"
    )
    spec = importlib.util.spec_from_file_location("migration_089", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._UPDATE_SKU, module._UPDATE_ALIASES


async def _connect(target_url: str) -> asyncpg.Connection:
    return await asyncpg.connect(_asyncpg_dsn(target_url))


@pytest.mark.asyncio
async def test_migration_089_moves_als_sku_to_canonical_spelling(tmp_path: Path) -> None:
    db_name, target_url = await create_migration_db()
    env = alembic_env(target_url, tmp_path)
    conn: asyncpg.Connection | None = None
    try:
        run_alembic(("upgrade", REVISION_BEFORE), env)
        conn = await _connect(target_url)
        try:
            await _seed(conn, SEED_ROWS)
        finally:
            await conn.close()
            conn = None

        run_alembic(("upgrade", "head"), env)

        conn = await _connect(target_url)
        try:
            assert await _state(conn, list(EXPECTED_AFTER_UPGRADE)) == EXPECTED_AFTER_UPGRADE

            # Повторный проход теми же запросами: состояние не меняется.
            update_sku, update_aliases = _migration_sql()
            await conn.execute(update_sku)
            await conn.execute(update_aliases)
            assert await _state(conn, list(EXPECTED_AFTER_UPGRADE)) == EXPECTED_AFTER_UPGRADE
        finally:
            await conn.close()
            conn = None

        run_alembic(("downgrade", REVISION_BEFORE), env)

        conn = await _connect(target_url)
        try:
            assert await _state(conn, list(EXPECTED_AFTER_ROLLBACK)) == EXPECTED_AFTER_ROLLBACK
        finally:
            await conn.close()
            conn = None
    finally:
        if conn is not None:
            await conn.close()
        await drop_migration_db(db_name)


@pytest.mark.asyncio
async def test_migration_089_fails_loudly_on_target_collision(tmp_path: Path) -> None:
    """``ALS-1103`` и ``ALS1103`` одновременно — не молчаливый пропуск."""
    db_name, target_url = await create_migration_db()
    env = alembic_env(target_url, tmp_path)
    conn: asyncpg.Connection | None = None
    try:
        run_alembic(("upgrade", REVISION_BEFORE), env)
        conn = await _connect(target_url)
        try:
            await _seed(conn, [("ALS-1103", []), ("ALS1103", [])])
        finally:
            await conn.close()
            conn = None

        result = await asyncio.to_thread(
            subprocess.run,
            alembic_command("upgrade", "head"),
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode != 0, "коллизия обязана ронять миграцию"
        output = f"{result.stderr}\n{result.stdout}"
        assert "ALS-1103" in output and "ALS1103" in output, output
        assert "занят" in output, output

        # База осталась в дефисном состоянии — данные не тронуты наполовину.
        conn = await _connect(target_url)
        try:
            assert await _state(conn) == {"ALS-1103": [], "ALS1103": []}
        finally:
            await conn.close()
            conn = None
    finally:
        if conn is not None:
            await conn.close()
        await drop_migration_db(db_name)
