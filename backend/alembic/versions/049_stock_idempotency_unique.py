"""Идемпотентность ledger: partial unique на idempotency_key (ADR-0022).

record() обеспечивал идемпотентность SELECT-then-INSERT без констрейнта:
в READ COMMITTED две конкурентные подачи с одним ключом (retry сети,
double-click) создавали две проводки. Partial unique-индекс — бэкстоп;
проигравший гонку получает 409 (StockIdempotencyConflict) и повторяет
операцию с тем же ключом. Старый неуникальный индекс дропается — partial
unique обслуживает и поиск по равенству.

Fail-fast: существующие дубликаты уронят создание unique-индекса.
Диагностика для оператора:
    SELECT idempotency_key, count(*) FROM stock_transactions
    WHERE idempotency_key IS NOT NULL
    GROUP BY 1 HAVING count(*) > 1;
Дубли лечатся компенсацией (ADR-0019), не удалением миграцией.

Revision ID: 049_stock_idempotency_unique
Revises: 048_product_hanger_mode_backfill
Create Date: 2026-09-05 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "049_stock_idempotency_unique"
down_revision: Union[str, None] = "048_product_hanger_mode_backfill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Сначала unique (fail-fast на дубликатах: старый индекс остаётся жив,
    # если создание упало), затем дроп устаревшего неуникального.
    # if_not_exists/if_exists: конвенция проекта — повторный прогон миграции
    # (stamp назад + upgrade head, см. tests/test_migrations.py) безопасен.
    op.create_index(
        "uq_stock_transactions_idempotency_key",
        "stock_transactions",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        if_not_exists=True,
    )
    op.drop_index(
        "ix_stock_transactions_idempotency_key",
        table_name="stock_transactions",
        if_exists=True,
    )


def downgrade() -> None:
    op.create_index(
        op.f("ix_stock_transactions_idempotency_key"),
        "stock_transactions",
        ["idempotency_key"],
        unique=False,
        if_not_exists=True,
    )
    op.drop_index(
        "uq_stock_transactions_idempotency_key",
        table_name="stock_transactions",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        if_exists=True,
    )
