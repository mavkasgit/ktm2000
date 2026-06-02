"""audit trail user name snapshots

Revision ID: 31ad3a8c872d
Revises: 33ba6862c77a
Create Date: 2026-06-03 00:08:37.059734
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision: str = '31ad3a8c872d'
down_revision: Union[str, None] = '33ba6862c77a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Movements: add name snapshots
    op.add_column(
        "movements",
        sa.Column("created_by_user_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "movements",
        sa.Column("executor_user_name", sa.String(length=255), nullable=True),
    )
    # WarehouseRemainders: add created_by FK and name snapshot
    op.add_column(
        "warehouse_remainders",
        sa.Column("created_by", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "warehouse_remainders",
        sa.Column("created_by_user_name", sa.String(length=255), nullable=True),
    )
    op.create_foreign_key(
        "fk_warehouse_remainders_created_by_users",
        "warehouse_remainders",
        "users",
        ["created_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_warehouse_remainders_created_by",
        "warehouse_remainders",
        ["created_by"],
    )


def downgrade() -> None:
    op.drop_index("ix_warehouse_remainders_created_by", table_name="warehouse_remainders")
    op.drop_constraint("fk_warehouse_remainders_created_by_users", "warehouse_remainders", type_="foreignkey")
    op.drop_column("warehouse_remainders", "created_by_user_name")
    op.drop_column("warehouse_remainders", "created_by")
    op.drop_column("movements", "executor_user_name")
    op.drop_column("movements", "created_by_user_name")
