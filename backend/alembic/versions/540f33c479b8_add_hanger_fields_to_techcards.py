"""add_hanger_fields_to_techcards

Revision ID: 540f33c479b8
Revises: 4db6464c9e10
Create Date: 2026-05-03 19:17:42.935227
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision: str = '540f33c479b8'
down_revision: Union[str, None] = '4db6464c9e10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("techcards", sa.Column("hangers_a", sa.Integer(), nullable=True))
    op.add_column("techcards", sa.Column("hangers_b", sa.Integer(), nullable=True))
    op.add_column("techcards", sa.Column("hangers_total", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("techcards", "hangers_total")
    op.drop_column("techcards", "hangers_b")
    op.drop_column("techcards", "hangers_a")
