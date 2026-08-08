"""добавить уникальный код товара (code).

Revision ID: 033_product_code
Revises: 032_product_quantity_per_hanger_per_length
Create Date: 2026-08-08 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "033_product_code"
down_revision: Union[str, None] = "032_product_quantity_per_hanger_per_length"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("code", sa.String(length=100), nullable=True))
    op.create_index("ix_products_code", "products", ["code"], unique=False)
    op.create_unique_constraint("uq_products_code", "products", ["code"])


def downgrade() -> None:
    op.drop_constraint("uq_products_code", "products", type_="unique")
    op.drop_index("ix_products_code", table_name="products")
    op.drop_column("products", "code")
