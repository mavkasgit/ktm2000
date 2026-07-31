"""Server-side user session (hybrid JWT + session row; JWT claim `sid` = id)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class UserSession(Base):
    """Active/revoked login session for multi-device revoke and last-seen tracking."""

    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_user_id_revoked_at", "user_id", "revoked_at"),
        Index("ix_user_sessions_expires_at", "expires_at"),
        # Lookup active session by IdP sid (back-channel logout correlation)
        Index(
            "ix_user_sessions_oidc_sid",
            "oidc_sid",
            postgresql_where=text("oidc_sid IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # logout | user_revoke | password_change | admin | expired | backchannel_logout
    revoke_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    # e.g. "Google Chrome (Windows)" — server-side UA parse
    device_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # password | otp | oidc | setup_password
    login_method: Mapped[str] = mapped_column(String(32), nullable=False)
    # sid claim from id_token (OIDC Back-Channel Logout correlation); NULL for non-OIDC logins
    oidc_sid: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user = relationship("User", lazy="select")
