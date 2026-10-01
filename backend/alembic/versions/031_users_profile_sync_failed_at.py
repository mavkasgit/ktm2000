"""add users.profile_sync_failed_at for failed profile pull cooldown

Revision ID: 031_users_profile_sync_failed_at
Revises: 030_drop_user_login_tokens
Create Date: 2026-08-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "031_users_profile_sync_failed_at"
down_revision: str | None = "030_drop_user_login_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("profile_sync_failed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "profile_sync_failed_at")
