"""Дневные планы участка и membership заданий.

Revision ID: 061_daily_plans
Revises: 060_length_model_cutover
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "061_daily_plans"
down_revision: Union[str, None] = "060_length_model_cutover"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "daily_plans" not in tables:
        op.create_table(
            "daily_plans",
            sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
            sa.Column("section_id", sa.BigInteger(), nullable=False),
            sa.Column("plan_date", sa.Date(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("created_by", sa.BigInteger(), nullable=False),
            sa.ForeignKeyConstraint(["section_id"], ["sections.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if "daily_plan_items" not in tables:
        op.create_table(
            "daily_plan_items",
            sa.Column("daily_plan_id", sa.BigInteger(), nullable=False),
            sa.Column("work_task_id", sa.BigInteger(), nullable=False),
            sa.ForeignKeyConstraint(["daily_plan_id"], ["daily_plans.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["work_task_id"], ["work_tasks.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("daily_plan_id", "work_task_id"),
            sa.UniqueConstraint("work_task_id", name="uq_daily_plan_items_work_task"),
        )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("daily_plans")}
    if "ix_daily_plans_section_plan_date" not in indexes:
        op.create_index("ix_daily_plans_section_plan_date", "daily_plans", ["section_id", "plan_date"])
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("daily_plan_items")}
    if "ix_daily_plan_items_daily_plan_id" not in indexes:
        op.create_index("ix_daily_plan_items_daily_plan_id", "daily_plan_items", ["daily_plan_id"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "daily_plan_items" in tables:
        op.drop_table("daily_plan_items")
    if "daily_plans" in tables:
        op.drop_table("daily_plans")
