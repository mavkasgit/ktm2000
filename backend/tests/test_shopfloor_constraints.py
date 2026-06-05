"""Tests for database-level CHECK constraints on shopfloor models."""

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_movement_quantity_positive_constraint_exists(client, session) -> None:
    """DB-level constraint: ck_movements_quantity_positive."""
    result = (await session.execute(text(
        "SELECT conname FROM pg_constraint WHERE conname = 'ck_movements_quantity_positive'"
    ))).scalar()
    assert result == "ck_movements_quantity_positive"


@pytest.mark.asyncio
async def test_defect_items_qty_positive_constraint_exists(client, session) -> None:
    """DB-level constraint: ck_defect_items_qty_positive."""
    result = (await session.execute(text(
        "SELECT conname FROM pg_constraint WHERE conname = 'ck_defect_items_qty_positive'"
    ))).scalar()
    assert result == "ck_defect_items_qty_positive"


@pytest.mark.asyncio
async def test_transfers_sent_quantity_positive_constraint_exists(client, session) -> None:
    """DB-level constraint: ck_transfers_sent_quantity_positive."""
    result = (await session.execute(text(
        "SELECT conname FROM pg_constraint WHERE conname = 'ck_transfers_sent_quantity_positive'"
    ))).scalar()
    assert result == "ck_transfers_sent_quantity_positive"


@pytest.mark.asyncio
async def test_transfer_discrepancy_qty_positive_constraint_exists(client, session) -> None:
    """DB-level constraint: ck_transfer_discrepancy_qty_positive."""
    result = (await session.execute(text(
        "SELECT conname FROM pg_constraint WHERE conname = 'ck_transfer_discrepancy_qty_positive'"
    ))).scalar()
    assert result == "ck_transfer_discrepancy_qty_positive"


@pytest.mark.asyncio
async def test_work_task_cache_constraints_exist(client, session) -> None:
    """DB-level constraints: ck_work_tasks_cached_*_non_negative."""
    expected = [
        "ck_work_tasks_cached_available_quantity_non_negative",
        "ck_work_tasks_cached_issued_quantity_non_negative",
        "ck_work_tasks_cached_in_work_quantity_non_negative",
        "ck_work_tasks_cached_completed_quantity_non_negative",
        "ck_work_tasks_cached_transferred_quantity_non_negative",
        "ck_work_tasks_cached_received_quantity_non_negative",
        "ck_work_tasks_cached_rejected_quantity_non_negative",
        "ck_work_tasks_cached_remaining_quantity_non_negative",
        "ck_work_tasks_planned_quantity_non_negative",
    ]
    for name in expected:
        result = (await session.execute(text(
            f"SELECT conname FROM pg_constraint WHERE conname = '{name}'"
        ))).scalar()
        assert result == name, f"Constraint {name} should exist"


@pytest.mark.asyncio
async def test_rework_tasks_qty_positive_constraint_exists(client, session) -> None:
    """DB-level constraint: ck_rework_tasks_qty_positive."""
    result = (await session.execute(text(
        "SELECT conname FROM pg_constraint WHERE conname = 'ck_rework_tasks_qty_positive'"
    ))).scalar()
    assert result == "ck_rework_tasks_qty_positive"


@pytest.mark.asyncio
async def test_defect_decisions_qty_positive_constraint_exists(client, session) -> None:
    """DB-level constraint: ck_defect_decisions_qty_positive."""
    result = (await session.execute(text(
        "SELECT conname FROM pg_constraint WHERE conname = 'ck_defect_decisions_qty_positive'"
    ))).scalar()
    assert result == "ck_defect_decisions_qty_positive"


@pytest.mark.asyncio
async def test_discrepancy_defect_item_qty_positive_constraint_exists(client, session) -> None:
    """DB-level constraint: ck_discrepancy_defect_item_qty_positive."""
    result = (await session.execute(text(
        "SELECT conname FROM pg_constraint WHERE conname = 'ck_discrepancy_defect_item_qty_positive'"
    ))).scalar()
    assert result == "ck_discrepancy_defect_item_qty_positive"


@pytest.mark.asyncio
async def test_transfer_accepted_rejected_non_negative_constraints_exist(client, session) -> None:
    """DB-level constraints: ck_transfers_accepted_quantity_non_negative, ck_transfers_rejected_quantity_non_negative."""
    for name in ["ck_transfers_accepted_quantity_non_negative", "ck_transfers_rejected_quantity_non_negative"]:
        result = (await session.execute(text(
            f"SELECT conname FROM pg_constraint WHERE conname = '{name}'"
        ))).scalar()
        assert result == name, f"Constraint {name} should exist"


@pytest.mark.asyncio
async def test_transfer_discrepancy_non_negative_constraints_exist(client, session) -> None:
    """DB-level constraints for transfer_discrepancies resolved/unresolved non-negative."""
    for name in ["ck_transfer_discrepancy_resolved_non_negative", "ck_transfer_discrepancy_unresolved_non_negative"]:
        result = (await session.execute(text(
            f"SELECT conname FROM pg_constraint WHERE conname = '{name}'"
        ))).scalar()
        assert result == name, f"Constraint {name} should exist"
