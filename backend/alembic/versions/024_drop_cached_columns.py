"""024_drop_work_task_cached_columns

Этап 4 рефакторинга Stock Ledger (см. PLAN_stock_ledger.md).

WorkTask.cached_* колонки удаляются — кэш вычисляется на лету из
StockTransaction ledger через StockProjectionManager.get_task_cache().

* DROP 8 CHECK constraints для cached_* колонок
* DROP 8 cached_* колонок

Revision ID: 024_drop_work_task_cached_columns
Revises: 023_section_location_type
Create Date: 2026-07-03 19:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "024_drop_cached_columns"
down_revision: Union[str, None] = "023_section_location_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CACHED_COLUMNS = [
    "cached_available_quantity",
    "cached_issued_quantity",
    "cached_in_work_quantity",
    "cached_completed_quantity",
    "cached_transferred_quantity",
    "cached_received_quantity",
    "cached_rejected_quantity",
    "cached_remaining_quantity",
]


def upgrade() -> None:
    # Drop CHECK constraints
    for col in CACHED_COLUMNS:
        constraint_name = f"ck_work_tasks_{col}_non_negative"
        op.execute(
            f"ALTER TABLE work_tasks DROP CONSTRAINT IF EXISTS {constraint_name}"
        )
    # Drop columns
    for col in CACHED_COLUMNS:
        op.drop_column("work_tasks", col)


def downgrade() -> None:
    # Restore columns
    for col in CACHED_COLUMNS:
        op.add_column(
            "work_tasks",
            sa.Column(col, sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        )
    # Restore CHECK constraints
    for col in CACHED_COLUMNS:
        constraint_name = f"ck_work_tasks_{col}_non_negative"
        op.create_check_constraint(
            constraint_name,
            "work_tasks",
            f"{col} >= 0",
        )
