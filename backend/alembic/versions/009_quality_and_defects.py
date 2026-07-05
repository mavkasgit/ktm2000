"""quality_and_defects

Эпик: Брак, решения, переделки
Irreversible: no

Revision ID: 009_quality_and_defects
Revises: 008_stock_ledger
Create Date: 2026-07-05 19:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "009_quality_and_defects"
down_revision: Union[str, None] = "008_stock_ledger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- SCHEMA ---
    op.create_table('defect_types',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('category', sa.String(length=100), nullable=True),
    sa.Column('severity', sa.BigInteger(), server_default=sa.text('1'), nullable=False),
    sa.Column('requires_quality_decision', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_defect_types')),
    sa.UniqueConstraint('code', name=op.f('uq_defect_types_code'))
    )
    op.create_table('defects',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('product_id', sa.BigInteger(), nullable=False),
    sa.Column('section_id', sa.BigInteger(), nullable=False),
    sa.Column('task_id', sa.BigInteger(), nullable=True),
    sa.Column('route_stage_id', sa.BigInteger(), nullable=True),
    sa.Column('stock_transaction_id', sa.BigInteger(), nullable=True),
    sa.Column('status', sa.Enum('open', 'decision_required', 'rework_task_created', 'scrapped', 'returned', 'accepted_with_deviation', 'closed', name='defect_status'), server_default=sa.text("'open'"), nullable=False),
    sa.Column('responsible_section_id', sa.BigInteger(), nullable=True),
    sa.Column('idempotency_key', sa.String(length=128), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('created_by', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_defects_created_by_users')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_defects_product_id_products')),
    sa.ForeignKeyConstraint(['responsible_section_id'], ['sections.id'], name=op.f('fk_defects_responsible_section_id_sections')),
    sa.ForeignKeyConstraint(['route_stage_id'], ['route_stages.id'], name=op.f('fk_defects_route_stage_id_route_stages'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], name=op.f('fk_defects_section_id_sections')),
    sa.ForeignKeyConstraint(['stock_transaction_id'], ['stock_transactions.id'], name=op.f('fk_defects_stock_transaction_id_stock_transactions')),
    sa.ForeignKeyConstraint(['task_id'], ['work_tasks.id'], name=op.f('fk_defects_task_id_work_tasks')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_defects'))
    )
    op.create_table('defect_decisions',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('defect_id', sa.BigInteger(), nullable=False),
    sa.Column('decision_type', sa.Enum('scrap', 'rework_current', 'return_previous', 'accept_with_deviation', name='defect_decision_type'), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('target_section_id', sa.BigInteger(), nullable=True),
    sa.Column('reason', sa.String(length=255), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('idempotency_key', sa.String(length=128), nullable=True),
    sa.Column('decided_by', sa.BigInteger(), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_defect_decisions_qty_positive')),
    sa.ForeignKeyConstraint(['decided_by'], ['users.id'], name=op.f('fk_defect_decisions_decided_by_users')),
    sa.ForeignKeyConstraint(['defect_id'], ['defects.id'], name=op.f('fk_defect_decisions_defect_id_defects')),
    sa.ForeignKeyConstraint(['target_section_id'], ['sections.id'], name=op.f('fk_defect_decisions_target_section_id_sections')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_defect_decisions'))
    )
    op.create_table('defect_items',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('defect_id', sa.BigInteger(), nullable=False),
    sa.Column('defect_type_id', sa.BigInteger(), nullable=True),
    sa.Column('defect_type_code_snapshot', sa.String(length=100), nullable=True),
    sa.Column('defect_type_name_snapshot', sa.String(length=255), nullable=True),
    sa.Column('subtype_code', sa.String(length=100), nullable=True),
    sa.Column('reason_code', sa.String(length=100), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_by', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_defect_items_qty_positive')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_defect_items_created_by_users')),
    sa.ForeignKeyConstraint(['defect_id'], ['defects.id'], name=op.f('fk_defect_items_defect_id_defects')),
    sa.ForeignKeyConstraint(['defect_type_id'], ['defect_types.id'], name=op.f('fk_defect_items_defect_type_id_defect_types')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_defect_items'))
    )
    op.create_table('rework_tasks',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('defect_id', sa.BigInteger(), nullable=False),
    sa.Column('source_task_id', sa.BigInteger(), nullable=False),
    sa.Column('section_id', sa.BigInteger(), nullable=False),
    sa.Column('product_id', sa.BigInteger(), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('status', sa.Enum('open', 'in_progress', 'completed', 'cancelled', name='rework_task_status'), server_default=sa.text("'open'"), nullable=False),
    sa.Column('idempotency_key', sa.String(length=128), nullable=True),
    sa.Column('created_by', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_rework_tasks_qty_positive')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_rework_tasks_created_by_users')),
    sa.ForeignKeyConstraint(['defect_id'], ['defects.id'], name=op.f('fk_rework_tasks_defect_id_defects')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_rework_tasks_product_id_products')),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], name=op.f('fk_rework_tasks_section_id_sections')),
    sa.ForeignKeyConstraint(['source_task_id'], ['work_tasks.id'], name=op.f('fk_rework_tasks_source_task_id_work_tasks')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rework_tasks'))
    )
    op.create_table('transfer_discrepancy_defect_items',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('transfer_discrepancy_id', sa.BigInteger(), nullable=False),
    sa.Column('defect_item_id', sa.BigInteger(), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('created_by', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_transfer_discrepancy_defect_items_qty_positive')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_transfer_discrepancy_defect_items_created_by_users')),
    sa.ForeignKeyConstraint(['defect_item_id'], ['defect_items.id'], name=op.f('fk_transfer_discrepancy_defect_items_defect_item_id_defect_items')),
    sa.ForeignKeyConstraint(['transfer_discrepancy_id'], ['transfer_discrepancies.id'], name=op.f('fk_transfer_discrepancy_defect_items_transfer_discrepancy_id_transfer_discrepancies')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_transfer_discrepancy_defect_items'))
    )

    # --- DATA ---
    pass

    # --- TRIGGERS ---
    pass


def downgrade() -> None:
    op.drop_table('transfer_discrepancy_defect_items')
    op.drop_table('rework_tasks')
    op.drop_table('defect_items')
    op.drop_table('defect_decisions')
    op.drop_table('defects')
    op.drop_table('defect_types')
