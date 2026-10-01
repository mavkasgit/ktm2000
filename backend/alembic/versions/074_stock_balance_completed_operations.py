"""completed_operations в ключе stock_balances: две строки остатка на разные операции (ADR-0055)

`stock_transactions.completed_operations` (ADR-0043, миграция 062) пишется, но
остаток по нему не различался: `StockBalance` ключом имел
`(product_id, location_id, quality_state, dimensions)`, поэтому материал,
прошедший разные операции, сливался в одну сумму — а колонка «Операции» в UI
показывала лишь текст комментария последней приходной проводки.

Теперь `completed_operations` входит в ключ баланса, ровно как `dimensions`
(ADR-0001): одна ось — один столбец в UNIQUE, NULLS NOT DISTINCT (PG15+), чтобы
legacy-группа с NULL-признаком не задвоилась.

Бэкфилл берёт признак из ledger: у каждой существующей строки баланса он равен
признаку проводок, образовавших эту строку.

Повторный прогон безопасен (конвенция 052: ``stamp`` назад + ``upgrade head``):
колонки добавляются с ``IF NOT EXISTS``, смена unique-констрейнта — по факту
наличия старого и отсутствия нового.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "074_stock_balance_completed_operations"
down_revision: str | None = "073_stock_import_rows_tx_set_null"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_CONSTRAINT = "uq_stock_balances_product_location_quality_dims"
NEW_CONSTRAINT = "uq_stock_balances_product_location_quality_dims_ops"

# Строка, которой не может быть текст jsonb: 'null' — единственный неинфографический
# литерал JSON, а обычные значения начинаются с '{', '[' или '"'. Нужен как
# маркер «признак не зафиксирован» внутри COUNT(DISTINCT ...), где SQL NULL
# не считается отдельным значением.
_NULL_SENTINEL = "'@@ktm_null@@'"

_BACKFILL_SQL = f"""
WITH tx_sides AS (
    SELECT product_id,
           to_location_id AS location_id,
           to_quality_state AS quality_state,
           dimensions,
           completed_operations
    FROM stock_transactions
    WHERE to_location_id IS NOT NULL
    UNION ALL
    SELECT product_id,
           from_location_id,
           from_quality_state,
           dimensions,
           completed_operations
    FROM stock_transactions
    WHERE from_location_id IS NOT NULL
),
src AS (
    SELECT product_id,
           location_id,
           quality_state,
           dimensions,
           COUNT(DISTINCT COALESCE(completed_operations::text, {_NULL_SENTINEL}))
               AS variants,
           (array_agg(completed_operations
                      ORDER BY completed_operations::text NULLS FIRST)
                FILTER (WHERE completed_operations IS NOT NULL))[1] AS ops_value
    FROM tx_sides
    GROUP BY product_id, location_id, quality_state, dimensions
)
UPDATE stock_balances AS b
SET completed_operations = src.ops_value
FROM src
WHERE b.product_id = src.product_id
  AND b.location_id = src.location_id
  AND b.quality_state = src.quality_state
  AND b.dimensions IS NOT DISTINCT FROM src.dimensions
  AND src.variants = 1
"""

# Группы с >1 вариантом признака не переносятся: они остаются NULL и разойдутся
# по первому же refresh_balance (признак пишется явно каждой проводкой).
# Падать на них нельзя — миграция обязана накатываться на любую существующую БД,
# где эти данные схлопнулись ещё до разделения оси.
#
# Обратный ход — два шага, и порядок обязателен: сначала строка-представитель
# группы (минимальный id) получает СУММУ остатков всех ops-групп, и только
# потом лишние строки удаляются. Если удалить раньше, SUM пойдёт по единственной
# оставшейся строке и молча потеряет материал остальных групп.
#
# Две отдельные константы, а не один скрипт через ``;``: asyncpg исполняет
# ``op.execute`` как prepared statement, а он принимает ровно одну команду.
_DOWNGRADE_SUM_SQL = """
UPDATE stock_balances AS b
SET balance_qty = agg.total
FROM (
    SELECT product_id, location_id, quality_state, dimensions,
           MIN(id) AS keep_id, SUM(balance_qty) AS total
    FROM stock_balances
    GROUP BY product_id, location_id, quality_state, dimensions
) AS agg
WHERE b.id = agg.keep_id
"""

_DOWNGRADE_DEDUP_SQL = """
DELETE FROM stock_balances a
USING stock_balances b
WHERE a.id > b.id
  AND a.product_id = b.product_id
  AND a.location_id = b.location_id
  AND a.quality_state = b.quality_state
  AND a.dimensions IS NOT DISTINCT FROM b.dimensions
"""

# Группы, чьи ops-строки взаимно погашаются в ноль, надо убрать ДО переноса
# суммы на представителя: `ck_stock_balances_nonzero` — обычный CHECK, он не
# откладывается до конца транзакции, и UPDATE с нулём упал бы, не дойдя до
# удаления. После этого шага сумма любой группы строго не нулевая.
_DOWNGRADE_DROP_ZERO_SQL = """
DELETE FROM stock_balances a
USING (
    SELECT product_id, location_id, quality_state, dimensions
    FROM stock_balances
    GROUP BY product_id, location_id, quality_state, dimensions
    HAVING SUM(balance_qty) = 0
) AS zero
WHERE a.product_id = zero.product_id
  AND a.location_id = zero.location_id
  AND a.quality_state = zero.quality_state
  AND a.dimensions IS NOT DISTINCT FROM zero.dimensions
"""


def upgrade() -> None:
    # Конвенция 052: повторный прогон (``stamp`` назад + ``upgrade head`` —
    # так это проверяют тесты 065/066/068/071) идёт поверх уже поднятой схемы,
    # поэтому колонки добавляются с ``IF NOT EXISTS``, а смена unique-констрейнта
    # выполняется по факту его наличия.
    bind = op.get_bind()
    existing_unique = {
        constraint["name"] for constraint in sa.inspect(bind).get_unique_constraints("stock_balances")
    }
    op.add_column(
        "stock_balances",
        sa.Column("completed_operations", JSONB(), nullable=True),
        if_not_exists=True,
    )
    # Признак самой строки импорта: «посмотреть» в истории ищет текущий
    # остаток строки по полному пятиосевому ключу, а он берётся отсюда
    # (`StockImportRow.completed_operations`, ADR-0055 п.5).
    op.add_column(
        "stock_import_rows",
        sa.Column("completed_operations", JSONB(), nullable=True),
        if_not_exists=True,
    )

    if OLD_CONSTRAINT in existing_unique:
        op.drop_constraint(OLD_CONSTRAINT, "stock_balances", type_="unique")
    if NEW_CONSTRAINT not in existing_unique:
        op.create_unique_constraint(
            NEW_CONSTRAINT,
            "stock_balances",

            [
                "product_id",
                "location_id",
                "quality_state",
                "dimensions",
                "completed_operations",
            ],
            postgresql_nulls_not_distinct=True,
        )
    op.execute(_BACKFILL_SQL)


def downgrade() -> None:
    # Схлопывание групп обратно: строка на пару (product, location, quality,
    # dimensions) должна быть одна, иначе прежняя уникальность не накладывается.
    # Порядок: убрать взаимно погашенные группы, перенести сумму на
    # представителя, удалить остальные строки.
    op.execute(_DOWNGRADE_DROP_ZERO_SQL)
    op.execute(_DOWNGRADE_SUM_SQL)
    op.execute(_DOWNGRADE_DEDUP_SQL)
    op.drop_constraint(NEW_CONSTRAINT, "stock_balances", type_="unique")
    op.create_unique_constraint(
        OLD_CONSTRAINT,
        "stock_balances",
        ["product_id", "location_id", "quality_state", "dimensions"],
        postgresql_nulls_not_distinct=True,
    )
    op.drop_column("stock_import_rows", "completed_operations")
    op.drop_column("stock_balances", "completed_operations")
