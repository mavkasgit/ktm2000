"""add_techcard_quantity_hanger_and_nullable_product

Revision ID: 002_techcards_fields
Revises: 001_products_aliases
Create Date: 2026-05-04 00:01:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_techcards_fields'
down_revision: Union[str, None] = '001_products_aliases'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Quantity fields
    op.add_column("techcards", sa.Column("quantity_total", sa.Integer(), nullable=True))
    op.add_column("techcards", sa.Column("quantity_a_per_item", sa.Integer(), nullable=True))
    op.add_column("techcards", sa.Column("quantity_b_per_item", sa.Integer(), nullable=True))

    # Hanger fields
    op.add_column("techcards", sa.Column("hangers_a", sa.Integer(), nullable=True))
    op.add_column("techcards", sa.Column("hangers_b", sa.Integer(), nullable=True))
    op.add_column("techcards", sa.Column("hangers_total", sa.Integer(), nullable=True))

    # Drop old partial index (was on product_id when not nullable)
    op.drop_index("ix_techcards_active_one_per_product", table_name="techcards")

    # Make product_id nullable for standalone paired techcards
    op.alter_column("techcards", "product_id", nullable=True)

    # Add FK index (Supabase: 10-100x faster JOINs and CASCADE operations)
    op.create_index("ix_techcards_product_id", "techcards", ["product_id"])

    # New partial index for active techcards (Supabase: 5-20x smaller index)
    op.create_index(
        "ix_techcards_active_one_per_product",
        "techcards",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true AND product_id IS NOT NULL")
    )


def downgrade() -> None:
    op.drop_index("ix_techcards_active_one_per_product", table_name="techcards")
    op.drop_index("ix_techcards_product_id", table_name="techcards")
    op.alter_column("techcards", "product_id", nullable=False)
    op.create_index(
        "ix_techcards_active_one_per_product",
        "techcards",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true")
    )
    op.drop_column("techcards", "hangers_total")
    op.drop_column("techcards", "hangers_b")
    op.drop_column("techcards", "hangers_a")
    op.drop_column("techcards", "quantity_b_per_item")
    op.drop_column("techcards", "quantity_a_per_item")
    op.drop_column("techcards", "quantity_total")
