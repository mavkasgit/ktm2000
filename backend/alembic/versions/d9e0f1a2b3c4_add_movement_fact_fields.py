"""add movement fact fields: executor_user_id, performed_at, accounted_at

Revision ID: d9e0f1a2b3c4
Revises: c8d3e4f5a6b7
Create Date: 2026-05-10 15:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, None] = "c8d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "movements",
        sa.Column("executor_user_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "movements",
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "movements",
        sa.Column("accounted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_movements_executor_user",
        "movements", "users",
        ["executor_user_id"], ["id"],
    )
    op.create_index(
        "ix_movements_performed_at",
        "movements",
        ["performed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_movements_performed_at", table_name="movements")
    op.drop_constraint("fk_movements_executor_user", "movements", type_="foreignkey")
    op.drop_column("movements", "accounted_at")
    op.drop_column("movements", "performed_at")
    op.drop_column("movements", "executor_user_id")
