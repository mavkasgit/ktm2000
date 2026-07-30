"""dimensions в stock ledger: JSONB-габарит на транзакции и в ключе баланса (ADR-0001)

Мягкая миграция: обе колонки nullable, старые записи остаются NULL
(«безразмерные штуки» / legacy). Уникальный ключ баланса расширяется
габаритом; NULLS NOT DISTINCT (PG15+), чтобы legacy-группа с NULL-габаритом
не могла задвоиться.

Revision ID: 023_stock_dimensions
Revises: 022_dimension_types
Create Date: 2026-07-31

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "023_stock_dimensions"
down_revision = "022_dimension_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stock_transactions",
        sa.Column("dimensions", JSONB(), nullable=True),
    )
    op.add_column(
        "stock_balances",
        sa.Column("dimensions", JSONB(), nullable=True),
    )
    op.drop_constraint(
        "uq_stock_balances_product_location_quality",
        "stock_balances",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_stock_balances_product_location_quality_dims",
        "stock_balances",
        ["product_id", "location_id", "quality_state", "dimensions"],
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_stock_balances_product_location_quality_dims",
        "stock_balances",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_stock_balances_product_location_quality",
        "stock_balances",
        ["product_id", "location_id", "quality_state"],
    )
    op.drop_column("stock_balances", "dimensions")
    op.drop_column("stock_transactions", "dimensions")
