"""создать таблицу internal_notifications (уведомления).

Revision ID: 035_internal_notifications
Revises: 034_product_dimension_state
Create Date: 2026-08-09 01:06:19.834102
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "035_internal_notifications"
down_revision: Union[str, None] = "034_product_dimension_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "internal_notifications",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("notification_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_internal_notifications_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_internal_notifications")),
    )
    op.create_index("ix_internal_notifications_created_at", "internal_notifications", ["created_at"], unique=False)
    op.create_index("ix_internal_notifications_user_unclosed", "internal_notifications", ["user_id", "closed_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_internal_notifications_user_unclosed", table_name="internal_notifications")
    op.drop_index("ix_internal_notifications_created_at", table_name="internal_notifications")
    op.drop_table("internal_notifications")
