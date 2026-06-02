"""manual stock operations: add manual_in/manual_out movement types and allow negative remainders.

Revision ID: 019_remainder_manual_ops
Revises: 011_remainder_manual
Create Date: 2026-06-02 23:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = '019_remainder_manual_ops'
down_revision: Union[str, None] = '011_remainder_manual'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New movement types for manual stock operations (no plan task)
    op.execute("ALTER TYPE movement_type ADD VALUE IF NOT EXISTS 'manual_in'")
    op.execute("ALTER TYPE movement_type ADD VALUE IF NOT EXISTS 'manual_out'")

    # Allow negative remainders so we can over-issue and fix post-factum.
    op.drop_constraint(
        'ck_warehouse_remainders_quantity_non_negative',
        'warehouse_remainders',
        type_='check',
    )


def downgrade() -> None:
    op.create_check_constraint(
        'ck_warehouse_remainders_quantity_non_negative',
        'warehouse_remainders',
        'remainder_quantity >= 0',
    )
    # Note: PostgreSQL cannot drop enum values, so manual_in/manual_out remain.
