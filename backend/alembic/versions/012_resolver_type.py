"""add resolver_type and resolver_config to section_operations

Revision ID: 012_resolver_type
Revises: 011_combined_op_group
Create Date: 2026-05-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "012_resolver_type"
down_revision = "011_combined_op_group"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("section_operations", sa.Column("resolver_type", sa.String(50), nullable=True))
    op.add_column(
        "section_operations",
        sa.Column("resolver_config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("section_operations", "resolver_config")
    op.drop_column("section_operations", "resolver_type")
