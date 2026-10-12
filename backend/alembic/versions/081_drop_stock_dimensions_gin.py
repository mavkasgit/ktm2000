"""Дроп GIN-индекса stock_transactions.dimensions: ось обслуживает только «=» (#081)

Миграция 080 поставила на ``dimensions`` GIN jsonb_ops «под containment-предикаты,
если появятся». Они не появились: единственный потребитель оси —
``dimensions_match_clause`` — сравнивает jsonb через ``=`` (плюс ``IS NULL``
для legacy-группы), а GIN обслуживает только containment-операторы
(``@>``, ``?``, ``?|``, ``?&``). Индекс не ускорял ни одного запроса, но
платил за каждый INSERT/UPDATE ledger'а write amplification.

``stock_transactions.completed_operations`` — btree по колонке — остаётся:
он обслуживает ``completed_operations_match_clause`` (jsonb-равенство и
IS NULL обе индексируемы btree).

``if_exists`` — конвенция цепочки (049, 052, 054, 072, 074, 077, 078, 079,
080): тесты миграций повторно проходят последние версии по живой схеме.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "081_drop_stock_dimensions_gin"
#: 080 (`stock_dimensions_ops_indexes`) — предыдущая в линейной цепочке.
down_revision: str | None = "080_stock_dimensions_ops_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        "ix_stock_transactions_dimensions_gin",
        table_name="stock_transactions",
        if_exists=True,
    )


def downgrade() -> None:
    op.create_index(
        "ix_stock_transactions_dimensions_gin",
        "stock_transactions",
        ["dimensions"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"dimensions": "jsonb_ops"},
        if_not_exists=True,
    )
