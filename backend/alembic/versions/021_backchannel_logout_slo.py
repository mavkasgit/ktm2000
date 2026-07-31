"""user_sessions.oidc_sid + used_logout_jti + user_login_events (OIDC back-channel SLO, phase 1)

Revision ID: 021_backchannel_logout_slo
Revises: 020_create_hrms_employees
Create Date: 2026-07-30

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "021_backchannel_logout_slo"
down_revision = "020_create_hrms_employees"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- user_sessions: add columns for multi-device tracking + back-channel SLO ---
    op.add_column("user_sessions", sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.add_column("user_sessions", sa.Column("revoke_reason", sa.String(length=32), nullable=True))
    op.add_column("user_sessions", sa.Column("ip_address", sa.String(length=45), nullable=True))
    op.add_column("user_sessions", sa.Column("user_agent", sa.Text(), nullable=True))
    op.add_column("user_sessions", sa.Column("device_label", sa.String(length=128), nullable=True))
    op.add_column("user_sessions", sa.Column("oidc_sid", sa.String(length=255), nullable=True))

    # ix_user_sessions_user_id_revoked_at and ix_user_sessions_expires_at already exist from 014
    op.create_index(
        "ix_user_sessions_oidc_sid",
        "user_sessions",
        ["oidc_sid"],
        postgresql_where=sa.text("oidc_sid IS NOT NULL"),
    )

    # --- used_logout_jti: replay protection for OIDC back-channel logout tokens ---
    op.create_table(
        "used_logout_jti",
        sa.Column("jti", sa.String(length=255), primary_key=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_used_logout_jti_expires_at", "used_logout_jti", ["expires_at"])

    # --- user_login_events: audit trail for login/session security events ---
    op.create_table(
        "user_login_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("username_attempted", sa.String(length=255), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_user_login_events_user_id", "user_login_events", ["user_id"])
    op.create_index(
        "ix_user_login_events_user_id_created_at",
        "user_login_events",
        ["user_id", "created_at"],
    )
    op.create_index("ix_user_login_events_created_at", "user_login_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_user_login_events_created_at", table_name="user_login_events")
    op.drop_index("ix_user_login_events_user_id_created_at", table_name="user_login_events")
    op.drop_index("ix_user_login_events_user_id", table_name="user_login_events")
    op.drop_table("user_login_events")

    op.drop_index("ix_used_logout_jti_expires_at", table_name="used_logout_jti")
    op.drop_table("used_logout_jti")

    op.drop_index("ix_user_sessions_oidc_sid", table_name="user_sessions")

    op.drop_column("user_sessions", "oidc_sid")
    op.drop_column("user_sessions", "device_label")
    op.drop_column("user_sessions", "user_agent")
    op.drop_column("user_sessions", "ip_address")
    op.drop_column("user_sessions", "revoke_reason")
    op.drop_column("user_sessions", "last_seen_at")
