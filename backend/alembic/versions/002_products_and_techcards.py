"""products and techcards

Revision ID: 002_products_and_techcards
Revises: 001_users_and_sections
Create Date: 2026-06-05 15:01:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '002_products_and_techcards'
down_revision: Union[str, None] = '001_users_and_sections'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create processing_flags
    op.create_table('processing_flags',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('section_scope', sa.String(length=50), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_processing_flags_code'), 'processing_flags', ['code'], unique=True)

    # 2. Create products
    op.create_table('products',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('sku', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('type', sa.Enum('finished_good', 'semi_finished', 'component', 'material', name='product_type'), nullable=False),
        sa.Column('unit', sa.String(length=50), server_default=sa.text("'pcs'"), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('notes', sa.String(length=2000), nullable=True),
        sa.Column('profile_type', sa.String(length=100), nullable=True),
        sa.Column('alloy', sa.String(length=50), nullable=True),
        sa.Column('color', sa.String(length=50), nullable=True),
        sa.Column('anod_type', sa.String(length=50), nullable=True),
        sa.Column('length_mm', sa.Float(), nullable=True),
        sa.Column('weight_per_meter', sa.Float(), nullable=True),
        sa.Column('quantity_per_hanger', sa.Integer(), nullable=True),
        sa.Column('cross_section', sa.String(length=100), nullable=True),
        sa.Column('photo_thumb', sa.String(length=500), nullable=True),
        sa.Column('photo_full', sa.String(length=500), nullable=True),
        sa.Column('source', sa.String(length=50), nullable=True),
        sa.Column('is_catalog_item', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('is_paired_profile', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('skip_shot_blast', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('is_laminated', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('aliases', sa.ARRAY(sa.String()), server_default=sa.text("'{}'"), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_products_alloy'), 'products', ['alloy'], unique=False)
    op.create_index(op.f('ix_products_color'), 'products', ['color'], unique=False)
    op.create_index(op.f('ix_products_name'), 'products', ['name'], unique=False)
    op.create_index(op.f('ix_products_profile_type'), 'products', ['profile_type'], unique=False)
    op.create_index(op.f('ix_products_sku'), 'products', ['sku'], unique=True)
    op.create_index(op.f('ix_products_source'), 'products', ['source'], unique=False)

    # 3. Create product_lengths
    op.create_table('product_lengths',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('product_id', sa.BigInteger(), nullable=False),
        sa.Column('length_mm', sa.Float(), nullable=False),
        sa.CheckConstraint('length_mm > 0', name='ck_product_lengths_positive'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # 4. Create product_processing_flags
    op.create_table('product_processing_flags',
        sa.Column('product_id', sa.BigInteger(), nullable=False),
        sa.Column('flag_id', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['flag_id'], ['processing_flags.id'], ),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.PrimaryKeyConstraint('product_id', 'flag_id')
    )

    # 5. Create techcards
    op.create_table('techcards',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('product_id', sa.BigInteger(), nullable=True),
        sa.Column('version', sa.String(length=100), nullable=False),
        sa.Column('processing_type', sa.String(length=50), server_default=sa.text("'standart_processing'"), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('quantity_total', sa.Integer(), nullable=True),
        sa.Column('quantity_a_per_item', sa.Integer(), nullable=True),
        sa.Column('quantity_b_per_item', sa.Integer(), nullable=True),
        sa.Column('hangers_a', sa.Integer(), nullable=True),
        sa.Column('hangers_b', sa.Integer(), nullable=True),
        sa.Column('hangers_total', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(
        'ix_techcards_active_one_per_product',
        'techcards',
        ['product_id'],
        unique=True,
        postgresql_where=sa.text('is_active = true AND product_id IS NOT NULL')
    )

    # 6. Create techcard_lines
    op.create_table('techcard_lines',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('techcard_id', sa.BigInteger(), nullable=False),
        sa.Column('component_product_id', sa.BigInteger(), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column('unit', sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(['component_product_id'], ['products.id'], ),
        sa.ForeignKeyConstraint(['techcard_id'], ['techcards.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('techcard_id', 'component_product_id', name='uq_techcard_lines_component')
    )


def downgrade() -> None:
    op.drop_table('techcard_lines')
    op.drop_index('ix_techcards_active_one_per_product', table_name='techcards')
    op.drop_table('techcards')
    op.drop_table('product_processing_flags')
    op.drop_table('product_lengths')
    op.drop_table('products')
    sa.Enum(name='product_type').drop(op.get_bind(), checkfirst=False)
    op.drop_index(op.f('ix_processing_flags_code'), table_name='processing_flags')
    op.drop_table('processing_flags')
