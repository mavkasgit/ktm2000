"""add users.locale and users.theme for unified profile cache

Revision ID: 016_users_locale_theme
Revises: 015_users_avatar_seed
Create Date: 2026-07-19 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "016_users_locale_theme"
down_revision: str | None = "015_users_avatar_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("locale", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("theme", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "theme")
    op.drop_column("users", "locale")
