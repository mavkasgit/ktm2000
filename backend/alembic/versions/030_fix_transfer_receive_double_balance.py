"""030_fix_transfer_receive_double_balance

TRANSFER_RECEIVE при transfer_send не должен дублировать физическое движение
остатков (его выполняет TRANSFER_SEND). Обнуляем локации у существующих
TRANSFER_RECEIVE с transfer_id и пересчитываем stock_balances.

Revision ID: 030_fix_xfer_recv_balance
Revises: 029_final_scrap_qs
Create Date: 2026-07-04 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "030_fix_xfer_recv_balance"
down_revision: Union[str, None] = "029_final_scrap_qs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_stock_transactions_at_least_one_location",
        "stock_transactions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_stock_transactions_at_least_one_location",
        "stock_transactions",
        "(from_location_id IS NOT NULL) OR (to_location_id IS NOT NULL) "
        "OR (reason = 'transfer_receive')",
    )
    op.execute(
        """
        UPDATE stock_transactions
        SET from_location_id = NULL,
            to_location_id = NULL
        WHERE reason = 'transfer_receive'
          AND transfer_id IS NOT NULL
        """
    )
    op.execute("DELETE FROM stock_balances")
    op.execute(
        """
        INSERT INTO stock_balances (product_id, location_id, quality_state, balance_qty, refreshed_at)
        SELECT product_id,
               location_id,
               quality_state,
               balance,
               NOW()
        FROM (
            SELECT product_id,
                   location_id,
                   quality_state,
                   SUM(delta) AS balance
            FROM (
                SELECT product_id,
                       to_location_id AS location_id,
                       to_quality_state AS quality_state,
                       quantity AS delta
                FROM stock_transactions
                WHERE to_location_id IS NOT NULL
                UNION ALL
                SELECT product_id,
                       from_location_id AS location_id,
                       from_quality_state AS quality_state,
                       -quantity AS delta
                FROM stock_transactions
                WHERE from_location_id IS NOT NULL
            ) movements
            GROUP BY product_id, location_id, quality_state
            HAVING SUM(delta) <> 0
        ) aggregated
        """
    )


def downgrade() -> None:
    # Восстановление прежней геометрии невозможно без потери точности.
    pass