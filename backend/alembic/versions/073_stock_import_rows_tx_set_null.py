"""Ссылка строки импорта на проводку — `ON DELETE SET NULL` (#232, ADR-0052).

Миграция 072 создала `stock_import_rows.stock_transaction_id` как обычный FK.
Это оказалось неверно: ссылка справочная, а ledger — источник истины, и любая
чистка проводок (сид с `--force`, `reset-all`, `hard purge`) падала на
`ForeignKeyViolationError`. Обнаружено на e2e-стенде: `e2e:prep` падал на
`DELETE FROM stock_transactions`.

Констрейнт пересоздаётся, а не правится на месте: 072 уже применена на dev- и
e2e-БД, и правка применённой миграции их бы не обновила.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "073_stock_import_rows_tx_set_null"
down_revision: str | None = "072_stock_import_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "fk_stock_import_rows_stock_transaction_id_stock_transactions"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, "stock_import_rows", type_="foreignkey")
    op.create_foreign_key(
        CONSTRAINT,
        "stock_import_rows",
        "stock_transactions",
        ["stock_transaction_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Обратно к строгому FK: строки, потерявшие проводку, сломают сид, но
    # откат миграции — осознанный отказ от выбранной семантики.
    op.execute("DELETE FROM stock_import_rows WHERE stock_transaction_id IS NULL")
    op.drop_constraint(CONSTRAINT, "stock_import_rows", type_="foreignkey")
    op.create_foreign_key(
        CONSTRAINT,
        "stock_import_rows",
        "stock_transactions",
        ["stock_transaction_id"],
        ["id"],
    )
