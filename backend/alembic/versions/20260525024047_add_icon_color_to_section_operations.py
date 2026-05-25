"""add icon and color to section operations

Revision ID: 021_icon_color_ops
Revises: f2a3b4c5d6e7
Create Date: 2026-05-25T02:40:47.182388
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '021_icon_color_ops'
down_revision: Union[str, None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('section_operations', sa.Column('icon', sa.String(50), nullable=True))
    op.add_column('section_operations', sa.Column('icon_color', sa.String(7), nullable=True))


def downgrade() -> None:
    op.drop_column('section_operations', 'icon_color')
    op.drop_column('section_operations', 'icon')
