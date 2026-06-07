"""add action, entity_type, entity_id, changes to audit_logs

Revision ID: 013_audit_logs_v2
Revises: 012_audit_logs
Create Date: 2026-06-07 23:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '013_audit_logs_v2'
down_revision: Union[str, None] = '012_audit_logs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns to audit_logs
    op.add_column('audit_logs', sa.Column('action', sa.String(length=50), nullable=True))
    op.add_column('audit_logs', sa.Column('entity_type', sa.String(length=50), nullable=True))
    op.add_column('audit_logs', sa.Column('entity_id', sa.BigInteger(), nullable=True))
    op.add_column('audit_logs', sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

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

    # Drop columns
    op.drop_column('audit_logs', 'changes')
    op.drop_column('audit_logs', 'entity_id')
    op.drop_column('audit_logs', 'entity_type')
    op.drop_column('audit_logs', 'action')
