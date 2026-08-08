from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InternalNotification(Base):
    """Внутреннее уведомление в интерфейсе.

    user_id IS NULL — общее (broadcast) уведомление для всех пользователей;
    user_id заполнен — персональное уведомление конкретного пользователя.
    Живёт до закрытия пользователем: есть дата прочтения и дата закрытия.
    """

    __tablename__ = "internal_notifications"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)

    # Адресат: NULL = общее, заполнен = персональное
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Ссылка на объект: тип + id, навигация по клику
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_internal_notifications_user_unclosed", "user_id", "closed_at"),
        Index("ix_internal_notifications_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<InternalNotification(id={self.id}, user_id={self.user_id}, "
            f"type={self.notification_type})>"
        )
