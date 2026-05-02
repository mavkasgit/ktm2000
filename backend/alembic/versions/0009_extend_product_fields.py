"""extend product with profile fields

Revision ID: 0009_extend_product_fields
Revises: 0008_seed_factory_sections
Create Date: 2026-05-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0009_extend_product_fields"
down_revision: Union[str, None] = "0008_seed_factory_sections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Expand notes column
    op.alter_column('products', 'notes',
               existing_type=sa.VARCHAR(length=1000),
               type_=sa.String(length=2000),
               existing_nullable=True)
    
    # Add profile-specific columns
    op.add_column('products', sa.Column('profile_type', sa.String(length=100), nullable=True))
    op.add_column('products', sa.Column('alloy', sa.String(length=50), nullable=True))
    op.add_column('products', sa.Column('color', sa.String(length=50), nullable=True))
    op.add_column('products', sa.Column('anod_type', sa.String(length=50), nullable=True))
    op.add_column('products', sa.Column('length_mm', sa.Float(), nullable=True))
    op.add_column('products', sa.Column('weight_per_meter', sa.Float(), nullable=True))
    op.add_column('products', sa.Column('quantity_per_hanger', sa.Integer(), nullable=True))
    op.add_column('products', sa.Column('cross_section', sa.String(length=100), nullable=True))
    op.add_column('products', sa.Column('photo_thumb', sa.String(length=500), nullable=True))
    op.add_column('products', sa.Column('photo_full', sa.String(length=500), nullable=True))
    
    # Add indexes for search/filter performance
    op.create_index('ix_products_profile_type', 'products', ['profile_type'], unique=False)
    op.create_index('ix_products_alloy', 'products', ['alloy'], unique=False)
    op.create_index('ix_products_color', 'products', ['color'], unique=False)
    op.create_index('ix_products_sku', 'products', ['sku'], unique=False)
    op.create_index('ix_products_name', 'products', ['name'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_products_name', table_name='products')
    op.drop_index('ix_products_sku', table_name='products')
    op.drop_index('ix_products_color', table_name='products')
    op.drop_index('ix_products_alloy', table_name='products')
    op.drop_index('ix_products_profile_type', table_name='products')
    
    op.drop_column('products', 'photo_full')
    op.drop_column('products', 'photo_thumb')
    op.drop_column('products', 'cross_section')
    op.drop_column('products', 'quantity_per_hanger')
    op.drop_column('products', 'weight_per_meter')
    op.drop_column('products', 'length_mm')
    op.drop_column('products', 'anod_type')
    op.drop_column('products', 'color')
    op.drop_column('products', 'alloy')
    op.drop_column('products', 'profile_type')
    
    op.alter_column('products', 'notes',
               existing_type=sa.String(length=2000),
               type_=sa.VARCHAR(length=1000),
               existing_nullable=True)
