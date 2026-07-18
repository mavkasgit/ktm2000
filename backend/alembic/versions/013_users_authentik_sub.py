"""add users.authentik_sub for OIDC/Authentik bridge

Revision ID: 013_users_authentik_sub
Revises: 012_database_triggers
Create Date: 2026-07-18 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "013_users_authentik_sub"
down_revision: Union[str, None] = "012_database_triggers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- SCHEMA ---
    op.add_column(
        "users",
        sa.Column("authentik_sub", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_users_authentik_sub", "users", ["authentik_sub"])
    # Partial unique: active rows only, non-null authentik_sub (KTM uses is_active)
    op.create_index(
        "ix_users_authentik_sub_active",
        "users",
        ["authentik_sub"],
        unique=True,
        postgresql_where=sa.text("is_active = true AND authentik_sub IS NOT NULL"),
    )

    # --- DATA ---
    pass

    # --- TRIGGERS ---
    pass


def downgrade() -> None:
    op.drop_index("ix_users_authentik_sub_active", table_name="users")
    op.drop_index("ix_users_authentik_sub", table_name="users")
    op.drop_column("users", "authentik_sub")
