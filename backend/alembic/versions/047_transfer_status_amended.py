"""transfer_status.amended — статус для коррекции через amend.

Тикет #124: ``correct_transfer`` переводится на ``ReversalService.amend``
исходного ``transfer_send``. Старая строка ``Transfer`` получает статус
``amended`` (append-only, ADR-0019), новая пара SEND/RECEIVE пишется под
новым ``Transfer``. Значение enum добавляется к существующему PostgreSQL
``transfer_status`` без перестройки таблицы.

Irreversible: no

Revision ID: 047_transfer_status_amended
Revises: 046_action_journal_replay_of_action_id
Create Date: 2026-08-25
"""
from typing import Sequence, Union

from alembic import op


revision: str = "047_transfer_status_amended"
down_revision: Union[str, None] = "046_action_journal_replay_of_action_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE transfer_status ADD VALUE IF NOT EXISTS 'amended'"
    )


def downgrade() -> None:
    # PostgreSQL не поддерживает удаление значения enum; ручная очистка
    # через UPDATE существующих строк и пересоздание типа (при необходимости).
    pass
