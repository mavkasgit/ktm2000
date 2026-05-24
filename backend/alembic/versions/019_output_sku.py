"""add_output_sku_to_plan_positions

Revision ID: 019_output_sku
Revises: 018_rule_engine_phase
Create Date: 2026-05-24 04:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "019_output_sku"
down_revision: Union[str, None] = "018_rule_engine_phase"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "plan_positions",
        sa.Column("output_sku", sa.String(255), nullable=False, server_default=""),
    )
    # Copy source_sku → output_sku for existing rows
    op.execute("UPDATE plan_positions SET output_sku = source_sku WHERE output_sku = ''")


def downgrade() -> None:
    op.drop_column("plan_positions", "output_sku")
