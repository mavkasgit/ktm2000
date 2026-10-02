"""Индексы под bulk-ready и журнал передач (#290)

Страница ready-передач уходила в сотни миллисекунд на одних только
lookup'ах и агрегатах без индексов; форма запросов — из #290:

* `stock_transactions (reason, task_id) INCLUDE (quantity, reverses_id)` —
  агрегаты бюджета (`WHERE reason=… GROUP BY task_id`): quantity и
  reverses_id читаются из индекса без heap-хода. Левый префикс покрывает
  прежний одиночный `ix_stock_transactions_reason` — он дропается, чтобы
  не удваивать write-цену ledger'а.
* `stock_transactions (reason, section_plan_line_id)` —
  `net_by_reason(section_plan_line_id=…)`, до сих пор шедший без индекса.
* `section_plan_lines (plan_position_id, sequence)` — «следующая строка»
  маршрута: внешний join production-ветки ready и prefetch `next_line`.
* `work_tasks (section_plan_line_id)` — FK без индекса: все lookup'ы задач
  по строке плана, включая prefetch складской ветки одним `IN`.
* `transfers (created_at)` — `ORDER BY created_at DESC` и фильтры дат
  журнала передач.

Все пять объявлены и в моделях (`__table_args__`): тестовая схема
строится `create_all` и не должна расходиться с миграцией.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "077_ready_transfer_indexes"
#: 076 (`stock_import_batch_fk_types`, #261) — предыдущая в линейной цепочке.
down_revision: str | None = "076_stock_import_batch_fk_types"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # if_not_exists/if_exists: повторный запуск миграции безопасен —
    # тесты test_migrations штампуют старую ревизию и гоняют upgrade head
    # на схеме, где эти индексы уже есть.
    op.create_index(
        "ix_section_plan_lines_plan_position_id_sequence",
        "section_plan_lines",
        ["plan_position_id", "sequence"],
        unique=False,
        if_not_exists=True,
    )
    op.drop_index(
        "ix_stock_transactions_reason",
        table_name="stock_transactions",
        if_exists=True,
    )
    op.create_index(
        "ix_stock_transactions_reason_section_plan_line_id",
        "stock_transactions",
        ["reason", "section_plan_line_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_stock_transactions_reason_task_id",
        "stock_transactions",
        ["reason", "task_id"],
        unique=False,
        postgresql_include=["quantity", "reverses_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_transfers_created_at",
        "transfers",
        ["created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_work_tasks_section_plan_line_id",
        "work_tasks",
        ["section_plan_line_id"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_work_tasks_section_plan_line_id",
        table_name="work_tasks",
        if_exists=True,
    )
    op.drop_index("ix_transfers_created_at", table_name="transfers", if_exists=True)
    op.drop_index(
        "ix_stock_transactions_reason_task_id",
        table_name="stock_transactions",
        postgresql_include=["quantity", "reverses_id"],
        if_exists=True,
    )
    op.drop_index(
        "ix_stock_transactions_reason_section_plan_line_id",
        table_name="stock_transactions",
        if_exists=True,
    )
    op.create_index(
        "ix_stock_transactions_reason",
        "stock_transactions",
        ["reason"],
        unique=False,
        if_not_exists=True,
    )
    op.drop_index(
        "ix_section_plan_lines_plan_position_id_sequence",
        table_name="section_plan_lines",
        if_exists=True,
    )
