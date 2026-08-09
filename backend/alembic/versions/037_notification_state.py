"""модель уведомлений: Notification + UserNotificationState (#86).

Разделение контента и состояния: таблица internal_notifications переименована
в notifications и лишена read_at/closed_at; состояние (read/close) переносится
в per-user таблицу user_notification_states. Единая модель для общих и
персональных уведомлений; ленивое создание записи состояния при первом
действии пользователя.

Revision ID: 037_notification_state
Revises: 036_product_length_is_primary
Create Date: 2026-08-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "037_notification_state"
down_revision: Union[str, None] = "036_product_length_is_primary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Таблица пустая (продюсеров пока нет) — переименование безопасно.
    op.rename_table("internal_notifications", "notifications")

    # read_at/closed_at уходят со строки в user_notification_states.
    op.drop_index("ix_internal_notifications_user_unclosed", table_name="notifications")
    op.drop_index("ix_internal_notifications_created_at", table_name="notifications")
    op.drop_column("notifications", "read_at")
    op.drop_column("notifications", "closed_at")

    op.create_index("ix_notifications_created_at", "notifications", ["created_at"], unique=False)
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", "created_at"], unique=False)

    # Constraint names по naming convention привязаны к старому имени таблицы.
    op.execute("ALTER TABLE notifications RENAME CONSTRAINT fk_internal_notifications_user_id_users TO fk_notifications_user_id_users")
    op.execute("ALTER TABLE notifications RENAME CONSTRAINT pk_internal_notifications TO pk_notifications")

    op.create_table(
        "user_notification_states",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("notification_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["notifications.id"],
            name=op.f("fk_user_notification_states_notification_id_notifications"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_notification_states_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_notification_states")),
        sa.UniqueConstraint(
            "notification_id",
            "user_id",
            name=op.f("uq_user_notification_states_notification_id"),
        ),
    )
    op.create_index(
        "ix_user_notification_states_user_closed",
        "user_notification_states",
        ["user_id", "closed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_user_notification_states_user_closed", table_name="user_notification_states")
    op.drop_table("user_notification_states")

    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_index("ix_notifications_created_at", table_name="notifications")

    op.execute("ALTER TABLE notifications RENAME CONSTRAINT fk_notifications_user_id_users TO fk_internal_notifications_user_id_users")
    op.execute("ALTER TABLE notifications RENAME CONSTRAINT pk_notifications TO pk_internal_notifications")

    op.add_column(
        "notifications",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_internal_notifications_created_at", "notifications", ["created_at"], unique=False)
    op.create_index("ix_internal_notifications_user_unclosed", "notifications", ["user_id", "closed_at"], unique=False)

    op.rename_table("notifications", "internal_notifications")
