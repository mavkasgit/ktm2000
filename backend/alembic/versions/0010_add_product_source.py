"""add product source fields

Revision ID: 0010_add_product_source
Revises: 0009_extend_product_fields
Create Date: 2026-05-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0010_add_product_source"
down_revision: Union[str, None] = "0009_extend_product_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('source', sa.String(length=50), nullable=True))
    op.add_column('products', sa.Column('is_catalog_item', sa.Boolean(), server_default='false', nullable=False))
    op.create_index('ix_products_source', 'products', ['source'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_products_source', table_name='products')
    op.drop_column('products', 'is_catalog_item')
    op.drop_column('products', 'source')
