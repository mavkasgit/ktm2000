"""create audit logs table

Revision ID: 012_audit_logs
Revises: 011_post_factum_transfers
Create Date: 2026-06-07 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '012_audit_logs'
down_revision: Union[str, None] = '011_post_factum_transfers'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=True),
        sa.Column('user_name', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('section_id', sa.BigInteger(), nullable=True),
        sa.Column('section_name', sa.String(length=255), nullable=True),
        sa.Column('section_code', sa.String(length=255), nullable=True),
        sa.Column('task_ids', sa.Text(), nullable=True),
        sa.Column('product_sku', sa.String(length=255), nullable=True),
        sa.Column('operation_name', sa.String(length=255), nullable=True),
        sa.Column('qty_text', sa.String(length=100), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('error_details', sa.Text(), nullable=True),
        sa.Column('action', sa.String(length=50), nullable=True),
        sa.Column('entity_type', sa.String(length=50), nullable=True),
        sa.Column('entity_id', sa.BigInteger(), nullable=True),
        sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['section_id'], ['sections.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for optimal querying
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'], unique=False)
    op.create_index('ix_audit_logs_entity_type', 'audit_logs', ['entity_type'], unique=False)
    op.create_index('ix_audit_logs_entity_id', 'audit_logs', ['entity_id'], unique=False)
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'], unique=False)
    op.create_index('ix_audit_logs_user_id', 'audit_logs', ['user_id'], unique=False)
    op.create_index('ix_audit_logs_section_id', 'audit_logs', ['section_id'], unique=False)
    op.create_index(
        'ix_audit_logs_entity_lookup',
        'audit_logs',
        ['entity_type', 'entity_id', 'created_at'],
        unique=False
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_audit_logs_entity_lookup', table_name='audit_logs')
    op.drop_index('ix_audit_logs_section_id', table_name='audit_logs')
    op.drop_index('ix_audit_logs_user_id', table_name='audit_logs')
    op.drop_index('ix_audit_logs_created_at', table_name='audit_logs')
    op.drop_index('ix_audit_logs_entity_id', table_name='audit_logs')
    op.drop_index('ix_audit_logs_entity_type', table_name='audit_logs')
    op.drop_index('ix_audit_logs_action', table_name='audit_logs')

    # Drop table
    op.drop_table('audit_logs')
