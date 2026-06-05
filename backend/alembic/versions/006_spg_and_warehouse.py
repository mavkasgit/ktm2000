"""spg and warehouse

Revision ID: 006_spg_and_warehouse
Revises: 005_shopfloor_and_tasks
Create Date: 2026-06-05 15:05:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '006_spg_and_warehouse'
down_revision: Union[str, None] = '005_shopfloor_and_tasks'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create storage_production_groups
    op.create_table('storage_production_groups',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('storage_kind', sa.Enum('raw', 'wip', 'finished', 'quarantine', name='spg_storage_kind'), server_default=sa.text("'wip'"), nullable=False),
        sa.Column('requires_lot', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('icon', sa.String(length=50), nullable=True),
        sa.Column('icon_color', sa.String(length=7), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )

    # 2. Create spg_sections
    op.create_table('spg_sections',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('spg_id', sa.BigInteger(), nullable=False),
        sa.Column('section_id', sa.BigInteger(), nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.ForeignKeyConstraint(['section_id'], ['sections.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['spg_id'], ['storage_production_groups.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('spg_id', 'section_id', name='uq_spg_sections')
    )

    # 3. Create spg_remainders
    op.create_table('spg_remainders',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('product_id', sa.BigInteger(), nullable=False),
        sa.Column('spg_id', sa.BigInteger(), nullable=False),
        sa.Column('route_stage_id', sa.BigInteger(), nullable=True),
        sa.Column('section_plan_line_id', sa.BigInteger(), nullable=True),
        sa.Column('origin_task_id', sa.BigInteger(), nullable=True),
        sa.Column('remainder_quantity', sa.Numeric(precision=14, scale=3), server_default=sa.text('0'), nullable=False),
        sa.Column('original_issued', sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column('completed_stages_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('source', sa.String(length=20), server_default=sa.text("'task'"), nullable=False),
        sa.Column('created_by', sa.BigInteger(), nullable=True),
        sa.Column('created_by_user_name', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('consumed_by_task_id', sa.BigInteger(), nullable=True),
        sa.Column('reserved_for_plan_position_id', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['consumed_by_task_id'], ['work_tasks.id'], ),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['origin_task_id'], ['work_tasks.id'], ),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.ForeignKeyConstraint(['reserved_for_plan_position_id'], ['plan_positions.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['route_stage_id'], ['route_stages.id'], ),
        sa.ForeignKeyConstraint(['section_plan_line_id'], ['section_plan_lines.id'], ),
        sa.ForeignKeyConstraint(['spg_id'], ['storage_production_groups.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # 4. Create transfers
    op.create_table('transfers',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('transfer_no', sa.String(length=100), nullable=False),
        sa.Column('from_task_id', sa.BigInteger(), nullable=False),
        sa.Column('to_task_id', sa.BigInteger(), nullable=False),
        sa.Column('from_section_id', sa.BigInteger(), nullable=False),
        sa.Column('to_section_id', sa.BigInteger(), nullable=False),
        sa.Column('product_id', sa.BigInteger(), nullable=False),
        sa.Column('sent_quantity', sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column('accepted_quantity', sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column('rejected_quantity', sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column('status', sa.Enum('draft', 'sent', 'accepted', 'partially_accepted', 'rejected', 'cancelled', name='transfer_status'), server_default=sa.text("'draft'"), nullable=False),
        sa.Column('idempotency_key', sa.String(length=128), nullable=True),
        sa.Column('sent_by', sa.BigInteger(), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('accepted_by', sa.BigInteger(), nullable=True),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('accepted_quantity IS NULL OR accepted_quantity >= 0', name='ck_transfers_accepted_quantity_non_negative'),
        sa.CheckConstraint('rejected_quantity IS NULL OR rejected_quantity >= 0', name='ck_transfers_rejected_quantity_non_negative'),
        sa.CheckConstraint('sent_quantity > 0', name='ck_transfers_sent_quantity_positive'),
        sa.ForeignKeyConstraint(['accepted_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['from_section_id'], ['sections.id'], ),
        sa.ForeignKeyConstraint(['from_task_id'], ['work_tasks.id'], ),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.ForeignKeyConstraint(['sent_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['to_section_id'], ['sections.id'], ),
        sa.ForeignKeyConstraint(['to_task_id'], ['work_tasks.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('transfer_no')
    )

    # 5. Create movements
    op.create_table('movements',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('product_id', sa.BigInteger(), nullable=False),
        sa.Column('task_id', sa.BigInteger(), nullable=True),
        sa.Column('section_plan_line_id', sa.BigInteger(), nullable=True),
        sa.Column('transfer_id', sa.BigInteger(), nullable=True),
        sa.Column('from_section_id', sa.BigInteger(), nullable=True),
        sa.Column('to_section_id', sa.BigInteger(), nullable=True),
        sa.Column('movement_type', sa.Enum('issue_to_work', 'complete', 'transfer_send', 'transfer_receive', 'reject', 'scrap', 'return_to_previous', 'final_release', 'adjustment', 'return_to_stock', 'manual_in', 'manual_out', name='movement_type'), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column('source_ref', sa.String(length=255), nullable=True),
        sa.Column('idempotency_key', sa.String(length=128), nullable=True),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_by', sa.BigInteger(), nullable=False),
        sa.Column('executor_user_id', sa.BigInteger(), nullable=True),
        sa.Column('created_by_user_name', sa.String(length=255), nullable=True),
        sa.Column('executor_user_name', sa.String(length=255), nullable=True),
        sa.Column('performed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('accounted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('quantity > 0', name='ck_movements_quantity_positive'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['executor_user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['from_section_id'], ['sections.id'], ),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.ForeignKeyConstraint(['section_plan_line_id'], ['section_plan_lines.id'], ),
        sa.ForeignKeyConstraint(['task_id'], ['work_tasks.id'], ),
        sa.ForeignKeyConstraint(['to_section_id'], ['sections.id'], ),
        sa.ForeignKeyConstraint(['transfer_id'], ['transfers.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # 6. Create transfer_discrepancies
    op.create_table('transfer_discrepancies',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('transfer_id', sa.BigInteger(), nullable=False),
        sa.Column('discrepancy_quantity', sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column('resolved_quantity', sa.Numeric(precision=14, scale=3), server_default=sa.text('0'), nullable=False),
        sa.Column('unresolved_quantity', sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column('status', sa.Enum('open', 'partially_resolved', 'resolved', 'cancelled', name='transfer_discrepancy_status'), server_default=sa.text("'open'"), nullable=False),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_by', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('discrepancy_quantity > 0', name='ck_transfer_discrepancy_qty_positive'),
        sa.CheckConstraint('resolved_quantity >= 0', name='ck_transfer_discrepancy_resolved_non_negative'),
        sa.CheckConstraint('unresolved_quantity >= 0', name='ck_transfer_discrepancy_unresolved_non_negative'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['transfer_id'], ['transfers.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('transfer_discrepancies')
    sa.Enum(name='transfer_discrepancy_status').drop(op.get_bind(), checkfirst=False)
    op.drop_table('movements')
    sa.Enum(name='movement_type').drop(op.get_bind(), checkfirst=False)
    op.drop_table('transfers')
    sa.Enum(name='transfer_status').drop(op.get_bind(), checkfirst=False)
    op.drop_table('spg_remainders')
    op.drop_table('spg_sections')
    op.drop_table('storage_production_groups')
    sa.Enum(name='spg_storage_kind').drop(op.get_bind(), checkfirst=False)
