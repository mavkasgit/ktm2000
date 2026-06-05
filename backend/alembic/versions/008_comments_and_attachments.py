"""comments and attachments

Revision ID: 008_comments_and_attachments
Revises: 007_defects_and_rework
Create Date: 2026-06-05 15:07:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '008_comments_and_attachments'
down_revision: Union[str, None] = '007_defects_and_rework'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create attachments
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
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # 2. Create entity_comments
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
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # 3. Create attachment_links
    op.create_table('attachment_links',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('attachment_id', sa.BigInteger(), nullable=False),
        sa.Column('entity_type', sa.Enum('plan_position', 'section_plan_line', 'work_task', 'transfer', 'transfer_discrepancy', 'defect', 'defect_item', 'defect_decision', 'rework_task', name='entity_type'), nullable=False),
        sa.Column('entity_id', sa.BigInteger(), nullable=False),
        sa.Column('caption', sa.Text(), nullable=True),
        sa.Column('created_by', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['attachment_id'], ['attachments.id'], ),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('attachment_id', 'entity_type', 'entity_id', name='uq_attachment_links_target')
    )


def downgrade() -> None:
    op.drop_table('attachment_links')
    op.drop_table('entity_comments')
    sa.Enum(name='entity_type').drop(op.get_bind(), checkfirst=False)
    op.drop_table('attachments')
