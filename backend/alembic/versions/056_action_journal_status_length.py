"""action_journal.status → varchar(8): выравнивание с Enum-моделью (#118, ADR-0019).

Колонка создана в 043 как varchar(20). В #114 модель перешла на не-нативный
Enum ActionStatus (native_enum=False), который рендерится в VARCHAR ровно по
длине самого длинного значения ('reversed' — 8 символов). Миграцию не
выровняли, и `alembic check` в CI падал на modify_type. Сужаем колонку до
длины Enum; CHECK ck_action_journal_status (044/045) не трогаем — он и так
ограничивает значения четырьмя статусами.

Irreversible: no

Revision ID: 056_action_journal_status_length
Revises: 055_drop_techcards
Create Date: 2026-09-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "056_action_journal_status_length"
down_revision: Union[str, None] = "055_drop_techcards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "action_journal",
        "status",
        existing_type=sa.String(length=20),
        type_=sa.String(length=8),
        existing_nullable=False,
        existing_server_default=sa.text("'active'"),
    )


def downgrade() -> None:
    op.alter_column(
        "action_journal",
        "status",
        existing_type=sa.String(length=8),
        type_=sa.String(length=20),
        existing_nullable=False,
        existing_server_default=sa.text("'active'"),
    )
