"""add route_name_pattern to route_rule_profiles

Revision ID: 016_route_name_pattern
Revises: 015_drop_normalization_rules
Create Date: 2026-05-30
"""
from alembic import op
import sqlalchemy as sa


revision = '016_route_name_pattern'
down_revision = '015_drop_normalization_rules'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'route_rule_profiles',
        sa.Column('route_name_pattern', sa.String(255), nullable=False, server_default='{output_kind} - {operations}')
    )


def downgrade() -> None:
    op.drop_column('route_rule_profiles', 'route_name_pattern')
