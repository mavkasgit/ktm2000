"""add position status history table and soft delete columns

Revision ID: 007_position_history_soft_delete
Revises: 006_route_signature_rules
Create Date: 2026-05-12 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "007_position_history_soft_delete"
down_revision: Union[str, None] = "006_route_signature_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create position_status_history table
    op.create_table(
        "position_status_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("plan_position_id", sa.BigInteger(), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=False),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("changed_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["plan_position_id"], ["plan_positions.id"]),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_history_position", "position_status_history", ["plan_position_id"])
    op.create_index(
        "ix_history_position_status_time",
        "position_status_history",
        ["plan_position_id", "to_status", "changed_at"],
    )

    # Add soft delete columns to plan_positions
    op.add_column("plan_positions", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "plan_positions",
        sa.Column("deleted_by", sa.BigInteger(), nullable=True),
    )
    op.add_column("plan_positions", sa.Column("delete_reason", sa.Text(), nullable=True))
    op.create_index(
        "ix_plan_positions_deleted_at",
        "plan_positions",
        ["deleted_at"],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )

    # Add FK for deleted_by
    op.create_foreign_key(
        "fk_plan_positions_deleted_by_users",
        "plan_positions",
        "users",
        ["deleted_by"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_plan_positions_deleted_by_users", "plan_positions", type_="foreignkey")
    op.drop_index("ix_plan_positions_deleted_at", table_name="plan_positions")
    op.drop_column("plan_positions", "delete_reason")
    op.drop_column("plan_positions", "deleted_by")
    op.drop_column("plan_positions", "deleted_at")
    op.drop_index("ix_history_position_status_time", table_name="position_status_history")
    op.drop_index("ix_history_position", table_name="position_status_history")
    op.drop_table("position_status_history")
