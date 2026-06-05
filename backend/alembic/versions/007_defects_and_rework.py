"""defects and rework

Revision ID: 007_defects_and_rework
Revises: 006_spg_and_warehouse
Create Date: 2026-06-05 15:06:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '007_defects_and_rework'
down_revision: Union[str, None] = '006_spg_and_warehouse'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create defect_types
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
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )

    # 2. Create defects
    op.create_table('defects',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('product_id', sa.BigInteger(), nullable=False),
        sa.Column('section_id', sa.BigInteger(), nullable=False),
        sa.Column('task_id', sa.BigInteger(), nullable=False),
        sa.Column('movement_id', sa.BigInteger(), nullable=True),
        sa.Column('status', sa.Enum('open', 'decision_required', 'rework_task_created', 'scrapped', 'returned', 'accepted_with_deviation', 'closed', name='defect_status'), server_default=sa.text("'open'"), nullable=False),
        sa.Column('responsible_section_id', sa.BigInteger(), nullable=True),
        sa.Column('idempotency_key', sa.String(length=128), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_by', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['movement_id'], ['movements.id'], ),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.ForeignKeyConstraint(['responsible_section_id'], ['sections.id'], ),
        sa.ForeignKeyConstraint(['section_id'], ['sections.id'], ),
        sa.ForeignKeyConstraint(['task_id'], ['work_tasks.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # 3. Create defect_decisions
    op.create_table('defect_decisions',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('defect_id', sa.BigInteger(), nullable=False),
        sa.Column('decision_type', sa.Enum('scrap', 'rework_current', 'return_previous', 'quality_hold', 'accept_with_deviation', name='defect_decision_type'), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column('target_section_id', sa.BigInteger(), nullable=True),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('idempotency_key', sa.String(length=128), nullable=True),
        sa.Column('decided_by', sa.BigInteger(), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('quantity > 0', name='ck_defect_decisions_qty_positive'),
        sa.ForeignKeyConstraint(['decided_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['defect_id'], ['defects.id'], ),
        sa.ForeignKeyConstraint(['target_section_id'], ['sections.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # 4. Create defect_items
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
        sa.CheckConstraint('quantity > 0', name='ck_defect_items_qty_positive'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['defect_id'], ['defects.id'], ),
        sa.ForeignKeyConstraint(['defect_type_id'], ['defect_types.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # 5. Create rework_tasks
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
        sa.CheckConstraint('quantity > 0', name='ck_rework_tasks_qty_positive'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['defect_id'], ['defects.id'], ),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.ForeignKeyConstraint(['section_id'], ['sections.id'], ),
        sa.ForeignKeyConstraint(['source_task_id'], ['work_tasks.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # 6. Create transfer_discrepancy_defect_items
    op.create_table('transfer_discrepancy_defect_items',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('transfer_discrepancy_id', sa.BigInteger(), nullable=False),
        sa.Column('defect_item_id', sa.BigInteger(), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_by', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('quantity > 0', name='ck_discrepancy_defect_item_qty_positive'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['defect_item_id'], ['defect_items.id'], ),
        sa.ForeignKeyConstraint(['transfer_discrepancy_id'], ['transfer_discrepancies.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('transfer_discrepancy_defect_items')
    op.drop_table('rework_tasks')
    sa.Enum(name='rework_task_status').drop(op.get_bind(), checkfirst=False)
    op.drop_table('defect_items')
    op.drop_table('defect_decisions')
    sa.Enum(name='defect_decision_type').drop(op.get_bind(), checkfirst=False)
    op.drop_table('defects')
    sa.Enum(name='defect_status').drop(op.get_bind(), checkfirst=False)
    op.drop_table('defect_types')
