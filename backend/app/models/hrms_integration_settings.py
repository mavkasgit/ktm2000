from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

SINGLETON_ID = 1


class HrmsIntegrationSettings(Base):
    __tablename__ = "hrms_integration_settings"

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    api_token: Mapped[str] = mapped_column(
        String(255), nullable=False, server_default=text("'admin'")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )