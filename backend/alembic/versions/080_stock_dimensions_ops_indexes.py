"""Индексы JSONB-осей ledger: dimensions (GIN) и completed_operations (btree) (#080)

Фильтр пересчёта баланса (``StockProjectionManager._recompute_balance``, Fix A
— сумма теперь считается в SQL) отбирает проводки по ключу
``(product, location, quality, dimensions, completed_operations)``: последние
две оси — JSONB и раньше читались без индекса.

* ``stock_transactions.dimensions`` — **GIN jsonb_ops**. Честное ограничение:
  ``dimensions_match_clause`` сравнивает jsonb через ``=`` (плюс ``IS NULL``
  для legacy-группы), а GIN обслуживает только containment-операторы
  (``@>``, ``?``, ``?|``, ``?&``) — равенство индекс НЕ ускоряет. Он даёт
  опору под containment-предикаты, если появятся (сейчас в коде их нет:
  ``@>`` используется только по ``Product.aliases``). Равенство по этой
  колонке обслуживается левыми префиксами ``(product_id)`` /
  ``(to_location_id, created_at)``.

* ``stock_transactions.completed_operations`` — **btree по колонке**. Это
  ровно выражение ``completed_operations_match_clause``:
  ``column = <список>::jsonb`` для непустого признака (jsonb входит в btree
  opclass, равенство индексируемо) и ``column IS NULL OR column =
  'null'::jsonb`` для ``None`` — обе ветки btree-равенство/IS NULL, поиск по
  индексу возможен. ``[]`` против ``NULL`` (ADR-0055) индекс не смешивает:
  это разные ключи и в btree, как и в данных.

``stock_balances`` не индексируем: там уже лежит
``uq_stock_balances_product_location_quality_dims_ops`` (NULLS NOT DISTINCT),
чей префикс ``(product_id, location_id, quality_state)`` плюс равенство по
осям покрывает lookup баланса целиком.

Всё объявлено и в модели (``StockTransaction.__table_args__``): тестовая
схема строится ``create_all`` и миграции не видит.

``if_not_exists``/``if_exists`` — конвенция цепочки (049, 052, 054, 072,
074, 077, 078, 079): тесты миграций повторно проходят последние версии по
живой схеме.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "080_stock_dimensions_ops_indexes"
#: 079 (`plan_position_validation_warnings`, #328) — предыдущая в линейной цепочке.
down_revision: str | None = "079_plan_position_validation_warnings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_stock_transactions_dimensions_gin",
        "stock_transactions",
        ["dimensions"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"dimensions": "jsonb_ops"},
        if_not_exists=True,
    )
    op.create_index(
        "ix_stock_transactions_completed_operations",
        "stock_transactions",
        ["completed_operations"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_stock_transactions_completed_operations",
        table_name="stock_transactions",
        if_exists=True,
    )
    op.drop_index(
        "ix_stock_transactions_dimensions_gin",
        table_name="stock_transactions",
        if_exists=True,
    )
