"""031_fix_complete_double_balance_after_transfer

COMPLETE с from=None после TRANSFER_SEND дублировал остаток на приёмнике.
Для задач с TRANSFER_RECEIVE (issued) выставляем from=to=section (net-zero)
и пересчитываем stock_balances.

Revision ID: 031_fix_complete_double
Revises: 030_fix_xfer_recv_balance
Create Date: 2026-07-04 20:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "031_fix_complete_double"
down_revision: Union[str, None] = "030_fix_xfer_recv_balance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_stock_transactions_locations_differ",
        "stock_transactions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_stock_transactions_locations_differ",
        "stock_transactions",
        "from_location_id IS NULL OR to_location_id IS NULL "
        "OR from_location_id <> to_location_id "
        "OR reason = 'complete'",
    )
    op.execute(
        """
        UPDATE stock_transactions st
        SET from_location_id = st.to_location_id
        WHERE st.reason = 'complete'
          AND st.from_location_id IS NULL
          AND st.to_location_id IS NOT NULL
          AND st.task_id IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM stock_transactions recv
            WHERE recv.task_id = st.task_id
              AND recv.reason = 'transfer_receive'
              AND recv.transfer_id IS NOT NULL
          )
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