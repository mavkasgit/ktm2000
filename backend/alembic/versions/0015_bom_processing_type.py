"""add bom processing type

Revision ID: 0015_bom_processing_type
Revises: 0014_route_step_operation_code
Create Date: 2026-05-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015_bom_processing_type"
down_revision: Union[str, None] = "0014_route_step_operation_code"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "boms",
        sa.Column(
            "processing_type",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'standart_processing'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("boms", "processing_type")

