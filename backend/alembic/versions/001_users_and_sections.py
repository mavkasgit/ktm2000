"""users and sections

Revision ID: 001_users_and_sections
Revises: 
Create Date: 2026-06-05 15:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '001_users_and_sections'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create sections table
    op.create_table('sections',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('kind', sa.String(length=20), server_default=sa.text("'production'"), nullable=False),
        sa.Column('icon', sa.String(length=50), nullable=True),
        sa.Column('icon_color', sa.String(length=7), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )
    
    # 2. Create section_operations table
    op.create_table('section_operations',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('section_id', sa.BigInteger(), nullable=False),
        sa.Column('operation_code', sa.String(length=100), nullable=False),
        sa.Column('operation_name', sa.String(length=255), nullable=False),
        sa.Column('is_significant', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('icon', sa.String(length=50), nullable=True),
        sa.Column('icon_color', sa.String(length=7), nullable=True),
        sa.Column('group_code', sa.String(length=100), nullable=True),
        sa.Column('group_name', sa.String(length=255), nullable=True),
        sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('resolver_type', sa.String(length=50), nullable=True),
        sa.Column('resolver_config', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(['section_id'], ['sections.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('section_id', 'operation_code', name='uq_section_operations')
    )
    
    # 3. Create users table
    op.create_table('users',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('role', sa.Enum('admin', 'planner', 'section_manager', 'operator', 'viewer', 'transporter', name='user_role'), nullable=False),
        sa.Column('section_id', sa.BigInteger(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['section_id'], ['sections.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )

    # 4. Seed default system user
    op.execute(
        "INSERT INTO users (id, email, password_hash, full_name, role, is_active) "
        "OVERRIDING SYSTEM VALUE "
        "VALUES (1, 'system@local', '', 'System User', 'admin', true) "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM users WHERE id = 1")
    op.drop_table('users')
    sa.Enum(name='user_role').drop(op.get_bind(), checkfirst=False)
    op.drop_table('section_operations')
    op.drop_table('sections')
