"""stock_ledger

Эпик: Append-only ledger движений материала
Irreversible: no

Revision ID: 008_stock_ledger
Revises: 007_transfers
Create Date: 2026-07-05 19:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "008_stock_ledger"
down_revision: Union[str, None] = "007_transfers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- SCHEMA ---
    op.create_table('stock_transactions',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False),
    sa.Column('product_id', sa.BigInteger(), nullable=False),
    sa.Column('from_location_id', sa.BigInteger(), nullable=True),
    sa.Column('to_location_id', sa.BigInteger(), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('reason', sa.Enum('issue_to_work', 'complete', 'transfer_send', 'transfer_receive', 'return_to_stock', 'return_to_previous', 'final_release', 'scrap', 'rework', 'adjustment_in', 'adjustment_out', 'manual_in', 'manual_out', name='stock_reason'), nullable=False),
    sa.Column('from_quality_state', sa.Enum('good', 'scrap', 'rework', 'final_scrap', name='stock_quality_state'), server_default=sa.text("'good'"), nullable=False),
    sa.Column('to_quality_state', sa.Enum('good', 'scrap', 'rework', 'final_scrap', name='stock_quality_state'), server_default=sa.text("'good'"), nullable=False),
    sa.Column('task_id', sa.BigInteger(), nullable=True),
    sa.Column('transfer_id', sa.BigInteger(), nullable=True),
    sa.Column('section_plan_line_id', sa.BigInteger(), nullable=True),
    sa.Column('compensates_tx_id', sa.BigInteger(), nullable=True),
    sa.Column('source_ref', sa.String(length=255), nullable=True),
    sa.Column('idempotency_key', sa.String(length=128), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('created_by', sa.BigInteger(), nullable=False),
    sa.Column('executor_user_id', sa.BigInteger(), nullable=True),
    sa.Column('created_by_user_name', sa.String(length=255), nullable=True),
    sa.Column('executor_user_name', sa.String(length=255), nullable=True),
    sa.Column('performed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('accounted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_post_factum', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(from_location_id IS NOT NULL) OR (to_location_id IS NOT NULL) OR (reason = 'transfer_receive')", name=op.f('ck_stock_transactions_at_least_one_location')),
    sa.CheckConstraint("from_location_id IS NULL OR to_location_id IS NULL OR from_location_id <> to_location_id OR reason = 'complete'", name=op.f('ck_stock_transactions_locations_differ')),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_stock_transactions_quantity_positive')),
    sa.ForeignKeyConstraint(['compensates_tx_id'], ['stock_transactions.id'], name=op.f('fk_stock_transactions_compensates_tx_id_stock_transactions')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_stock_transactions_created_by_users')),
    sa.ForeignKeyConstraint(['executor_user_id'], ['users.id'], name=op.f('fk_stock_transactions_executor_user_id_users')),
    sa.ForeignKeyConstraint(['from_location_id'], ['sections.id'], name=op.f('fk_stock_transactions_from_location_id_sections')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_stock_transactions_product_id_products')),
    sa.ForeignKeyConstraint(['section_plan_line_id'], ['section_plan_lines.id'], name=op.f('fk_stock_transactions_section_plan_line_id_section_plan_lines')),
    sa.ForeignKeyConstraint(['task_id'], ['work_tasks.id'], name=op.f('fk_stock_transactions_task_id_work_tasks')),
    sa.ForeignKeyConstraint(['to_location_id'], ['sections.id'], name=op.f('fk_stock_transactions_to_location_id_sections')),
    sa.ForeignKeyConstraint(['transfer_id'], ['transfers.id'], name=op.f('fk_stock_transactions_transfer_id_transfers')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stock_transactions'))
    )
    op.create_index(op.f('ix_stock_transactions_from_location_id'), 'stock_transactions', ['from_location_id'], unique=False)
    op.create_index(op.f('ix_stock_transactions_from_quality_state'), 'stock_transactions', ['from_quality_state'], unique=False)
    op.create_index(op.f('ix_stock_transactions_idempotency_key'), 'stock_transactions', ['idempotency_key'], unique=False)
    op.create_index(op.f('ix_stock_transactions_product_id'), 'stock_transactions', ['product_id'], unique=False)
    op.create_index(op.f('ix_stock_transactions_reason'), 'stock_transactions', ['reason'], unique=False)
    op.create_index(op.f('ix_stock_transactions_task_id'), 'stock_transactions', ['task_id'], unique=False)
    op.create_index(op.f('ix_stock_transactions_to_location_id'), 'stock_transactions', ['to_location_id'], unique=False)
    op.create_index(op.f('ix_stock_transactions_to_quality_state'), 'stock_transactions', ['to_quality_state'], unique=False)
    op.create_index(op.f('ix_stock_transactions_transfer_id'), 'stock_transactions', ['transfer_id'], unique=False)

    # --- DATA ---
    pass

    # --- TRIGGERS ---
    pass


def downgrade() -> None:
    op.drop_table('stock_transactions')
