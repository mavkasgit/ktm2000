"""products domain: products, product_lengths, processing_flags, product_processing_flags

Revision ID: 001_products_domain
Revises:
Create Date: 2026-05-25 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '001_products_domain'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROCESSING_FLAGS = [
    ("WINDOW", "Оконный профиль", "PRESS"),
    ("COMB", "Комбинированный профиль", "PRESS"),
    ("DRILL", "Сверловка", None),
    ("GLUE", "Склейка", None),
    ("DIFFUSER", "Диффузор", None),
    ("RUBBER", "Резинка", None),
    ("RUBBER_DRILL", "Сверловка резинки", None),
    ("SHOT_SKIP", "Пропуск дробеструйки", None),
]


def _create_enum_if_not_exists(name: str, values: list[str]) -> None:
    """Create a PostgreSQL enum only if it doesn't exist, using a PL/pgSQL block."""
    values_sql = ", ".join(f"'{v}'" for v in values)
    op.execute(sa.text(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{name}') THEN
                CREATE TYPE {name} AS ENUM ({values_sql});
            END IF;
        END$$;
    """))


def upgrade() -> None:
    _create_enum_if_not_exists("product_type", ["finished_good", "semi_finished", "component", "material"])

    # Tables
    op.create_table(
        'products',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('sku', sa.String(100), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('type', postgresql.ENUM("finished_good", "semi_finished", "component", "material", name="product_type", create_type=False), nullable=False),
        sa.Column('unit', sa.String(50), nullable=False, server_default=sa.text("'pcs'")),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column('notes', sa.String(2000), nullable=True),
        sa.Column('profile_type', sa.String(100), nullable=True),
        sa.Column('alloy', sa.String(50), nullable=True),
        sa.Column('color', sa.String(50), nullable=True),
        sa.Column('anod_type', sa.String(50), nullable=True),
        sa.Column('length_mm', sa.Float(), nullable=True),
        sa.Column('weight_per_meter', sa.Float(), nullable=True),
        sa.Column('quantity_per_hanger', sa.Integer(), nullable=True),
        sa.Column('cross_section', sa.String(100), nullable=True),
        sa.Column('photo_thumb', sa.String(500), nullable=True),
        sa.Column('photo_full', sa.String(500), nullable=True),
        sa.Column('source', sa.String(50), nullable=True),
        sa.Column('is_catalog_item', sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column('is_paired_profile', sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column('skip_shot_blast', sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column('is_laminated', sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column('aliases', postgresql.ARRAY(sa.String()), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index('ix_products_sku', 'products', ['sku'], unique=True)
    op.create_index('ix_products_name', 'products', ['name'], unique=False)
    op.create_index('ix_products_profile_type', 'products', ['profile_type'], unique=False)
    op.create_index('ix_products_alloy', 'products', ['alloy'], unique=False)
    op.create_index('ix_products_color', 'products', ['color'], unique=False)
    op.create_index('ix_products_source', 'products', ['source'], unique=False)

    op.create_table(
        'product_lengths',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('product_id', sa.BigInteger(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('length_mm', sa.Float(), nullable=False),
        sa.CheckConstraint('length_mm > 0', name='ck_product_lengths_positive'),
        sa.UniqueConstraint('product_id', 'length_mm', name='uq_product_lengths_product_length'),
    )
    op.create_index('ix_product_lengths_product_id', 'product_lengths', ['product_id'])

    op.create_table(
        'processing_flags',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('code', sa.String(50), nullable=False, unique=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('section_scope', sa.String(50), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    op.create_table(
        'product_processing_flags',
        sa.Column('product_id', sa.BigInteger(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('flag_id', sa.BigInteger(), sa.ForeignKey('processing_flags.id'), nullable=False),
        sa.UniqueConstraint('product_id', 'flag_id', name='uq_product_flags_product_flag'),
    )
    op.create_index('ix_product_processing_flags_product_id', 'product_processing_flags', ['product_id'])

    # Seed processing flags
    flags_table = sa.table(
        'processing_flags',
        sa.column('code', sa.String),
        sa.column('name', sa.String),
        sa.column('section_scope', sa.String),
        sa.column('is_active', sa.Boolean),
    )
    op.bulk_insert(
        flags_table,
        [
            {"code": code, "name": name, "section_scope": scope, "is_active": True}
            for code, name, scope in PROCESSING_FLAGS
        ],
    )


def downgrade() -> None:
    op.drop_index('ix_product_processing_flags_product_id', table_name='product_processing_flags')
    op.drop_table('product_processing_flags')
    op.drop_index('ix_product_lengths_product_id', table_name='product_lengths')
    op.drop_table('product_lengths')
    op.drop_index('ix_products_source', table_name='products')
    op.drop_index('ix_products_color', table_name='products')
    op.drop_index('ix_products_alloy', table_name='products')
    op.drop_index('ix_products_profile_type', table_name='products')
    op.drop_index('ix_products_name', table_name='products')
    op.drop_index('ix_products_sku', table_name='products')
    op.drop_table('products')
    op.drop_table('processing_flags')
    sa.Enum(name='product_type').drop(op.get_bind(), checkfirst=True)
