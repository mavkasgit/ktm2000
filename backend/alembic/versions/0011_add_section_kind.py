"""add section kind

Revision ID: 0011_add_section_kind
Revises: 0010_add_product_source
Create Date: 2026-05-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0011_add_section_kind"
down_revision: Union[str, None] = "0010_add_product_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sections', sa.Column('kind', sa.String(length=20), server_default='production', nullable=False))


def downgrade() -> None:
    op.drop_column('sections', 'kind')
