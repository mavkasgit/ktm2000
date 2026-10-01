"""Состояние валидации «перекрыта форс-аппрувом» (тикет #212, ADR-0048).

Revision ID: 064_plan_position_validation_overridden
Revises: 063_work_task_skipped_stage
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "064_plan_position_validation_overridden"
down_revision: str | None = "063_work_task_skipped_stage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUM_TYPE = "plan_position_validation_status"
ENUM_VALUE = "overridden"


def upgrade() -> None:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_enum e "
            "JOIN pg_type t ON t.oid = e.enumtypid "
            "WHERE t.typname = :type AND e.enumlabel = :value"
        ),
        {"type": ENUM_TYPE, "value": ENUM_VALUE},
    ).scalar()
    if not exists:
        # AFTER transaction: значение enum нельзя добавить внутри транзакции,
        # которая этим типом уже пользуется (alembic ведёт миграции в одной).
        with op.get_context().autocommit_block():
            op.execute(sa.text(f"ALTER TYPE {ENUM_TYPE} ADD VALUE '{ENUM_VALUE}'"))


def downgrade() -> None:
    # Значение enum удалить нельзя: ALTER TYPE ... DROP VALUE в PG 15 не
    # поддерживается. Downgrade оставляет значение в типе — код, который его
    # больше не пишет, продолжит читать его как обычную строку.
    pass
