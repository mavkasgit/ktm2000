"""add users.avatar_seed for unified Multiavatar profile

Revision ID: 015_users_avatar_seed
Revises: 014_user_sessions
Create Date: 2026-07-18 22:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "015_users_avatar_seed"
down_revision: Union[str, None] = "014_user_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("avatar_seed", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "avatar_seed")
