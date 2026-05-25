"""shopfloor domain: defect_types, transfers, transfer_discrepancies, movements,
defects, defect_items, defect_decisions, rework_tasks, entity_comments,
attachments, attachment_links, transfer_discrepancy_defect_items

Revision ID: 007_shopfloor_domain
Revises: 006_import_domain
Create Date: 2026-05-25 12:06:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '007_shopfloor_domain'
down_revision: Union[str, None] = '006_import_domain'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ENUMs
    postgresql.ENUM("plan_position", "section_plan_line", "work_task", "transfer",
                     "transfer_discrepancy", "defect", "defect_item", "defect_decision",
                     "rework_task", name="entity_type").create(op.get_bind())
    postgresql.ENUM("draft", "sent", "accepted", "partially_accepted", "rejected", "cancelled",
                     name="transfer_status").create(op.get_bind())
    postgresql.ENUM("open", "partially_resolved", "resolved", "cancelled",
                     name="transfer_discrepancy_status").create(op.get_bind())
    postgresql.ENUM("issue_to_work", "complete", "transfer_send", "transfer_receive",
                     "reject", "scrap", "return_to_previous", "final_release", "adjustment",
                     name="movement_type").create(op.get_bind())
    postgresql.ENUM("open", "decision_required", "rework_task_created", "scrapped",
                     "returned", "accepted_with_deviation", "closed",
                     name="defect_status").create(op.get_bind())
    postgresql.ENUM("scrap", "rework_current", "return_previous", "quality_hold",
                     "accept_with_deviation", name="defect_decision_type").create(op.get_bind())
    postgresql.ENUM("open", "in_progress", "completed", "cancelled",
                     name="rework_task_status").create(op.get_bind())

    entity_type = postgresql.ENUM(name="entity_type", create_type=False)

    # defect_types
    op.create_table('defect_types',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('code', sa.String(100), nullable=False, unique=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('category', sa.String(100), nullable=True),
        sa.Column('severity', sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column('requires_quality_decision', sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # transfers
    op.create_table('transfers',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('transfer_no', sa.String(100), nullable=False, unique=True),
        sa.Column('from_task_id', sa.BigInteger(), sa.ForeignKey('work_tasks.id'), nullable=False),
        sa.Column('to_task_id', sa.BigInteger(), sa.ForeignKey('work_tasks.id'), nullable=False),
        sa.Column('from_section_id', sa.BigInteger(), sa.ForeignKey('sections.id'), nullable=False),
        sa.Column('to_section_id', sa.BigInteger(), sa.ForeignKey('sections.id'), nullable=False),
        sa.Column('product_id', sa.BigInteger(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('sent_quantity', sa.Numeric(14, 3), nullable=False),
        sa.Column('accepted_quantity', sa.Numeric(14, 3), nullable=True),
        sa.Column('rejected_quantity', sa.Numeric(14, 3), nullable=True),
        sa.Column('status', sa.Enum("draft", "sent", "accepted", "partially_accepted", "rejected", "cancelled", name="transfer_status"), nullable=False, server_default=sa.text("'draft'")),
        sa.Column('idempotency_key', sa.String(128), nullable=True),
        sa.Column('sent_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('accepted_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('sent_quantity > 0', name='ck_transfers_sent_quantity_positive'),
        sa.CheckConstraint('accepted_quantity IS NULL OR accepted_quantity >= 0', name='ck_transfers_accepted_quantity_non_negative'),
        sa.CheckConstraint('rejected_quantity IS NULL OR rejected_quantity >= 0', name='ck_transfers_rejected_quantity_non_negative'),
    )

    # transfer_discrepancies
    op.create_table('transfer_discrepancies',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('transfer_id', sa.BigInteger(), sa.ForeignKey('transfers.id'), nullable=False),
        sa.Column('discrepancy_quantity', sa.Numeric(14, 3), nullable=False),
        sa.Column('resolved_quantity', sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column('unresolved_quantity', sa.Numeric(14, 3), nullable=False),
        sa.Column('status', sa.Enum("open", "partially_resolved", "resolved", "cancelled", name="transfer_discrepancy_status"), nullable=False, server_default=sa.text("'open'")),
        sa.Column('reason', sa.String(255), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('discrepancy_quantity > 0', name='ck_transfer_discrepancy_qty_positive'),
        sa.CheckConstraint('resolved_quantity >= 0', name='ck_transfer_discrepancy_resolved_non_negative'),
        sa.CheckConstraint('unresolved_quantity >= 0', name='ck_transfer_discrepancy_unresolved_non_negative'),
    )

    # movements
    op.create_table('movements',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('product_id', sa.BigInteger(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('task_id', sa.BigInteger(), sa.ForeignKey('work_tasks.id'), nullable=True),
        sa.Column('section_plan_line_id', sa.BigInteger(), sa.ForeignKey('section_plan_lines.id'), nullable=True),
        sa.Column('transfer_id', sa.BigInteger(), sa.ForeignKey('transfers.id'), nullable=True),
        sa.Column('from_section_id', sa.BigInteger(), sa.ForeignKey('sections.id'), nullable=True),
        sa.Column('to_section_id', sa.BigInteger(), sa.ForeignKey('sections.id'), nullable=True),
        sa.Column('movement_type', sa.Enum("issue_to_work", "complete", "transfer_send", "transfer_receive", "reject", "scrap", "return_to_previous", "final_release", "adjustment", name="movement_type"), nullable=False),
        sa.Column('quantity', sa.Numeric(14, 3), nullable=False),
        sa.Column('source_ref', sa.String(255), nullable=True),
        sa.Column('idempotency_key', sa.String(128), nullable=True),
        sa.Column('reason', sa.String(255), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('executor_user_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('performed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('accounted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('quantity > 0', name='ck_movements_quantity_positive'),
    )
    op.create_index('ix_movements_task_created_at', 'movements', ['task_id', 'created_at'])
    op.create_index('ix_movements_performed_at', 'movements', ['performed_at'])

    # defects
    op.create_table('defects',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('product_id', sa.BigInteger(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('section_id', sa.BigInteger(), sa.ForeignKey('sections.id'), nullable=False),
        sa.Column('task_id', sa.BigInteger(), sa.ForeignKey('work_tasks.id'), nullable=False),
        sa.Column('movement_id', sa.BigInteger(), sa.ForeignKey('movements.id'), nullable=True),
        sa.Column('status', sa.Enum("open", "decision_required", "rework_task_created", "scrapped", "returned", "accepted_with_deviation", "closed", name="defect_status"), nullable=False, server_default=sa.text("'open'")),
        sa.Column('responsible_section_id', sa.BigInteger(), sa.ForeignKey('sections.id'), nullable=True),
        sa.Column('idempotency_key', sa.String(128), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # defect_items
    op.create_table('defect_items',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('defect_id', sa.BigInteger(), sa.ForeignKey('defects.id'), nullable=False),
        sa.Column('defect_type_id', sa.BigInteger(), sa.ForeignKey('defect_types.id'), nullable=True),
        sa.Column('defect_type_code_snapshot', sa.String(100), nullable=True),
        sa.Column('defect_type_name_snapshot', sa.String(255), nullable=True),
        sa.Column('subtype_code', sa.String(100), nullable=True),
        sa.Column('reason_code', sa.String(100), nullable=True),
        sa.Column('quantity', sa.Numeric(14, 3), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('quantity > 0', name='ck_defect_items_qty_positive'),
    )

    # defect_decisions
    op.create_table('defect_decisions',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('defect_id', sa.BigInteger(), sa.ForeignKey('defects.id'), nullable=False),
        sa.Column('decision_type', sa.Enum("scrap", "rework_current", "return_previous", "quality_hold", "accept_with_deviation", name="defect_decision_type"), nullable=False),
        sa.Column('quantity', sa.Numeric(14, 3), nullable=False),
        sa.Column('target_section_id', sa.BigInteger(), sa.ForeignKey('sections.id'), nullable=True),
        sa.Column('reason', sa.String(255), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('idempotency_key', sa.String(128), nullable=True),
        sa.Column('decided_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('quantity > 0', name='ck_defect_decisions_qty_positive'),
    )

    # rework_tasks
    op.create_table('rework_tasks',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('defect_id', sa.BigInteger(), sa.ForeignKey('defects.id'), nullable=False),
        sa.Column('source_task_id', sa.BigInteger(), sa.ForeignKey('work_tasks.id'), nullable=False),
        sa.Column('section_id', sa.BigInteger(), sa.ForeignKey('sections.id'), nullable=False),
        sa.Column('product_id', sa.BigInteger(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('quantity', sa.Numeric(14, 3), nullable=False),
        sa.Column('status', sa.Enum("open", "in_progress", "completed", "cancelled", name="rework_task_status"), nullable=False, server_default=sa.text("'open'")),
        sa.Column('idempotency_key', sa.String(128), nullable=True),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('quantity > 0', name='ck_rework_tasks_qty_positive'),
    )

    # entity_comments
    op.create_table('entity_comments',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('entity_type', entity_type, nullable=False),
        sa.Column('entity_id', sa.BigInteger(), nullable=False),
        sa.Column('comment_type', sa.String(50), nullable=False, server_default=sa.text("'note'")),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('is_internal', sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column('idempotency_key', sa.String(128), nullable=True),
        sa.Column('author_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_entity_comments_entity', 'entity_comments', ['entity_type', 'entity_id', 'created_at'])

    # attachments
    op.create_table('attachments',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('original_filename', sa.String(500), nullable=False),
        sa.Column('stored_path', sa.String(1000), nullable=False),
        sa.Column('content_type', sa.String(255), nullable=True),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('file_sha256', sa.String(64), nullable=True),
        sa.Column('idempotency_key', sa.String(128), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # attachment_links
    op.create_table('attachment_links',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('attachment_id', sa.BigInteger(), sa.ForeignKey('attachments.id'), nullable=False),
        sa.Column('entity_type', entity_type, nullable=False),
        sa.Column('entity_id', sa.BigInteger(), nullable=False),
        sa.Column('caption', sa.Text(), nullable=True),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('attachment_id', 'entity_type', 'entity_id', name='uq_attachment_links_target'),
    )

    # transfer_discrepancy_defect_items
    op.create_table('transfer_discrepancy_defect_items',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('transfer_discrepancy_id', sa.BigInteger(), sa.ForeignKey('transfer_discrepancies.id'), nullable=False),
        sa.Column('defect_item_id', sa.BigInteger(), sa.ForeignKey('defect_items.id'), nullable=False),
        sa.Column('quantity', sa.Numeric(14, 3), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('quantity > 0', name='ck_discrepancy_defect_item_qty_positive'),
    )


def downgrade() -> None:
    op.drop_table('transfer_discrepancy_defect_items')
    op.drop_table('attachment_links')
    op.drop_table('attachments')
    op.drop_index('ix_entity_comments_entity', table_name='entity_comments')
    op.drop_table('entity_comments')
    op.drop_table('rework_tasks')
    op.drop_table('defect_decisions')
    op.drop_table('defect_items')
    op.drop_table('defects')
    op.drop_index('ix_movements_performed_at', table_name='movements')
    op.drop_index('ix_movements_task_created_at', table_name='movements')
    op.drop_table('movements')
    op.drop_table('transfer_discrepancies')
    op.drop_table('transfers')
    op.drop_table('defect_types')

    sa.Enum(name='rework_task_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='defect_decision_type').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='defect_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='movement_type').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='transfer_discrepancy_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='transfer_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='entity_type').drop(op.get_bind(), checkfirst=True)
