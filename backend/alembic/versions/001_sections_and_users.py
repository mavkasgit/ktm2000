"""sections_and_users

Эпик: Участки, операции, пользователи, авторизация
Irreversible: no

Revision ID: 001_sections_and_users
Revises: 
Create Date: 2026-07-05 19:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql


revision: str = "001_sections_and_users"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- SCHEMA ---
    op.create_table('sections',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.String(length=500), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('type', sa.String(length=20), server_default=sa.text("'production'"), nullable=False),
    sa.Column('icon', sa.String(length=50), nullable=True),
    sa.Column('icon_color', sa.String(length=7), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sections')),
    sa.UniqueConstraint('code', name=op.f('uq_sections_code'))
    )
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
    sa.Column('operation_type', sa.Enum('production', 'transport', name='section_operation_type'), server_default=sa.text("'production'"), nullable=False),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], name=op.f('fk_section_operations_section_id_sections')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_section_operations')),
    sa.UniqueConstraint('section_id', 'operation_code', name='uq_section_operations')
    )
    op.create_table('users',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('username', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=False),
    sa.Column('role', sa.Enum('admin', 'planner', 'section_manager', 'operator', 'viewer', 'transporter', name='user_role'), nullable=False),
    sa.Column('section_id', sa.BigInteger(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('hrms_access_level', sa.String(length=50), server_default=sa.text("'no_access'"), nullable=False),
    sa.Column('tab_number', sa.String(length=50), nullable=True),
    sa.Column('hrms_employee_id', sa.BigInteger(), nullable=True),
    sa.Column('position', sa.String(length=255), nullable=True),
    sa.Column('department', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], name=op.f('fk_users_section_id_sections')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email')),
    sa.UniqueConstraint('hrms_employee_id', name=op.f('uq_users_hrms_employee_id')),
    sa.UniqueConstraint('username', name=op.f('uq_users_username'))
    )
    op.create_table('user_sections',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('section_id', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], name=op.f('fk_user_sections_section_id_sections'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_sections_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'section_id', name=op.f('pk_user_sections'))
    )
    op.create_table('user_login_tokens',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('token', sa.String(length=6), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('session_duration_seconds', sa.Integer(), nullable=True),
    sa.Column('is_used', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_login_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_login_tokens')),
    sa.UniqueConstraint('token', name=op.f('uq_user_login_tokens_token'))
    )

    # --- DATA ---
    # Passwordless service account for automated actions and DEV_BYPASS_AUTH fallback.
    op.execute(text("""
        INSERT INTO users (id, username, email, password_hash, full_name, role, is_active)
        OVERRIDING SYSTEM VALUE
        VALUES (1, 'system', 'system@local', '', 'System User', 'admin', true)
    """))
    op.execute(text("SELECT setval(pg_get_serial_sequence('users', 'id'), 100, false)"))

    # --- TRIGGERS ---
    pass


def downgrade() -> None:
    op.drop_table('user_login_tokens')
    op.drop_table('user_sections')
    op.drop_table('users')
    op.drop_table('section_operations')
    op.drop_table('sections')
