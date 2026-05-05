"""merge seed_sections and plan_positions_route_id

Revision ID: 11eeae284970
Revises: a1b2c3d4e5f6, 004_seed_sections
Create Date: 2026-05-05 02:00:43.911265
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision: str = '11eeae284970'
down_revision: Union[str, None] = ('a1b2c3d4e5f6', '004_seed_sections')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
