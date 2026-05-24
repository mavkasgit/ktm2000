"""add is_significant to route_steps

Revision ID: e1f2a3b4c5d6
Revises: d9e0f1a2b3c4
Create Date: 2026-05-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "019_output_sku"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "route_steps",
        sa.Column("is_significant", sa.Boolean(), nullable=False, server_default="false"),
    )
    # Пометить технологические операции как значимые
    op.execute(
        """
        UPDATE route_steps
        SET is_significant = true
        WHERE operation_code IN (
            'DRILL', 'SHOT', 'ANOD', 'PRESS', 'SAW', 'PACK',
            'COAT', 'WELD', 'BEND', 'CUT', 'POLISH'
        )
        """
    )


def downgrade() -> None:
    op.drop_column("route_steps", "is_significant")
