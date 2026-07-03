"""026_cleanup_legacy_tables

Этап 7 рефакторинга Stock Ledger (см. PLAN_stock_ledger.md).

Удаление legacy таблиц:
- spg_remainders
- movements
- movement_type enum

Также удаление legacy FK из defects:
- defects.movement_id
- defects.spg_remainder_id

Revision ID: 026_cleanup_legacy_tables
Revises: 025_defect_stock_tx_id
Create Date: 2026-07-03 22:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "026_cleanup_legacy_tables"
down_revision: Union[str, None] = "025_defect_stock_tx_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop FK constraints from defects
    op.drop_constraint("defects_movement_id_fkey", "defects", type_="foreignkey")
    op.drop_constraint("defects_spg_remainder_id_fkey", "defects", type_="foreignkey")
    op.drop_column("defects", "movement_id")
    op.drop_column("defects", "spg_remainder_id")

    # Drop legacy tables
    op.drop_table("movements")
    op.drop_table("spg_remainders")

    # Drop legacy enum type
    op.execute("DROP TYPE IF EXISTS movement_type")


def downgrade() -> None:
    # Re-create movement_type enum
    op.execute("""
        CREATE TYPE movement_type AS ENUM (
            'issue_to_work', 'complete', 'transfer_send', 'transfer_receive',
            'reject', 'scrap', 'return_to_previous', 'final_release',
            'adjustment', 'return_to_stock', 'manual_in', 'manual_out'
        )
    """)

    # Re-create spg_remainders table
    op.create_table(
        "spg_remainders",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("spg_id", sa.Integer(), nullable=False),
        sa.Column("route_stage_id", sa.Integer(), nullable=True),
        sa.Column("section_plan_line_id", sa.Integer(), nullable=True),
        sa.Column("origin_task_id", sa.Integer(), nullable=True),
        sa.Column("remainder_quantity", sa.Numeric(14, 3), server_default=sa.text("0"), nullable=False),
        sa.Column("original_issued", sa.Numeric(14, 3), nullable=False),
        sa.Column("completed_stages_json", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("source", sa.String(20), server_default=sa.text("'task'"), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_by_user_name", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_by_task_id", sa.Integer(), nullable=True),
        sa.Column("reserved_for_plan_position_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=sa.QuotedName("spg_remainders_pkey")),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name="spg_remainders_product_id_fkey"),
        sa.ForeignKeyConstraint(["spg_id"], ["storage_production_groups.id"], name="spg_remainders_spg_id_fkey", ondelete="CASCADE"),
    )

    # Re-create movements table
    op.create_table(
        "movements",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("section_plan_line_id", sa.Integer(), nullable=True),
        sa.Column("transfer_id", sa.Integer(), nullable=True),
        sa.Column("from_section_id", sa.Integer(), nullable=True),
        sa.Column("to_section_id", sa.Integer(), nullable=True),
        sa.Column("movement_type", sa.Enum("movement_type", name="movement_type"), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("source_ref", sa.String(255), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("executor_user_id", sa.Integer(), nullable=True),
        sa.Column("created_by_user_name", sa.String(255), nullable=True),
        sa.Column("executor_user_name", sa.String(255), nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accounted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_post_factum", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=sa.QuotedName("movements_pkey")),
        sa.CheckConstraint("quantity > 0", name="ck_movements_quantity_positive"),
    )

    # Re-add FK columns to defects
    op.add_column("defects", sa.Column("movement_id", sa.Integer(), nullable=True))
    op.add_column("defects", sa.Column("spg_remainder_id", sa.Integer(), nullable=True))
    op.create_foreign_key("defects_movement_id_fkey", "defects", "movements", ["movement_id"], ["id"])
    op.create_foreign_key("defects_spg_remainder_id_fkey", "defects", "spg_remainders", ["spg_remainder_id"], ["id"], ondelete="SET NULL")
