"""Архивирование производственного плана без удаления ledger и истории.

Revision ID: 062_production_plan_archive
Revises: 061_daily_plans
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "062_production_plan_archive"
down_revision: Union[str, None] = "061_daily_plans"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("production_plans")
    }
    if "deleted_at" not in columns:
        op.add_column(
            "production_plans",
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "deleted_by" not in columns:
        op.add_column(
            "production_plans",
            sa.Column("deleted_by", sa.BigInteger(), nullable=True),
        )
        op.create_foreign_key(
            "fk_production_plans_deleted_by_users",
            "production_plans",
            "users",
            ["deleted_by"],
            ["id"],
            ondelete="SET NULL",
        )
    if "delete_reason" not in columns:
        op.add_column(
            "production_plans",
            sa.Column("delete_reason", sa.Text(), nullable=True),
        )
    indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("production_plans")
    }
    if "ix_production_plans_deleted_at" not in indexes:
        op.create_index(
            "ix_production_plans_deleted_at",
            "production_plans",
            ["deleted_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("production_plans")
    }
    indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("production_plans")
    }
    if "ix_production_plans_deleted_at" in indexes:
        op.drop_index("ix_production_plans_deleted_at", table_name="production_plans")
    if "delete_reason" in columns:
        op.drop_column("production_plans", "delete_reason")
    if "deleted_by" in columns:
        constraints = {
            item["name"]
            for item in sa.inspect(bind).get_foreign_keys("production_plans")
        }
        if "fk_production_plans_deleted_by_users" in constraints:
            op.drop_constraint(
                "fk_production_plans_deleted_by_users",
                "production_plans",
                type_="foreignkey",
            )
        op.drop_column("production_plans", "deleted_by")
    if "deleted_at" in columns:
        op.drop_column("production_plans", "deleted_at")
