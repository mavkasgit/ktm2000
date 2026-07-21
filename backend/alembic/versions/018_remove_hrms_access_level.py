"""remove hrms_access_level from users

Revision ID: 018_remove_hrms_access_level
Revises: 017_users_profile_synced_at
Create Date: 2026-07-21

"""
from alembic import op
import sqlalchemy as sa

revision: str = "018_remove_hrms_access_level"
down_revision: str = "017_users_profile_synced_at"

def upgrade() -> None:
    op.drop_column("users", "hrms_access_level")

def downgrade() -> None:
    op.add_column("users", sa.Column(
        "hrms_access_level", sa.String(50),
        server_default="'no_access'", nullable=False,
    ))
