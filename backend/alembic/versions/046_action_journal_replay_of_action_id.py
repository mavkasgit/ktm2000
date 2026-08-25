"""action_journal.replay_of_action_id — связь реплея действия.

Эпик Reversal (ADR-0019, тикет #121, решение 4 эпика):
``replay_of_action_id`` — новое действие воспроизводит эффект указанного
(компенсированного при amend) действия ветки. Реплей-действия имеют статус
``'active'`` — это полноценные живые действия. Индекс — поиск цепочки
реплея узла при preview/tree.

Irreversible: no

Revision ID: 046_action_journal_replay_of_action_id
Revises: 045_hard_purge_status_index
Create Date: 2026-08-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "046_action_journal_replay_of_action_id"
down_revision: Union[str, None] = "045_hard_purge_status_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- SCHEMA ---
    op.add_column(
        "action_journal",
        sa.Column("replay_of_action_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_action_journal_replay_of_action_id_action_journal"),
        "action_journal",
        "action_journal",
        ["replay_of_action_id"],
        ["id"],
    )
    op.create_index(
        op.f("ix_action_journal_replay_of_action_id"),
        "action_journal",
        ["replay_of_action_id"],
        unique=False,
    )

    # --- DATA ---
    pass

    # --- TRIGGERS ---
    pass


def downgrade() -> None:
    op.drop_index(
        op.f("ix_action_journal_replay_of_action_id"), table_name="action_journal"
    )
    op.drop_constraint(
        op.f("fk_action_journal_replay_of_action_id_action_journal"),
        "action_journal",
        type_="foreignkey",
    )
    op.drop_column("action_journal", "replay_of_action_id")
