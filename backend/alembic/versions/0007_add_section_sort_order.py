"""add section sort_order

Revision ID: 0007_add_section_sort_order
Revises: 0006_seed_default_template
Create Date: 2026-05-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0007_add_section_sort_order"
down_revision: Union[str, None] = "0006_seed_default_template"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add sort_order column with default 0
    op.add_column(
        "sections",
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0")
    )
    # Backfill existing rows: use id as initial sort_order
    op.execute("UPDATE sections SET sort_order = id")
    # Drop server_default to keep it clean
    op.alter_column("sections", "sort_order", server_default=None)


def downgrade() -> None:
    op.drop_column("sections", "sort_order")
