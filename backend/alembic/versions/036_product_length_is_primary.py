"""основная длина артикула: is_primary на product_lengths (#81).

Существующим артикулам основная назначается по текущему правилу —
первая длина по возрастанию (как раньше выбирал `_primary_hanger_length_key`).
Partial unique index гарантирует не более одной основной на продукт.

Revision ID: 036_product_length_is_primary
Revises: 035_internal_notifications
Create Date: 2026-08-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "036_product_length_is_primary"
down_revision: Union[str, None] = "035_internal_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "product_lengths",
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    # Назначить основную существующим артикулам: первая длина по возрастанию.
    op.execute(
        """
        UPDATE product_lengths pl
        SET is_primary = true
        WHERE pl.id IN (
            SELECT DISTINCT ON (product_id) id
            FROM product_lengths
            ORDER BY product_id, length_mm ASC, id ASC
        )
        """
    )
    op.create_index(
        "uq_product_lengths_one_primary_per_product",
        "product_lengths",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )


def downgrade() -> None:
    op.drop_index("uq_product_lengths_one_primary_per_product", table_name="product_lengths")
    op.drop_column("product_lengths", "is_primary")
