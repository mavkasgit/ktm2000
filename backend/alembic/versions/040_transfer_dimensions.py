"""Transfer.dimensions — передача несёт размер, как ledger (тикет #90).

Передача по паре (задача, размер): колонка dimensions в канонической
форме JSONB (как WorkTask.dimensions / StockTransaction.dimensions).
None — безразмерные штуки. Легаси-передачи без размера остаются NULL.

Revision ID: 040_transfer_dimensions
Revises: 039_work_task_dimensions
Create Date: 2026-08-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "040_transfer_dimensions"
down_revision: Union[str, None] = "039_work_task_dimensions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transfers",
        sa.Column("dimensions", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transfers", "dimensions")
