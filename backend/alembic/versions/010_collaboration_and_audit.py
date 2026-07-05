"""collaboration_and_audit

Эпик: Комментарии, вложения, аудит
Irreversible: no

Revision ID: 010_collaboration_and_audit
Revises: 009_quality_and_defects
Create Date: 2026-07-05 19:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "010_collaboration_and_audit"
down_revision: Union[str, None] = "009_quality_and_defects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- SCHEMA ---
    op.create_table('attachments',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('original_filename', sa.String(length=500), nullable=False),
    sa.Column('stored_path', sa.String(length=1000), nullable=False),
    sa.Column('content_type', sa.String(length=255), nullable=True),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('file_sha256', sa.String(length=64), nullable=True),
    sa.Column('idempotency_key', sa.String(length=128), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_attachments_created_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attachments'))
    )
    op.create_table('entity_comments',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('entity_type', sa.Enum('plan_position', 'section_plan_line', 'work_task', 'transfer', 'transfer_discrepancy', 'defect', 'defect_item', 'defect_decision', 'rework_task', name='entity_type'), nullable=False),
    sa.Column('entity_id', sa.BigInteger(), nullable=False),
    sa.Column('comment_type', sa.String(length=50), server_default=sa.text("'note'"), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('is_internal', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('idempotency_key', sa.String(length=128), nullable=True),
    sa.Column('author_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=op.f('fk_entity_comments_author_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_entity_comments'))
    )
    op.create_table('attachment_links',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('attachment_id', sa.BigInteger(), nullable=False),
    sa.Column('entity_type', sa.Enum('plan_position', 'section_plan_line', 'work_task', 'transfer', 'transfer_discrepancy', 'defect', 'defect_item', 'defect_decision', 'rework_task', name='entity_type'), nullable=False),
    sa.Column('entity_id', sa.BigInteger(), nullable=False),
    sa.Column('caption', sa.Text(), nullable=True),
    sa.Column('created_by', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['attachment_id'], ['attachments.id'], name=op.f('fk_attachment_links_attachment_id_attachments')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_attachment_links_created_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attachment_links')),
    sa.UniqueConstraint('attachment_id', 'entity_type', 'entity_id', name='uq_attachment_links_target')
    )
    op.create_table('audit_logs',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=True),
    sa.Column('user_name', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('action', sa.String(length=50), nullable=True),
    sa.Column('entity_type', sa.String(length=50), nullable=True),
    sa.Column('entity_id', sa.BigInteger(), nullable=True),
    sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('section_id', sa.BigInteger(), nullable=True),
    sa.Column('section_name', sa.String(length=255), nullable=True),
    sa.Column('section_code', sa.String(length=255), nullable=True),
    sa.Column('task_ids', sa.Text(), nullable=True),
    sa.Column('product_sku', sa.String(length=255), nullable=True),
    sa.Column('operation_name', sa.String(length=255), nullable=True),
    sa.Column('qty_text', sa.String(length=100), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('error_details', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], name=op.f('fk_audit_logs_section_id_sections'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_audit_logs_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )

    # --- DATA ---
    pass

    # --- TRIGGERS ---
    pass


def downgrade() -> None:
    op.drop_table('audit_logs')
    op.drop_table('attachment_links')
    op.drop_table('entity_comments')
    op.drop_table('attachments')
