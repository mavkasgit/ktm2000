"""transfers

Эпик: Передачи между участками, расхождения
Irreversible: no

Revision ID: 007_transfers
Revises: 006_release_and_shopfloor
Create Date: 2026-07-05 19:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "007_transfers"
down_revision: Union[str, None] = "006_release_and_shopfloor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- SCHEMA ---
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
    sa.Column('is_post_factum', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('physical_handover_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('accepted_quantity IS NULL OR accepted_quantity >= 0', name=op.f('ck_transfers_accepted_quantity_non_negative')),
    sa.CheckConstraint('rejected_quantity IS NULL OR rejected_quantity >= 0', name=op.f('ck_transfers_rejected_quantity_non_negative')),
    sa.CheckConstraint('sent_quantity > 0', name=op.f('ck_transfers_sent_quantity_positive')),
    sa.ForeignKeyConstraint(['accepted_by'], ['users.id'], name=op.f('fk_transfers_accepted_by_users')),
    sa.ForeignKeyConstraint(['from_section_id'], ['sections.id'], name=op.f('fk_transfers_from_section_id_sections')),
    sa.ForeignKeyConstraint(['from_task_id'], ['work_tasks.id'], name=op.f('fk_transfers_from_task_id_work_tasks')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_transfers_product_id_products')),
    sa.ForeignKeyConstraint(['sent_by'], ['users.id'], name=op.f('fk_transfers_sent_by_users')),
    sa.ForeignKeyConstraint(['to_section_id'], ['sections.id'], name=op.f('fk_transfers_to_section_id_sections')),
    sa.ForeignKeyConstraint(['to_task_id'], ['work_tasks.id'], name=op.f('fk_transfers_to_task_id_work_tasks')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_transfers')),
    sa.UniqueConstraint('transfer_no', name=op.f('uq_transfers_transfer_no'))
    )
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
    sa.CheckConstraint('discrepancy_quantity > 0', name=op.f('ck_transfer_discrepancies_qty_positive')),
    sa.CheckConstraint('resolved_quantity >= 0', name=op.f('ck_transfer_discrepancies_resolved_non_negative')),
    sa.CheckConstraint('unresolved_quantity >= 0', name=op.f('ck_transfer_discrepancies_unresolved_non_negative')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_transfer_discrepancies_created_by_users')),
    sa.ForeignKeyConstraint(['transfer_id'], ['transfers.id'], name=op.f('fk_transfer_discrepancies_transfer_id_transfers')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_transfer_discrepancies'))
    )

    # --- DATA ---
    pass

    # --- TRIGGERS ---
    pass


def downgrade() -> None:
    op.drop_table('transfer_discrepancies')
    op.drop_table('transfers')
