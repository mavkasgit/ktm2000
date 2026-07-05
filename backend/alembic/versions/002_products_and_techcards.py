"""products_and_techcards

Эпик: Номенклатура, техкарты, флаги обработки
Irreversible: no

Revision ID: 002_products_and_techcards
Revises: 001_sections_and_users
Create Date: 2026-07-05 19:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "002_products_and_techcards"
down_revision: Union[str, None] = "001_sections_and_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- SCHEMA ---
    op.create_table('processing_flags',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('section_scope', sa.String(length=50), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_processing_flags'))
    )
    op.create_index(op.f('ix_processing_flags_code'), 'processing_flags', ['code'], unique=True)
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
    sa.PrimaryKeyConstraint('id', name=op.f('pk_products'))
    )
    op.create_index(op.f('ix_products_alloy'), 'products', ['alloy'], unique=False)
    op.create_index(op.f('ix_products_color'), 'products', ['color'], unique=False)
    op.create_index(op.f('ix_products_name'), 'products', ['name'], unique=False)
    op.create_index(op.f('ix_products_profile_type'), 'products', ['profile_type'], unique=False)
    op.create_index(op.f('ix_products_sku'), 'products', ['sku'], unique=True)
    op.create_index(op.f('ix_products_source'), 'products', ['source'], unique=False)
    op.create_table('product_lengths',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('product_id', sa.BigInteger(), nullable=False),
    sa.Column('length_mm', sa.Float(), nullable=False),
    sa.CheckConstraint('length_mm > 0', name=op.f('ck_product_lengths_positive')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_product_lengths_product_id_products')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_product_lengths'))
    )
    op.create_table('product_processing_flags',
    sa.Column('product_id', sa.BigInteger(), nullable=False),
    sa.Column('flag_id', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['flag_id'], ['processing_flags.id'], name=op.f('fk_product_processing_flags_flag_id_processing_flags')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_product_processing_flags_product_id_products')),
    sa.PrimaryKeyConstraint('product_id', 'flag_id', name=op.f('pk_product_processing_flags'))
    )
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
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_techcards_product_id_products')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_techcards'))
    )
    op.create_index('ix_techcards_active_one_per_product', 'techcards', ['product_id'], unique=True, postgresql_where=sa.text('is_active = true AND product_id IS NOT NULL'))
    op.create_table('techcard_lines',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('techcard_id', sa.BigInteger(), nullable=False),
    sa.Column('component_product_id', sa.BigInteger(), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('unit', sa.String(length=50), nullable=False),
    sa.ForeignKeyConstraint(['component_product_id'], ['products.id'], name=op.f('fk_techcard_lines_component_product_id_products')),
    sa.ForeignKeyConstraint(['techcard_id'], ['techcards.id'], name=op.f('fk_techcard_lines_techcard_id_techcards')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_techcard_lines')),
    sa.UniqueConstraint('techcard_id', 'component_product_id', name='uq_techcard_lines_component')
    )

    # --- DATA ---
    pass

    # --- TRIGGERS ---
    pass


def downgrade() -> None:
    op.drop_table('techcard_lines')
    op.drop_table('techcards')
    op.drop_table('product_processing_flags')
    op.drop_table('product_lengths')
    op.drop_table('products')
    op.drop_table('processing_flags')
