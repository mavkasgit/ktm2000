from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Notification(Base):
    """Уведомление — что произошло и что показать пользователю.

    Чистый контент: не знает про прочтение. Адресация — деталь хранения:
    user_id IS NULL = общее (для всех), user_id заполнен = персональное
    конкретному пользователю. Состояние (read/close) живёт в
    UserNotificationState.
    """

    __tablename__ = "notifications"

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

    __table_args__ = (
        Index("ix_notifications_created_at", "created_at"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Notification(id={self.id}, user_id={self.user_id}, "
            f"type={self.notification_type})>"
        )


class UserNotificationState(Base):
    """Состояние уведомления относительно конкретного пользователя.

    Единственное место хранения read/close — и для общих, и для персональных
    уведомлений. Ленивое создание: запись появляется при первом действии
    пользователя (read/close). Отсутствие записи = «непрочитано и активно».
    """

    __tablename__ = "user_notification_states"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)

    notification_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("notifications.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("notification_id", "user_id"),
        Index("ix_user_notification_states_user_closed", "user_id", "closed_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<UserNotificationState(id={self.id}, notification_id={self.notification_id}, "
            f"user_id={self.user_id})>"
        )
