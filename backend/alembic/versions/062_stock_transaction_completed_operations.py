"""Признак «пройденные операции» на проводках ledger (ADR-0043, #207).

Revision ID: 062_stock_tx_completed_operations
Revises: 061_daily_plans
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "062_stock_tx_completed_operations"
down_revision: str | None = "061_daily_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("stock_transactions")
    }
    if "completed_operations" not in columns:
        op.add_column(
            "stock_transactions",
            sa.Column(
                "completed_operations",
                postgresql.JSONB(none_as_null=True),
                nullable=True,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("stock_transactions")
    }
    if "completed_operations" in columns:
        op.drop_column("stock_transactions", "completed_operations")
