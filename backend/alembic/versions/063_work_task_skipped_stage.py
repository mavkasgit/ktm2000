"""Статус этапа «пропущено» и причина пропуска (тикет #207, Q6).

Revision ID: 063_work_task_skipped_stage
Revises: 062_stock_tx_completed_operations
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "063_work_task_skipped_stage"
down_revision: str | None = "062_stock_tx_completed_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_enum e "
            "JOIN pg_type t ON t.oid = e.enumtypid "
            "WHERE t.typname = 'work_task_status' AND e.enumlabel = 'skipped'"
        )
    ).scalar()
    if not exists:
        # AFTER transaction: добавить значение в тип enum нельзя внутри
        # транзакции, которая этим типом пользуется. Alembic выполняет
        # миграции в транзакции, поэтому значение добавляется autocommit-блоком.
        with op.get_context().autocommit_block():
            op.execute(sa.text("ALTER TYPE work_task_status ADD VALUE 'skipped'"))

    columns = {column["name"] for column in sa.inspect(bind).get_columns("work_tasks")}
    if "skip_reason" not in columns:
        op.add_column(
            "work_tasks",
            sa.Column("skip_reason", sa.String(255), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("work_tasks")}
    if "skip_reason" in columns:
        op.drop_column("work_tasks", "skip_reason")
    # Значение enum 'skipped' удалить нельзя (ALTER TYPE ... DROP VALUE
    # недоступен в PG 15), поэтому downgrade оставляет его в типе: код,
    # умеющий его читать, продолжит работать, а записывать его перестанет.
