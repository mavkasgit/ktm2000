"""add route_profile_id to plan_positions

Revision ID: 017_add_route_profile_id
Revises: 016_route_name_pattern
Create Date: 2026-05-30

"""
from alembic import op
import sqlalchemy as sa


revision = '017_add_route_profile_id'
down_revision = '016_route_name_pattern'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('plan_positions', sa.Column('route_profile_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'fk_plan_positions_route_profile_id',
        'plan_positions', 'route_rule_profiles',
        ['route_profile_id'], ['id']
    )


def downgrade() -> None:
    op.drop_constraint('fk_plan_positions_route_profile_id', 'plan_positions', type_='foreignkey')
    op.drop_column('plan_positions', 'route_profile_id')
