"""drop normalization_rules from import_templates

Revision ID: 015_drop_normalization_rules
Revises: 014_op_groups_route_template
Create Date: 2026-05-30
"""
from alembic import op

revision = "015_drop_normalization_rules"
down_revision = "014_op_groups_route_template"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE import_templates DROP COLUMN IF EXISTS normalization_rules")


def downgrade() -> None:
    import sqlalchemy as sa
    op.add_column(
        "import_templates",
        sa.Column("normalization_rules", sa.dialects.postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
