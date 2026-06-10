"""add one time login tokens

Revision ID: 014_add_one_time_login_tokens
Revises: 013_add_username
Create Date: 2026-06-10 06:53:21.861750
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '014_add_one_time_login_tokens'
down_revision: Union[str, None] = '013_add_username'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_login_tokens',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token', sa.String(length=6), nullable=False, unique=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('session_duration_seconds', sa.Integer(), nullable=True),
        sa.Column('is_used', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'))
    )
    op.create_index('ix_user_login_tokens_token', 'user_login_tokens', ['token'])


def downgrade() -> None:
    op.drop_index('ix_user_login_tokens_token', table_name='user_login_tokens')
    op.drop_table('user_login_tokens')
