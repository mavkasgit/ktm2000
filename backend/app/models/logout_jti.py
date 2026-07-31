"""Replay-protect OIDC back-channel logout_token (jti one-time use, OIDC BCP)."""

from sqlalchemy import Column, DateTime, String

from app.models.base import Base


class UsedLogoutJti(Base):
    """Consumed jti from logout_token; row lives until token exp, then cleaned up."""

    __tablename__ = "used_logout_jti"

    jti = Column(String(255), primary_key=True)
    # exp from logout_token — after this point replay is impossible, row can be deleted
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
