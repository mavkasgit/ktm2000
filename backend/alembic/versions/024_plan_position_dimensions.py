"""Габариты в позиции плана: вход + список выходов группы строк (ADR-0003)

Revision ID: 024_plan_position_dimensions
Revises: 023_stock_dimensions
Create Date: 2026-07-31

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "024_plan_position_dimensions"
down_revision = "023_stock_dimensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plan_positions",
        sa.Column("input_quantity", sa.Numeric(14, 3), nullable=True),
    )
    op.add_column(
        "plan_positions",
        sa.Column("input_dimensions", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "plan_positions",
        sa.Column(
            "outputs",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("plan_positions", "outputs")
    op.drop_column("plan_positions", "input_dimensions")
    op.drop_column("plan_positions", "input_quantity")
