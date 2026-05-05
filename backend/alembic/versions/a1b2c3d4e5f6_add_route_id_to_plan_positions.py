"""add route_id to plan_positions

Revision ID: a1b2c3d4e5f6
Revises: 004_seed_sections
Create Date: 2026-05-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '004_seed_sections'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'plan_positions',
        sa.Column('route_id', sa.BigInteger(), nullable=True)
    )
    op.create_foreign_key(
        'fk_plan_positions_route_id',
        'plan_positions',
        'production_routes',
        ['route_id'],
        ['id']
    )


def downgrade() -> None:
    op.drop_constraint('fk_plan_positions_route_id', 'plan_positions', type_='foreignkey')
    op.drop_column('plan_positions', 'route_id')
