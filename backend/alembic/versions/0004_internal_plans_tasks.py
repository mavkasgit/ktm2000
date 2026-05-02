"""internal plans tasks

Revision ID: 0004_internal_plans_tasks
Revises: 0003_imports_production_plans
Create Date: 2026-05-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0004_internal_plans_tasks"
down_revision: Union[str, None] = "0003_imports_production_plans"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

release_batch_type = sa.Enum("near_term", "weekly", "future_preparation", "manual", name="release_batch_type")
release_batch_status = sa.Enum("draft", "released", "cancelled", name="release_batch_status")
internal_plan_status = sa.Enum("active", "cancelled", "completed", name="internal_plan_status")
work_task_status = sa.Enum("waiting_previous", "ready", "in_progress", "completed", "cancelled", name="work_task_status")


def upgrade() -> None:
    op.create_table(
        "release_batches",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("batch_no", sa.String(length=100), nullable=False),
        sa.Column("production_plan_id", sa.BigInteger(), sa.ForeignKey("production_plans.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("batch_type", release_batch_type, nullable=False),
        sa.Column("status", release_batch_status, nullable=False, server_default=sa.text("'draft'")),
        sa.Column("horizon_start", sa.Date(), nullable=True),
        sa.Column("horizon_end", sa.Date(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("released_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("batch_no", name="uq_release_batches_batch_no"),
    )

    op.create_table(
        "release_batch_positions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("release_batch_id", sa.BigInteger(), sa.ForeignKey("release_batches.id"), nullable=False),
        sa.Column("plan_position_id", sa.BigInteger(), sa.ForeignKey("plan_positions.id"), nullable=False),
        sa.Column("release_quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("route_id", sa.BigInteger(), sa.ForeignKey("production_routes.id"), nullable=False),
        sa.Column("route_version", sa.String(length=100), nullable=False),
        sa.Column("route_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("release_batch_id", "plan_position_id", name="uq_release_batch_position"),
        sa.CheckConstraint("release_quantity > 0", name="ck_release_batch_positions_quantity_gt_zero"),
    )

    op.create_table(
        "internal_plans",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("production_plan_id", sa.BigInteger(), sa.ForeignKey("production_plans.id"), nullable=False),
        sa.Column("release_batch_id", sa.BigInteger(), sa.ForeignKey("release_batches.id"), nullable=True),
        sa.Column("status", internal_plan_status, nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_internal_plans_release_batch", "internal_plans", ["release_batch_id"], unique=True)

    op.create_table(
        "section_plan_lines",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("internal_plan_id", sa.BigInteger(), sa.ForeignKey("internal_plans.id"), nullable=False),
        sa.Column("plan_position_id", sa.BigInteger(), sa.ForeignKey("plan_positions.id"), nullable=False),
        sa.Column("section_id", sa.BigInteger(), sa.ForeignKey("sections.id"), nullable=False),
        sa.Column("product_id", sa.BigInteger(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("route_id", sa.BigInteger(), sa.ForeignKey("production_routes.id"), nullable=False),
        sa.Column("route_step_id", sa.BigInteger(), sa.ForeignKey("route_steps.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("planned_quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("cached_available_quantity", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("cached_issued_quantity", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("cached_completed_quantity", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("cached_transferred_quantity", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("cached_received_quantity", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("cached_rejected_quantity", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("cached_remaining_quantity", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.UniqueConstraint("internal_plan_id", "plan_position_id", "route_step_id", name="uq_section_plan_lines_step"),
        sa.CheckConstraint("planned_quantity > 0", name="ck_section_plan_lines_quantity_gt_zero"),
    )

    op.create_table(
        "work_tasks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("section_plan_line_id", sa.BigInteger(), sa.ForeignKey("section_plan_lines.id"), nullable=False),
        sa.Column("section_id", sa.BigInteger(), sa.ForeignKey("sections.id"), nullable=False),
        sa.Column("product_id", sa.BigInteger(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("route_step_id", sa.BigInteger(), sa.ForeignKey("route_steps.id"), nullable=False),
        sa.Column("planned_quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("status", work_task_status, nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("assigned_to", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("cached_available_quantity", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("cached_issued_quantity", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("cached_in_work_quantity", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("cached_completed_quantity", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("cached_transferred_quantity", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("cached_received_quantity", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("cached_rejected_quantity", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("cached_remaining_quantity", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint("planned_quantity > 0", name="ck_work_tasks_quantity_gt_zero"),
    )


def downgrade() -> None:
    op.drop_table("work_tasks")
    op.drop_table("section_plan_lines")
    op.drop_index("ix_internal_plans_release_batch", table_name="internal_plans")
    op.drop_table("internal_plans")
    op.drop_table("release_batch_positions")
    op.drop_table("release_batches")
    work_task_status.drop(op.get_bind(), checkfirst=True)
    internal_plan_status.drop(op.get_bind(), checkfirst=True)
    release_batch_status.drop(op.get_bind(), checkfirst=True)
    release_batch_type.drop(op.get_bind(), checkfirst=True)
