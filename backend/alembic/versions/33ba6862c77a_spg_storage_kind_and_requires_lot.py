"""spg storage_kind and requires_lot

Revision ID: 33ba6862c77a
Revises: 020_merge_heads
Create Date: 2026-06-02 23:25:28.066435
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision: str = '33ba6862c77a'
down_revision: Union[str, None] = '020_merge_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE TYPE spg_storage_kind AS ENUM ('raw', 'wip', 'finished', 'quarantine')")
    op.add_column(
        "storage_production_groups",
        sa.Column(
            "storage_kind",
            sa.Enum("raw", "wip", "finished", "quarantine", name="spg_storage_kind", create_type=False),
            nullable=False,
            server_default="wip",
        ),
    )
    op.add_column(
        "storage_production_groups",
        sa.Column("requires_lot", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_storage_production_groups_storage_kind",
        "storage_production_groups",
        ["storage_kind"],
    )
    op.create_index(
        "ix_warehouse_remainders_product_section_active",
        "warehouse_remainders",
        ["product_id", "section_id"],
        postgresql_where=sa.text("consumed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_warehouse_remainders_product_section_active", table_name="warehouse_remainders")
    op.drop_index("ix_storage_production_groups_storage_kind", table_name="storage_production_groups")
    op.drop_column("storage_production_groups", "requires_lot")
    op.drop_column("storage_production_groups", "storage_kind")
    op.execute("DROP TYPE spg_storage_kind")
