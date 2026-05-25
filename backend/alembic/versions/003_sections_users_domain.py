"""sections and users domain

Revision ID: 003_sections_users_domain
Revises: 002_techcards_domain
Create Date: 2026-05-25 12:02:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '003_sections_users_domain'
down_revision: Union[str, None] = '002_techcards_domain'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    user_role_enum = postgresql.ENUM(
        "admin", "planner", "section_manager", "operator", "viewer",
        name="user_role",
    )
    user_role_enum.create(op.get_bind())

    op.create_table(
        'sections',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True, autoincrement=True),
        sa.Column('code', sa.String(100), nullable=False, unique=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column('kind', sa.String(20), nullable=False, server_default=sa.text("'production'")),
        sa.Column('icon', sa.String(50), nullable=True),
        sa.Column('icon_color', sa.String(7), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        'users',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True, autoincrement=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(255), nullable=False),
        sa.Column('role', sa.Enum("admin", "planner", "section_manager", "operator", "viewer", name="user_role"), nullable=False),
        sa.Column('section_id', sa.BigInteger(), sa.ForeignKey('sections.id'), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table('users')
    op.drop_table('sections')
    sa.Enum(name='user_role').drop(op.get_bind(), checkfirst=True)
