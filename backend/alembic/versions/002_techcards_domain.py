"""techcards domain: techcards, techcard_lines

Revision ID: 002_techcards_domain
Revises: 001_products_domain
Create Date: 2026-05-25 12:01:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '002_techcards_domain'
down_revision: Union[str, None] = '001_products_domain'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'techcards',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('product_id', sa.BigInteger(), sa.ForeignKey('products.id'), nullable=True),
        sa.Column('version', sa.String(100), nullable=False),
        sa.Column('processing_type', sa.String(50), nullable=False, server_default=sa.text("'standart_processing'")),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column('quantity_total', sa.Integer(), nullable=True),
        sa.Column('quantity_a_per_item', sa.Integer(), nullable=True),
        sa.Column('quantity_b_per_item', sa.Integer(), nullable=True),
        sa.Column('hangers_a', sa.Integer(), nullable=True),
        sa.Column('hangers_b', sa.Integer(), nullable=True),
        sa.Column('hangers_total', sa.Integer(), nullable=True),
    )
    op.create_index('ix_techcards_product_id', 'techcards', ['product_id'])
    op.create_index(
        'ix_techcards_active_one_per_product',
        'techcards',
        ['product_id'],
        unique=True,
        postgresql_where=sa.text("is_active = true AND product_id IS NOT NULL"),
    )

    op.create_table(
        'techcard_lines',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('techcard_id', sa.BigInteger(), sa.ForeignKey('techcards.id'), nullable=False),
        sa.Column('component_product_id', sa.BigInteger(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('quantity', sa.Numeric(14, 3), nullable=False),
        sa.Column('unit', sa.String(50), nullable=False),
        sa.UniqueConstraint('techcard_id', 'component_product_id', name='uq_techcard_lines_component'),
    )


def downgrade() -> None:
    op.drop_table('techcard_lines')
    op.drop_index('ix_techcards_active_one_per_product', table_name='techcards')
    op.drop_index('ix_techcards_product_id', table_name='techcards')
    op.drop_table('techcards')
