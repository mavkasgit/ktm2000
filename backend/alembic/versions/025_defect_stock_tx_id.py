"""025_defect_stock_tx_id

Этап 5 рефакторинга Stock Ledger (см. PLAN_stock_ledger.md).

Defect → StockTransaction связь:
- 'quarantine' value added to stock_reason enum
- defects.stock_transaction_id FK → stock_transactions.id

Revision ID: 025_defect_stock_tx_id
Revises: 024_drop_cached_columns
Create Date: 2026-07-03 20:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "025_defect_stock_tx_id"
down_revision: Union[str, None] = "024_drop_cached_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE stock_reason ADD VALUE IF NOT EXISTS 'quarantine'"
        )

    op.add_column(
        "defects",
        sa.Column("stock_transaction_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_defects_stock_transaction_id",
        "defects", "stock_transactions",
        ["stock_transaction_id"], ["id"],
    )
    op.create_index(
        "ix_defects_stock_transaction_id",
        "defects", ["stock_transaction_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_defects_stock_transaction_id", table_name="defects")
    op.drop_constraint("fk_defects_stock_transaction_id", "defects", type_="foreignkey")
    op.drop_column("defects", "stock_transaction_id")
    # ALTER TYPE ... ADD VALUE is irreversible in a downgrade.
    # The 'quarantine' value remains in the enum to avoid data loss.
