"""Индексы горячих путей: доска участка, /rows, summary, журнал передач (#291)

12-секундный опрос операционных экранов делал seq scan по таблицам, у которых
не было ни одного вторичного индекса. Формы запросов — из тикета #291,
замеры «до/после» и планы EXPLAIN — в комментарии к тикету и в
``docs/night/tickets/T-291-hot-path-indexes.md``.

* ``work_tasks (section_id, status)`` — доска участка (``section_id = …``),
  summary и ready фильтруют по участку; ``summary`` ещё и группирует по нему,
  поэтому ``status`` вторым столбцом: агрегат читает пары из индекса, не
  поднимая heap. Левый префикс покрывает все lookup'ы «задачи участка».
* ``route_stages (section_id)`` — коррелированный EXISTS «есть задача на
  участке» в ``/rows`` (на позицию); без индекса каждый EXISTS шёл
  seq scan по 369 строкам этапов.
* ``plan_positions (status) WHERE deleted_at IS NULL`` — ``_active_positions_stmt``
  и фильтр «неудалённые» в ``/rows``/board/summary. Partial: soft-deleted
  позиции в индексе не лежат, write-цена не растёт от их удаления.
  (``deleted_at`` внутрь ключа не берём — в partial он константен.)
* ``plan_positions (production_plan_id)`` — ``list_plans`` и ``section_totals``:
  агрегаты по плану шли seq scan'ом на каждый план.
* ``transfers (to_section_id, created_at)`` / ``transfers (from_section_id,
  created_at)`` — OR-фильтр журнала передач по участку и ``ORDER BY created_at
  DESC``. Одиночных ``(to_section_id)``/``(from_section_id)`` не создаём: их
  левый префикс покрыт этими составными.
* ``stock_transactions (to_location_id, created_at)`` — суточная статистика
  участка (``to_location_id = … AND created_at BETWEEN …``). Заменяет
  одиночный ``ix_stock_transactions_to_location_id`` (левый префикс покрыт),
  тот дропается — ledger не платит за две записи на одну проводку.
* ``stock_transactions (created_at)`` — фид проводок: ``ORDER BY created_at`` и
  фильтры дат без ``ORDER BY id``.

Уже объявленные #290 (миграция 077) не дублируются:
``section_plan_lines (plan_position_id, sequence)`` покрывает одиночный
``(plan_position_id)`` из списка тикета, ``stock_transactions (reason,
section_plan_line_id)`` покрывает запрошенный ``(section_plan_line_id,
reason)`` (равенства по обоим столбцам — порядок столбцов не влияет на
селективность), а ``transfers (created_at)`` покрывает журнал по датам.

Все индексы объявлены и в моделях (``__table_args__``): тестовая схема
строится ``create_all`` и миграции не видит.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "078_hot_path_indexes"
#: 077 (`ready_transfer_indexes`, #290) — предыдущая в линейной цепочке.
down_revision: str | None = "077_ready_transfer_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # if_not_exists/if_exists: повторный проход безопасен — тесты
    # test_migrations гоняют upgrade head на схеме, где индексы уже есть.
    op.create_index(
        "ix_work_tasks_section_id_status",
        "work_tasks",
        ["section_id", "status"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_route_stages_section_id",
        "route_stages",
        ["section_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_plan_positions_active_status",
        "plan_positions",
        ["status"],
        unique=False,
        postgresql_where="deleted_at IS NULL",
        if_not_exists=True,
    )
    op.create_index(
        "ix_plan_positions_production_plan_id",
        "plan_positions",
        ["production_plan_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_transfers_from_section_id_created_at",
        "transfers",
        ["from_section_id", "created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_transfers_to_section_id_created_at",
        "transfers",
        ["to_section_id", "created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_stock_transactions_to_location_id_created_at",
        "stock_transactions",
        ["to_location_id", "created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.drop_index(
        "ix_stock_transactions_to_location_id",
        table_name="stock_transactions",
        if_exists=True,
    )
    op.create_index(
        "ix_stock_transactions_created_at",
        "stock_transactions",
        ["created_at"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_stock_transactions_created_at",
        table_name="stock_transactions",
        if_exists=True,
    )
    op.create_index(
        "ix_stock_transactions_to_location_id",
        "stock_transactions",
        ["to_location_id"],
        unique=False,
        if_not_exists=True,
    )
    op.drop_index(
        "ix_stock_transactions_to_location_id_created_at",
        table_name="stock_transactions",
        if_exists=True,
    )
    op.drop_index(
        "ix_transfers_to_section_id_created_at",
        table_name="transfers",
        if_exists=True,
    )
    op.drop_index(
        "ix_transfers_from_section_id_created_at",
        table_name="transfers",
        if_exists=True,
    )
    op.drop_index(
        "ix_plan_positions_production_plan_id",
        table_name="plan_positions",
        if_exists=True,
    )
    op.drop_index(
        "ix_plan_positions_active_status",
        table_name="plan_positions",
        postgresql_where="deleted_at IS NULL",
        if_exists=True,
    )
    op.drop_index("ix_route_stages_section_id", table_name="route_stages", if_exists=True)
    op.drop_index("ix_work_tasks_section_id_status", table_name="work_tasks", if_exists=True)
