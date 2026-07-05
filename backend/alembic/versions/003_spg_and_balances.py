"""spg_and_balances

Эпик: СПГ, привязка участков, кэш остатков
Irreversible: no

Revision ID: 003_spg_and_balances
Revises: 002_products_and_techcards
Create Date: 2026-07-05 19:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "003_spg_and_balances"
down_revision: Union[str, None] = "002_products_and_techcards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- SCHEMA ---
    op.create_table('storage_production_groups',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('storage_kind', sa.Enum('raw', 'wip', 'finished', name='spg_storage_kind'), server_default=sa.text("'wip'"), nullable=False),
    sa.Column('requires_lot', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('icon', sa.String(length=50), nullable=True),
    sa.Column('icon_color', sa.String(length=7), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_storage_production_groups')),
    sa.UniqueConstraint('code', name=op.f('uq_storage_production_groups_code'))
    )
    op.create_table('spg_sections',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('spg_id', sa.BigInteger(), nullable=False),
    sa.Column('section_id', sa.BigInteger(), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], name=op.f('fk_spg_sections_section_id_sections'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['spg_id'], ['storage_production_groups.id'], name=op.f('fk_spg_sections_spg_id_storage_production_groups'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_spg_sections')),
    sa.UniqueConstraint('spg_id', 'section_id', name='uq_spg_sections')
    )
    op.create_table('stock_balances',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False),
    sa.Column('product_id', sa.BigInteger(), nullable=False),
    sa.Column('location_id', sa.BigInteger(), nullable=False),
    sa.Column('quality_state', sa.Enum('good', 'scrap', 'rework', 'final_scrap', name='stock_quality_state'), server_default=sa.text("'good'"), nullable=False),
    sa.Column('balance_qty', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('refreshed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('balance_qty <> 0', name=op.f('ck_stock_balances_nonzero')),
    sa.ForeignKeyConstraint(['location_id'], ['sections.id'], name=op.f('fk_stock_balances_location_id_sections')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_stock_balances_product_id_products')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stock_balances')),
    sa.UniqueConstraint('product_id', 'location_id', 'quality_state', name='uq_stock_balances_product_location_quality')
    )
    op.create_index(op.f('ix_stock_balances_location_id'), 'stock_balances', ['location_id'], unique=False)
    op.create_index(op.f('ix_stock_balances_product_id'), 'stock_balances', ['product_id'], unique=False)

    # --- DATA ---
    pass

    # --- TRIGGERS ---
    pass


def downgrade() -> None:
    op.drop_table('stock_balances')
    op.drop_table('spg_sections')
    op.drop_table('storage_production_groups')
