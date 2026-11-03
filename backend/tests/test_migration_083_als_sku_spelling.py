"""Миграция 083: ``ALS1290 → ALS-1290`` в ``sku`` и в массиве эквивалентов.

Переименование ALS-артикулов проведено в проде вручную, но написание держится не
только в ``products.sku``: его несут ``products.aliases`` («Эквиваленты»), и на
слитную форму смотрит поиск позиции
``(sku == X) | (aliases @> ARRAY[X])`` (``catalog_import.py:169``) — точное
совпадение строк. Миграция обязана править и то, и другое, иначе эквивалент
перестаёт находиться, а повторный демо-сид заводит второй артикул рядом со
старым.

Отдельные случаи проверки — это границы самой миграции:

* слитный ``sku`` переименовывается;
* слитный элемент ``aliases`` нормализуется, порядок элементов сохраняется;
* нормализация не трогает соседний элемент с запятой внутри (``Ш-15,6_8,8``) —
  массив разворачивается по элементам, а не по разделителю;
* столбение ``ALS917``/``ALS-917`` внутри одного массива схлопывается в один
  элемент, а не плодит дубль эквивалента;
* столкновение с уже существующей дефисной формой пропускается (уникальный
  индекс ``sku``), а не разруливается слиянием;
* нижний регистр не меняется — миграция работает по ``^ALS[0-9]+$``.

База — одноразовая ``ktm_mig_*`` через ``tests/helpers/mig_db.py``, как у 082.
"""
from __future__ import annotations

from pathlib import Path

import asyncpg
import pytest

from tests.helpers.mig_db import (
    alembic_env,
    create_migration_db,
    drop_migration_db,
    migration_db_reachable,
    run_alembic,
)

#: Версия непосредственно перед проверяемой миграцией.
REVISION_BEFORE = "082_plan_position_validation_warnings_backfill"

#: Слитая форма в ``sku`` + слитные элементы в ``aliases`` + коллизии.
SEED_ROWS: list[tuple[str, list[str]]] = [
    ("ALS1290", []),
    ("ALS-1103", []),
    ("ALS1103", []),
    ("335", ["ALS917"]),
    ("ПТ40", ["ЮП-3035", "ALS1103"]),
    ("ЮП-048", ["Ш-15,6_8,8", "ALS915"]),
    ("ЮП-049", ["ALS917", "ALS-917"]),
    ("als917", []),
    ("ЮП-2974", ["481"]),
]

EXPECTED_AFTER_UPGRADE: dict[str, list[str]] = {
    "ALS-1290": [],
    "ALS-1103": [],
    # Коллизия: дефисная форма уже занята → слитный sku остаётся как есть,
    # слияние двух строк — решение про данные, которого у миграции нет.
    "ALS1103": [],
    "335": ["ALS-917"],
    "ПТ40": ["ЮП-3035", "ALS-1103"],
    "ЮП-048": ["Ш-15,6_8,8", "ALS-915"],
    "ЮП-049": ["ALS-917"],
    "als917": [],
    "ЮП-2974": ["481"],
}

EXPECTED_AFTER_ROLLBACK: dict[str, list[str]] = {
    "ALS1290": [],
    # Откат тоже не трогает занятую цель: слитная форма жива, поэтому дефисная
    # строка её не получила и осталась как есть.
    "ALS-1103": [],
    "ALS1103": [],
    "335": ["ALS917"],
    "ПТ40": ["ЮП-3035", "ALS1103"],
    "ЮП-048": ["Ш-15,6_8,8", "ALS915"],
    # Схлопнутый дубль в обратную сторону не разворачивается: откат даёт слитную
    # форму, но вторым элементом она была бы копией первого. Идемпотентность
    # важнее побайтового возврата к посеву.
    "ЮП-049": ["ALS917"],
    "als917": [],
    "ЮП-2974": ["481"],
}


pytestmark = pytest.mark.skipif(
    not migration_db_reachable(),
    reason="PostgreSQL server not reachable for migration test",
)


def _asyncpg_dsn(target_url: str) -> str:
    return target_url.replace("postgresql+asyncpg://", "postgresql://")


async def _seed(conn: asyncpg.Connection) -> None:
    for sku, aliases in SEED_ROWS:
        await conn.execute(
            """
            INSERT INTO products (sku, name, type, aliases)
            VALUES ($1, $2, 'finished_good', $3::varchar[])
            """,
            sku,
            f"Миграция 083: {sku}",
            aliases,
        )


async def _state(conn: asyncpg.Connection) -> dict[str, list[str]]:
    rows = await conn.fetch("SELECT sku, aliases FROM products ORDER BY sku")
    return {row["sku"]: list(row["aliases"] or []) for row in rows}


def _migration_sql() -> tuple[str, str]:
    """SQL-константы самой миграции — чтобы проверить повторный проход.

    Имя файла миграции начинается с цифр, поэтому его нельзя импортировать как
    модуль пакета — грузим по пути. ``op`` внутри файла вызывается только в
    upgrade/downgrade, а константы — обычные строки.
    """
    import importlib.util

    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "083_normalize_als_sku_spelling.py"
    )
    spec = importlib.util.spec_from_file_location("migration_083", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._UPDATE_SKU, module._UPDATE_ALIASES


@pytest.mark.asyncio
async def test_migration_083_normalizes_sku_and_aliases(tmp_path: Path) -> None:
    db_name, target_url = await create_migration_db()
    env = alembic_env(target_url, tmp_path)
    conn: asyncpg.Connection | None = None
    try:
        run_alembic(("upgrade", REVISION_BEFORE), env)
        conn = await asyncpg.connect(_asyncpg_dsn(target_url))
        try:
            await _seed(conn)
        finally:
            await conn.close()
            conn = None

        run_alembic(("upgrade", "head"), env)

        conn = await asyncpg.connect(_asyncpg_dsn(target_url))
        try:
            assert await _state(conn) == EXPECTED_AFTER_UPGRADE

            # Повторный проход теми же запросами (stamp назад + upgrade в тесте
            # не воспроизводит идемпотентность: alembic не перезапускает миграцию):
            # состояние не меняется, коллизионная строка не переименовывается.
            update_sku, update_aliases = _migration_sql()
            await conn.execute(update_sku)
            await conn.execute(update_aliases)
            assert await _state(conn) == EXPECTED_AFTER_UPGRADE
        finally:
            await conn.close()
            conn = None

        run_alembic(("downgrade", REVISION_BEFORE), env)

        conn = await asyncpg.connect(_asyncpg_dsn(target_url))
        try:
            assert await _state(conn) == EXPECTED_AFTER_ROLLBACK
        finally:
            await conn.close()
            conn = None
    finally:
        if conn is not None:
            await conn.close()
        await drop_migration_db(db_name)
