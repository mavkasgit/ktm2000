"""Статус purged + индекс reverses_id для hard-чистки.

Эпик Reversal (ADR-0019 п.7, тикет #118):
1. CHECK статуса action_journal расширен значением ``'purged'`` —
   действие с физически удалёнными (скомпенсированными) парами проводок;
   записи журнала не удаляются (аудит).
2. Индекс ``ix_stock_transactions_reverses_id`` — поиск пар
   «исходная+компенсация» идёт по ``reverses_id``.

Irreversible: no

Revision ID: 045_hard_purge_status_index
Revises: 044_action_journal_indexes_status
Create Date: 2026-08-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "045_hard_purge_status_index"
down_revision: Union[str, None] = "044_action_journal_indexes_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- SCHEMA ---
    op.drop_constraint("ck_action_journal_status", "action_journal", type_="check")
    op.create_check_constraint(
        "ck_action_journal_status",
        "action_journal",
        "status IN ('active', 'reversed', 'amended', 'purged')",
    )
    op.create_index(
        op.f("ix_stock_transactions_reverses_id"),
        "stock_transactions",
        ["reverses_id"],
        unique=False,
    )

    # --- DATA ---
    pass

    # --- TRIGGERS ---
    pass


def downgrade() -> None:
    op.drop_index(
        op.f("ix_stock_transactions_reverses_id"), table_name="stock_transactions"
    )
    # Пары уже удалены — статус 'purged' более не валиден: возвращаем
    # такие действия в 'reversed', чтобы ужать CHECK до прежнего списка.
    op.execute("UPDATE action_journal SET status = 'reversed' WHERE status = 'purged'")
    op.drop_constraint("ck_action_journal_status", "action_journal", type_="check")
    op.create_check_constraint(
        "ck_action_journal_status",
        "action_journal",
        "status IN ('active', 'reversed', 'amended')",
    )
