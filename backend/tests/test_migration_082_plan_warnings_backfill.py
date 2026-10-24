"""Бэкфилл ``plan_positions.validation_warnings`` из применённых change items.

Тикет #334, миграция ``082_plan_position_validation_warnings_backfill``:
исторические позиции (до 079) получают предупреждения последнего применённого
``PlanChangeItem``, позиции с уже заполненной колонкой не трогаются, откаченные
и неприменённые сеты источником не считаются.

Источник — только действия, которые пишут предупреждения на позицию
(``create_position``/``update_draft_position``), включая сеты, применённые до
057 (``applied_at IS NULL``, ``status = 'applied'``).

Тест отдельный от ``test_migrations.py``: тот файл правится параллельно
(#335), а проверка нужна самостоятельная. База — одноразовая ``ktm_mig_*``
через общий helper ``tests/helpers/mig_db.py``.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
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
REVISION_BEFORE = "081_drop_stock_dimensions_gin"

#: SQLSTATE-независимое ожидание: у каждой позиции ровно один ответ.
EXPECTED_WARNINGS = {
    "MIG-082-LATEST": ["latest_warning"],
    "MIG-082-TWO-SETS": ["newer_warning"],
    "MIG-082-CLEARED": [],
    "MIG-082-KEPT": ["kept_warning"],
    "MIG-082-UNAPPLIED": [],
    "MIG-082-CANCELLED": [],
    # Дубль не пишет предупреждения на позицию, поэтому источником остаётся
    # create_position; пустой список дубля не гасит его.
    "MIG-082-DUPLICATE": ["created_warning"],
    # Дубль с непустым списком тоже не источник: чужие предупреждения не
    # должны переехать на позицию через бэкфилл.
    "MIG-082-DUPLICATE-WARNINGS": ["created_warning"],
    # Сет применён до 057: applied_at NULL, но status = 'applied'.
    "MIG-082-PRE057": ["pre_057_warning"],
}


pytestmark = pytest.mark.skipif(
    not migration_db_reachable(),
    reason="PostgreSQL server not reachable for migration test",
)


def _asyncpg_dsn(target_url: str) -> str:
    return target_url.replace("postgresql+asyncpg://", "postgresql://")


async def _insert_position(
    conn: asyncpg.Connection,
    plan_id: int,
    sku: str,
    row_number: int,
    *,
    validation_warnings: list[str] | None = None,
) -> int:
    warnings = json.dumps(validation_warnings or [])
    return await conn.fetchval(
        """
        INSERT INTO plan_positions (
            production_plan_id, source_type, source_sku, quantity,
            status, validation_status, validation_warnings, source_row_number
        )
        VALUES ($1, 'excel_import', $2, 10, 'draft', 'valid', $3::jsonb, $4)
        RETURNING id
        """,
        plan_id,
        sku,
        warnings,
        row_number,
    )


async def _insert_change_set(
    conn: asyncpg.Connection,
    plan_id: int,
    *,
    status: str,
    applied_at: datetime | None,
) -> int:
    return await conn.fetchval(
        """
        INSERT INTO plan_change_sets (production_plan_id, status, summary, applied_at)
        VALUES ($1, $2, '{}'::jsonb, $3)
        RETURNING id
        """,
        plan_id,
        status,
        applied_at,
    )


async def _insert_item(
    conn: asyncpg.Connection,
    change_set_id: int,
    position_id: int,
    *,
    warnings: list[str],
    status: str = "applied",
    action: str = "create_position",
) -> None:
    await conn.execute(
        """
        INSERT INTO plan_change_items (
            change_set_id, plan_position_id, source_row_number, source_ref,
            change_action, after_data, status, warnings, errors
        )
        VALUES ($1, $2, 1, 'rows:1', $3, '{}'::jsonb, $4, $5::jsonb, '[]'::jsonb)
        """,
        change_set_id,
        position_id,
        action,
        status,
        json.dumps(warnings),
    )


async def _warnings_by_sku(conn: asyncpg.Connection) -> dict[str, list[str]]:
    rows = await conn.fetch("SELECT source_sku, validation_warnings FROM plan_positions")
    return {row["source_sku"]: json.loads(row["validation_warnings"]) for row in rows}


async def _seed_history(conn: asyncpg.Connection) -> None:
    """История применений: свежий, два сета, очистка, «уже заполнено», черновик, откат, дубль."""
    plan_id = await conn.fetchval(
        """
        INSERT INTO production_plans (plan_no, name, status)
        VALUES ('MIG-082-BACKFILL', 'Migration 082 backfill', 'draft')
        RETURNING id
        """
    )
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)

    latest = await _insert_position(conn, plan_id, "MIG-082-LATEST", 1)
    latest_set = await _insert_change_set(conn, plan_id, status="applied", applied_at=base)
    await _insert_item(conn, latest_set, latest, warnings=["latest_warning"])

    two_sets = await _insert_position(conn, plan_id, "MIG-082-TWO-SETS", 2)
    older_set = await _insert_change_set(
        conn, plan_id, status="applied", applied_at=base - timedelta(days=2)
    )
    await _insert_item(conn, older_set, two_sets, warnings=["older_warning"])
    newer_set = await _insert_change_set(
        conn, plan_id, status="applied", applied_at=base - timedelta(days=1)
    )
    await _insert_item(conn, newer_set, two_sets, warnings=["newer_warning"])

    cleared = await _insert_position(conn, plan_id, "MIG-082-CLEARED", 3)
    cleared_old = await _insert_change_set(
        conn, plan_id, status="applied", applied_at=base - timedelta(days=2)
    )
    await _insert_item(conn, cleared_old, cleared, warnings=["old_warning"])
    cleared_new = await _insert_change_set(
        conn, plan_id, status="applied", applied_at=base - timedelta(days=1)
    )
    await _insert_item(conn, cleared_new, cleared, warnings=[])

    kept = await _insert_position(
        conn, plan_id, "MIG-082-KEPT", 4, validation_warnings=["kept_warning"]
    )
    kept_set = await _insert_change_set(conn, plan_id, status="applied", applied_at=base)
    await _insert_item(conn, kept_set, kept, warnings=["legacy_warning"])

    unapplied = await _insert_position(conn, plan_id, "MIG-082-UNAPPLIED", 5)
    unapplied_set = await _insert_change_set(conn, plan_id, status="draft", applied_at=None)
    await _insert_item(conn, unapplied_set, unapplied, warnings=["draft_warning"], status="pending")

    cancelled = await _insert_position(conn, plan_id, "MIG-082-CANCELLED", 6)
    cancelled_set = await _insert_change_set(conn, plan_id, status="cancelled", applied_at=None)
    await _insert_item(conn, cancelled_set, cancelled, warnings=["cancelled_warning"])

    # Дубль не переносит предупреждения на позицию (#328), поэтому его
    # элемент не источник: остаётся create_position с непустым списком.
    duplicate = await _insert_position(conn, plan_id, "MIG-082-DUPLICATE", 7)
    duplicate_created = await _insert_change_set(
        conn, plan_id, status="applied", applied_at=base - timedelta(days=1)
    )
    await _insert_item(conn, duplicate_created, duplicate, warnings=["created_warning"])
    duplicate_later = await _insert_change_set(conn, plan_id, status="applied", applied_at=base)
    await _insert_item(
        conn,
        duplicate_later,
        duplicate,
        warnings=[],
        action="mark_possible_duplicate",
    )

    # Дубль с непустым списком: предупреждения элемента не про позицию и на
    # неё не попадают ни в рантайме, ни в бэкфилле.
    duplicate_warnings = await _insert_position(
        conn, plan_id, "MIG-082-DUPLICATE-WARNINGS", 8
    )
    duplicate_warnings_created = await _insert_change_set(
        conn, plan_id, status="applied", applied_at=base - timedelta(days=1)
    )
    await _insert_item(
        conn, duplicate_warnings_created, duplicate_warnings, warnings=["created_warning"]
    )
    duplicate_warnings_later = await _insert_change_set(
        conn, plan_id, status="applied", applied_at=base
    )
    await _insert_item(
        conn,
        duplicate_warnings_later,
        duplicate_warnings,
        warnings=["duplicate_warning"],
        action="mark_possible_duplicate",
    )

    # Применение до 057: applied_at ещё не было, поэтому NULL, а статус —
    # applied. Такой сет обязан остаться источником бэкфилла.
    pre_057 = await _insert_position(conn, plan_id, "MIG-082-PRE057", 9)
    pre_057_set = await _insert_change_set(conn, plan_id, status="applied", applied_at=None)
    await _insert_item(conn, pre_057_set, pre_057, warnings=["pre_057_warning"])


@pytest.mark.asyncio
async def test_migration_082_backfills_warnings_from_last_applied_item(tmp_path: Path) -> None:
    db_name, target_url = await create_migration_db()
    env = alembic_env(target_url, tmp_path)
    conn: asyncpg.Connection | None = None
    try:
        run_alembic(("upgrade", REVISION_BEFORE), env)
        conn = await asyncpg.connect(_asyncpg_dsn(target_url))
        try:
            await _seed_history(conn)
        finally:
            await conn.close()
            conn = None

        run_alembic(("upgrade", "head"), env)

        conn = await asyncpg.connect(_asyncpg_dsn(target_url))
        try:
            assert await _warnings_by_sku(conn) == EXPECTED_WARNINGS

            # Повторный проход (downgrade 082 — no-op, затем upgrade) не
            # переписывает уже заполненные значения.
            run_alembic(("downgrade", REVISION_BEFORE), env)
            assert await _warnings_by_sku(conn) == EXPECTED_WARNINGS
        finally:
            await conn.close()
            conn = None

        run_alembic(("upgrade", "head"), env)
        conn = await asyncpg.connect(_asyncpg_dsn(target_url))
        try:
            assert await _warnings_by_sku(conn) == EXPECTED_WARNINGS
        finally:
            await conn.close()
            conn = None
    finally:
        if conn is not None:
            await conn.close()
        await drop_migration_db(db_name)
