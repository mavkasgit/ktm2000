"""Дроп таблиц techcards/techcard_lines — техкарты упразднены (ADR-0023, #151).

Продукт — единый справочник (#146/#147): пары живут в product_pairs, состав
ГП — в product_compositions. Техкарты больше не читаются ни одним сервисом —
модели, роутер и страница удалены тем же тикетом. «Чистый лист» (ADR-0023 §7):
миграция данных из техкарт не выполняется, таблицы дропаются.

Идемпотентна (конвенция 052): stamp назад + повторный upgrade —
DROP TABLE IF EXISTS.

Revises: 054_product_pairs
Create Date: 2026-09-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "055_drop_techcards"
down_revision: Union[str, None] = "054_product_pairs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS techcard_lines")
    op.execute("DROP TABLE IF EXISTS techcards")


def downgrade() -> None:
    # Техкарты выведены из эксплуатации (ADR-0023) — downgrade не восстанавливает
    # таблицы: обратной миграции данных нет и не планируется.
    pass
