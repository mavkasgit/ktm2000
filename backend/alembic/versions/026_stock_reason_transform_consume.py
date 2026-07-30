"""Причина движения transform_consume (ADR-0002, завершение трансформации)

Списание входа трансформирующего этапа — отдельная причина ledger:
не смешивается с COMPLETE (приход выходов), поэтому проекция
completed_quantity остаётся суммой выходных штук.

Revision ID: 026_stock_reason_transform_consume
Revises: 025_route_stage_transform
Create Date: 2026-07-31

"""

from alembic import op

revision = "026_stock_reason_transform_consume"
down_revision = "025_route_stage_transform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PG15: ADD VALUE допустим внутри транзакции, если новое значение
    # не используется в той же транзакции.
    op.execute("ALTER TYPE stock_reason ADD VALUE IF NOT EXISTS 'transform_consume'")


def downgrade() -> None:
    # PostgreSQL не поддерживает удаление значения из enum;
    # неиспользуемое значение безвредно — no-op.
    pass
