"""add_quantity_fields_to_techcards

Revision ID: 4db6464c9e10
Revises: 89fd6a7d5f21
Create Date: 2026-05-03 19:08:12.711837
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision: str = '4db6464c9e10'
down_revision: Union[str, None] = '89fd6a7d5f21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("techcards", sa.Column("quantity_total", sa.Integer(), nullable=True))
    op.add_column("techcards", sa.Column("quantity_a_per_item", sa.Integer(), nullable=True))
    op.add_column("techcards", sa.Column("quantity_b_per_item", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("techcards", "quantity_b_per_item")
    op.drop_column("techcards", "quantity_a_per_item")
    op.drop_column("techcards", "quantity_total")
