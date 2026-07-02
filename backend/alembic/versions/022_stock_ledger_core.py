"""022_stock_ledger_core

Этап 1 рефакторинга Stock Ledger (см. PLAN_stock_ledger.md).

Создаёт новый домен inventory параллельно существующему Movement/SpgRemainder:
- ``location_type`` enum + ``sections.type`` — Location как расширение Section
- ``stock_reason`` enum — явные причины движений (без знаковой интерпретации)
- ``stock_quality_state`` enum — GOOD/SCRAP/REWORK/QUARANTINE
- ``stock_transactions`` — единый append-only ledger (from→to locations)
- ``stock_balances`` — материализованный кэш баланса по (product, location, quality)

Старые таблицы (movements, spg_remainders) НЕ трогаются — двойная запись
живёт до Этапа 7. Все новые инвариант-проверки в test_integrity_invariants.py
автоматически активируются после применения этой миграции.

Data-migration kind→type:
- raw_stock     → raw_stock
- wip_stock     → wip_stock
- finished_stock→ finished_stock
- production    → production  (уточняется до laser/welding/... через UI позже)

Revision ID: 022_stock_ledger_core
Revises: 021_route_stage_section_nullable
Create Date: 2026-07-03 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "022_stock_ledger_core"
down_revision: Union[str, None] = "021_route_stage_section_nullable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LOCATION_TYPE_VALUES = (
    "raw_stock", "wip_stock", "finished_stock", "production",
    "laser", "welding", "painting", "assembly",
    "scrap", "quarantine", "transit",
)
STOCK_REASON_VALUES = (
    "issue_to_work", "complete", "transfer_send", "transfer_receive",
    "return_to_stock", "return_to_previous", "final_release",
    "scrap", "rework", "adjustment_in", "adjustment_out",
    "manual_in", "manual_out",
)
STOCK_QUALITY_STATE_VALUES = ("good", "scrap", "rework", "quarantine")


def _enum(name: str, values: tuple[str, ...]) -> postgresql.ENUM:
    """ postgresql.ENUM с create_type=False — тип создаётся отдельно через
    op.execute ниже, чтобы была идемпотентность и контроль порядком. """
    return postgresql.ENUM(*values, name=name, create_type=False)


def upgrade() -> None:
    # --- enum types (идемпотентное CREATE через DO $$ — можно в транзакции) ---
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'location_type') THEN "
        "CREATE TYPE location_type AS ENUM ("
        + ", ".join(f"'{v}'" for v in LOCATION_TYPE_VALUES)
        + "); "
        "END IF; "
        "END $$;"
    )
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'stock_reason') THEN "
        "CREATE TYPE stock_reason AS ENUM ("
        + ", ".join(f"'{v}'" for v in STOCK_REASON_VALUES)
        + "); "
        "END IF; "
        "END $$;"
    )
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'stock_quality_state') THEN "
        "CREATE TYPE stock_quality_state AS ENUM ("
        + ", ".join(f"'{v}'" for v in STOCK_QUALITY_STATE_VALUES)
        + "); "
        "END IF; "
        "END $$;"
    )

    # --- sections.type column + data-migration from kind ---
    op.add_column(
        "sections",
        sa.Column("type", _enum("location_type", LOCATION_TYPE_VALUES), nullable=True),
    )
    op.execute(
        """
        UPDATE sections SET type = CASE
            WHEN kind = 'raw_stock'      THEN 'raw_stock'::location_type
            WHEN kind = 'wip_stock'      THEN 'wip_stock'::location_type
            WHEN kind = 'finished_stock' THEN 'finished_stock'::location_type
            ELSE 'production'::location_type
        END
        """
    )

    # --- stock_transactions ---
    op.create_table(
        "stock_transactions",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True, autoincrement=True),
        sa.Column("product_id", sa.BigInteger, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("from_location_id", sa.BigInteger, sa.ForeignKey("sections.id"), nullable=True),
        sa.Column("to_location_id", sa.BigInteger, sa.ForeignKey("sections.id"), nullable=True),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("reason", _enum("stock_reason", STOCK_REASON_VALUES), nullable=False),
        sa.Column("from_quality_state", _enum("stock_quality_state", STOCK_QUALITY_STATE_VALUES),
                  nullable=False, server_default="good"),
        sa.Column("to_quality_state", _enum("stock_quality_state", STOCK_QUALITY_STATE_VALUES),
                  nullable=False, server_default="good"),
        sa.Column("task_id", sa.BigInteger, sa.ForeignKey("work_tasks.id"), nullable=True),
        sa.Column("transfer_id", sa.BigInteger, sa.ForeignKey("transfers.id"), nullable=True),
        sa.Column("section_plan_line_id", sa.BigInteger, sa.ForeignKey("section_plan_lines.id"), nullable=True),
        sa.Column("compensates_tx_id", sa.BigInteger, sa.ForeignKey("stock_transactions.id"), nullable=True),
        sa.Column("source_ref", sa.String(255), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("created_by", sa.BigInteger, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("executor_user_id", sa.BigInteger, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_by_user_name", sa.String(255), nullable=True),
        sa.Column("executor_user_name", sa.String(255), nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accounted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_post_factum", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("quantity > 0", name="ck_stock_transactions_quantity_positive"),
        sa.CheckConstraint(
            "(from_location_id IS NOT NULL) OR (to_location_id IS NOT NULL)",
            name="ck_stock_transactions_at_least_one_location",
        ),
        sa.CheckConstraint(
            "from_location_id IS NULL OR to_location_id IS NULL OR from_location_id <> to_location_id",
            name="ck_stock_transactions_locations_differ",
        ),
    )
    op.create_index("ix_stock_transactions_product_id", "stock_transactions", ["product_id"])
    op.create_index("ix_stock_transactions_from_location_id", "stock_transactions", ["from_location_id"])
    op.create_index("ix_stock_transactions_to_location_id", "stock_transactions", ["to_location_id"])
    op.create_index("ix_stock_transactions_reason", "stock_transactions", ["reason"])
    op.create_index("ix_stock_transactions_from_quality_state", "stock_transactions", ["from_quality_state"])
    op.create_index("ix_stock_transactions_to_quality_state", "stock_transactions", ["to_quality_state"])
    op.create_index("ix_stock_transactions_task_id", "stock_transactions", ["task_id"])
    op.create_index("ix_stock_transactions_transfer_id", "stock_transactions", ["transfer_id"])
    op.create_index("ix_stock_transactions_idempotency_key", "stock_transactions", ["idempotency_key"])
    op.create_index(
        "ix_stock_transactions_balance_lookup_in",
        "stock_transactions",
        ["product_id", "to_location_id", "to_quality_state"],
    )
    op.create_index(
        "ix_stock_transactions_balance_lookup_out",
        "stock_transactions",
        ["product_id", "from_location_id", "from_quality_state"],
    )

    # --- stock_balances ---
    op.create_table(
        "stock_balances",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True, autoincrement=True),
        sa.Column("product_id", sa.BigInteger, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("location_id", sa.BigInteger, sa.ForeignKey("sections.id"), nullable=False),
        sa.Column("quality_state", _enum("stock_quality_state", STOCK_QUALITY_STATE_VALUES),
                  nullable=False, server_default="good"),
        sa.Column("balance_qty", sa.Numeric(14, 3), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "product_id", "location_id", "quality_state",
            name="uq_stock_balances_product_location_quality",
        ),
        sa.CheckConstraint("balance_qty <> 0", name="ck_stock_balances_nonzero"),
    )
    op.create_index("ix_stock_balances_product_id", "stock_balances", ["product_id"])
    op.create_index("ix_stock_balances_location_id", "stock_balances", ["location_id"])


def downgrade() -> None:
    op.drop_index("ix_stock_balances_location_id", table_name="stock_balances")
    op.drop_index("ix_stock_balances_product_id", table_name="stock_balances")
    op.drop_table("stock_balances")

    op.drop_index("ix_stock_transactions_balance_lookup_out", table_name="stock_transactions")
    op.drop_index("ix_stock_transactions_balance_lookup_in", table_name="stock_transactions")
    op.drop_index("ix_stock_transactions_idempotency_key", table_name="stock_transactions")
    op.drop_index("ix_stock_transactions_transfer_id", table_name="stock_transactions")
    op.drop_index("ix_stock_transactions_task_id", table_name="stock_transactions")
    op.drop_index("ix_stock_transactions_to_quality_state", table_name="stock_transactions")
    op.drop_index("ix_stock_transactions_from_quality_state", table_name="stock_transactions")
    op.drop_index("ix_stock_transactions_reason", table_name="stock_transactions")
    op.drop_index("ix_stock_transactions_to_location_id", table_name="stock_transactions")
    op.drop_index("ix_stock_transactions_from_location_id", table_name="stock_transactions")
    op.drop_index("ix_stock_transactions_product_id", table_name="stock_transactions")
    op.drop_table("stock_transactions")

    op.drop_column("sections", "type")

    op.execute("DROP TYPE IF EXISTS stock_quality_state")
    op.execute("DROP TYPE IF EXISTS stock_reason")
    op.execute("DROP TYPE IF EXISTS location_type")
