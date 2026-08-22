"""Индексы action_journal + CHECK статуса + колонка reason.

Эпик Reversal (ADR-0019, тикет #114, чек-лист ревью #113):
1. Индексы ``action_journal(ref_id)`` и ``action_journal(action_type)`` —
   все запросы к журналу фильтруют по ним.
2. CHECK-констрейнт статуса (active/reversed/amended) — согласован с
   Python Enum ActionStatus.
3. Колонка ``reason`` — причина отката (ReversalService.reverse).

Irreversible: no

Revision ID: 044_action_journal_indexes_status
Revises: 043_action_journal_reverses_id
Create Date: 2026-08-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "044_action_journal_indexes_status"
down_revision: Union[str, None] = "043_action_journal_reverses_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- SCHEMA ---
    op.create_index(
        op.f("ix_action_journal_ref_id"), "action_journal", ["ref_id"], unique=False
    )
    op.create_index(
        op.f("ix_action_journal_action_type"),
        "action_journal",
        ["action_type"],
        unique=False,
    )
    op.create_check_constraint(
        "ck_action_journal_status",
        "action_journal",
        "status IN ('active', 'reversed', 'amended')",
    )
    op.add_column("action_journal", sa.Column("reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("action_journal", "reason")
    op.drop_constraint("ck_action_journal_status", "action_journal", type_="check")
    op.drop_index(op.f("ix_action_journal_action_type"), table_name="action_journal")
    op.drop_index(op.f("ix_action_journal_ref_id"), table_name="action_journal")
