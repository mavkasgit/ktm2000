"""add users.profile_synced_at for unified profile cache TTL

Revision ID: 017_users_profile_synced_at
Revises: 016_users_locale_theme
Create Date: 2026-07-19 13:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "017_users_profile_synced_at"
down_revision: Union[str, None] = "016_users_locale_theme"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("profile_synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "profile_synced_at")
