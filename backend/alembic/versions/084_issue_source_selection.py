"""Автоподбор источника выдачи (#282): номер выдачи на передачах, пропуски по выдаче

Три изменения схемы, все — следствия решения «одна выдача = N передач»:

1. ``transfers.issue_no`` (VARCHAR(100), NULL): общий номер выдачи для всех
   передач, порождённых одним автоподбором источника. У обычной ручной
   передачи номера выдачи нет (NULL) — она никогда не была частью выдачи.
   Partial index только на непустые: журнал и «Отмена действий» группируют
   именно выдачи, а обычные передачи в выборку не должны тянуться.

2. ``transfers.from_task_id`` → NULL: выдача со склада-хранилища, у позиции
   которого нет строки плана на этом складе (склад вне маршрута — правило
   Q1/#282: источник ищется по всем складам-хранилищам), не имеет задания-
   источника. Передача остаётся полноценной записью (свой номер, свой
   Action, своя отмена); ``from_section_id`` по-прежнему обязателен —
   «Откуда» журнал читает именно по нему.

3. ``work_tasks.skipped_by_issue_no`` (VARCHAR(100), NULL): какой выдачей
   этап помечен «Пропущено». Отмена выдачи обязана снимать знак только с
   тех этапов, которые заставила пропустить именно она (#282), — без
   метки нельзя отличить автопропуск от пропуска, поставленного другой
   выдачей.

``downgrade`` убирает колонки; данные выдач (issue_no/метки) при откате
теряются — осознанно: откат схемы ниже версии продукта, её пишущей, всё
равно требует разбора.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "084_issue_source_selection"
down_revision: str | None = "083_normalize_als_sku_spelling"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transfers",
        sa.Column("issue_no", sa.String(length=100), nullable=True),
    )
    op.create_index(
        "ix_transfers_issue_no",
        "transfers",
        ["issue_no"],
        unique=False,
        postgresql_where=sa.text("issue_no IS NOT NULL"),
    )
    op.alter_column(
        "transfers",
        "from_task_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.add_column(
        "work_tasks",
        sa.Column("skipped_by_issue_no", sa.String(length=100), nullable=True),
    )
    op.create_index(
        "ix_work_tasks_skipped_by_issue_no",
        "work_tasks",
        ["skipped_by_issue_no"],
        unique=False,
        postgresql_where=sa.text("skipped_by_issue_no IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_work_tasks_skipped_by_issue_no", table_name="work_tasks")
    op.drop_column("work_tasks", "skipped_by_issue_no")
    op.alter_column(
        "transfers",
        "from_task_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.drop_index("ix_transfers_issue_no", table_name="transfers")
    op.drop_column("transfers", "issue_no")
