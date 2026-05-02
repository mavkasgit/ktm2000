"""imports production plans

Revision ID: 0003_imports_production_plans
Revises: 0002_products_boms_routes
Create Date: 2026-05-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0003_imports_production_plans"
down_revision: Union[str, None] = "0002_products_boms_routes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

import_batch_mode = sa.Enum("create_plan", "append_to_plan", "replace_draft_from_same_source", name="import_batch_mode")
import_batch_status = sa.Enum("parsed", "failed", "applied", "cancelled", name="import_batch_status")
production_plan_status = sa.Enum(
    "draft", "validated", "approved", "partially_released", "released", "cancelled", name="production_plan_status"
)
plan_source_type = sa.Enum("manual", "excel_import", "api", "integration", name="plan_source_type")
plan_position_status = sa.Enum("draft", "invalid", "valid", "approved", "released", "cancelled", name="plan_position_status")
plan_position_validation_status = sa.Enum("pending", "valid", "invalid", name="plan_position_validation_status")
plan_change_set_status = sa.Enum("draft", "applied", "cancelled", name="plan_change_set_status")
plan_change_action = sa.Enum(
    "create_position",
    "update_draft_position",
    "mark_possible_duplicate",
    "ignore_unchanged",
    "cancel_draft_position",
    name="plan_change_action",
)
plan_change_item_status = sa.Enum("pending", "warning", "invalid", "applied", name="plan_change_item_status")


def upgrade() -> None:
    op.create_table(
        "import_files",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("original_filename", sa.String(length=500), nullable=False),
        sa.Column("stored_path", sa.String(length=1000), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("file_extension", sa.String(length=20), nullable=False),
        sa.Column("detected_format", sa.String(length=50), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("file_sha256", name="uq_import_files_file_sha256"),
    )

    op.create_table(
        "production_plans",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("plan_no", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", production_plan_status, nullable=False, server_default=sa.text("'draft'")),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("plan_no", name="uq_production_plans_plan_no"),
    )

    op.create_table(
        "import_batches",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("source_file_id", sa.BigInteger(), sa.ForeignKey("import_files.id"), nullable=False),
        sa.Column("production_plan_id", sa.BigInteger(), sa.ForeignKey("production_plans.id"), nullable=False),
        sa.Column("mode", import_batch_mode, nullable=False),
        sa.Column("status", import_batch_status, nullable=False, server_default=sa.text("'parsed'")),
        sa.Column("source_system", sa.String(length=100), nullable=False, server_default=sa.text("'excel'")),
        sa.Column("sheet_name", sa.String(length=255), nullable=False),
        sa.Column("header_row_number", sa.BigInteger(), nullable=False),
        sa.Column("total_rows", sa.BigInteger(), nullable=False),
        sa.Column("parsed_rows", sa.BigInteger(), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "plan_positions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("production_plan_id", sa.BigInteger(), sa.ForeignKey("production_plans.id"), nullable=False),
        sa.Column("product_id", sa.BigInteger(), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("source_type", plan_source_type, nullable=False),
        sa.Column("source_system", sa.String(length=100), nullable=True),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("external_plan_id", sa.String(length=255), nullable=True),
        sa.Column("source_row_hash", sa.String(length=64), nullable=True),
        sa.Column("import_batch_id", sa.BigInteger(), sa.ForeignKey("import_batches.id"), nullable=True),
        sa.Column("source_sku", sa.String(length=255), nullable=False),
        sa.Column("source_name", sa.String(length=1000), nullable=True),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("source_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("customer", sa.String(length=255), nullable=True),
        sa.Column("priority", sa.BigInteger(), nullable=False, server_default=sa.text("100")),
        sa.Column("source_row_number", sa.BigInteger(), nullable=True),
        sa.Column("status", plan_position_status, nullable=False),
        sa.Column("validation_status", plan_position_validation_status, nullable=False),
        sa.Column("validation_errors", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("approved_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("quantity > 0", name="ck_plan_positions_quantity_gt_zero"),
    )
    op.create_index("ix_plan_positions_import_row", "plan_positions", ["import_batch_id", "source_row_number"], unique=True)
    op.create_index("ix_plan_positions_import_hash", "plan_positions", ["import_batch_id", "source_row_hash"], unique=True)

    op.create_table(
        "plan_change_sets",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("production_plan_id", sa.BigInteger(), sa.ForeignKey("production_plans.id"), nullable=False),
        sa.Column("import_batch_id", sa.BigInteger(), sa.ForeignKey("import_batches.id"), nullable=True),
        sa.Column("status", plan_change_set_status, nullable=False, server_default=sa.text("'draft'")),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "plan_change_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("change_set_id", sa.BigInteger(), sa.ForeignKey("plan_change_sets.id"), nullable=False),
        sa.Column("plan_position_id", sa.BigInteger(), sa.ForeignKey("plan_positions.id"), nullable=True),
        sa.Column("source_row_number", sa.BigInteger(), nullable=True),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.Column("change_action", plan_change_action, nullable=False),
        sa.Column("before_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", plan_change_item_status, nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_plan_change_items_change_set", "plan_change_items", ["change_set_id"])


def downgrade() -> None:
    op.drop_index("ix_plan_change_items_change_set", table_name="plan_change_items")
    op.drop_table("plan_change_items")
    op.drop_table("plan_change_sets")
    op.drop_index("ix_plan_positions_import_hash", table_name="plan_positions")
    op.drop_index("ix_plan_positions_import_row", table_name="plan_positions")
    op.drop_table("plan_positions")
    op.drop_table("import_batches")
    op.drop_table("production_plans")
    op.drop_table("import_files")
    plan_change_item_status.drop(op.get_bind(), checkfirst=True)
    plan_change_action.drop(op.get_bind(), checkfirst=True)
    plan_change_set_status.drop(op.get_bind(), checkfirst=True)
    plan_position_validation_status.drop(op.get_bind(), checkfirst=True)
    plan_position_status.drop(op.get_bind(), checkfirst=True)
    plan_source_type.drop(op.get_bind(), checkfirst=True)
    production_plan_status.drop(op.get_bind(), checkfirst=True)
    import_batch_status.drop(op.get_bind(), checkfirst=True)
    import_batch_mode.drop(op.get_bind(), checkfirst=True)
