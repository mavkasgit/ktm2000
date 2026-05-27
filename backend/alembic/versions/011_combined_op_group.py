"""add combined_op_group to route_steps

Revision ID: 011_combined_op_group
Revises: 009_seed_data
Create Date: 2026-05-27
"""
from alembic import op
import sqlalchemy as sa

revision = "011_combined_op_group"
down_revision = "010_warehouse_remainders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("route_steps", sa.Column("combined_op_group", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("route_steps", "combined_op_group")
