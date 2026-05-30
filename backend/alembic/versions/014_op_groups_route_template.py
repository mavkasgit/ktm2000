"""add route_sections to profiles, group_name and sort_order to section_operations

Revision ID: 014_op_groups_route_template
Revises: 013_drop_route_routing_enums
Create Date: 2026-05-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "014_op_groups_route_template"
down_revision = "013_drop_route_routing_enums"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. route_sections JSONB in route_rule_profiles
    op.add_column(
        "route_rule_profiles",
        sa.Column("route_sections", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )

    # 2. group_name VARCHAR(255) in section_operations
    op.add_column(
        "section_operations",
        sa.Column("group_name", sa.String(255), nullable=True),
    )

    # 2b. group_code VARCHAR(100) in section_operations
    op.add_column(
        "section_operations",
        sa.Column("group_code", sa.String(100), nullable=True),
    )

    # 3. sort_order INTEGER in section_operations
    op.add_column(
        "section_operations",
        sa.Column("sort_order", sa.Integer, nullable=False, server_default=sa.text("0"), default=0),
    )


def downgrade() -> None:
    op.drop_column("section_operations", "sort_order")
    op.execute("ALTER TABLE section_operations DROP COLUMN IF EXISTS group_code")
    op.drop_column("section_operations", "group_name")
    op.drop_column("route_rule_profiles", "route_sections")
