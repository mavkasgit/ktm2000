"""add route selection rules

Revision ID: 011_route_selection_rules
Revises: 010_press_semi_exact_rules
Create Date: 2026-05-15 10:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "011_route_selection_rules"
down_revision: Union[str, None] = "010_press_semi_exact_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE plan_position_route_match_reason ADD VALUE IF NOT EXISTS 'selection_rules'")
    op.execute("ALTER TYPE plan_position_route_match_reason ADD VALUE IF NOT EXISTS 'no_route_candidate'")
    op.execute("ALTER TYPE plan_position_route_match_reason ADD VALUE IF NOT EXISTS 'route_rule_conflict'")

    op.create_table(
        "route_selection_rules",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("code", sa.String(length=100), nullable=True, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_route_selection_rules_priority", "route_selection_rules", ["priority", "id"])


def downgrade() -> None:
    op.drop_index("ix_route_selection_rules_priority", table_name="route_selection_rules")
    op.drop_table("route_selection_rules")
