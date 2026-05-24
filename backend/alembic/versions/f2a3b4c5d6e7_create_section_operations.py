"""create section_operations table

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-05-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "section_operations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("sections.id"), nullable=False),
        sa.Column("operation_code", sa.String(100), nullable=False),
        sa.Column("operation_name", sa.String(255), nullable=False),
        sa.Column("is_significant", sa.Boolean(), nullable=False, server_default="false"),
        sa.UniqueConstraint("section_id", "operation_code", name="uq_section_operations"),
    )

    # Заполнить из route_steps (уникальные пары section+operation)
    op.execute(
        """
        INSERT INTO section_operations (section_id, operation_code, operation_name, is_significant)
        SELECT DISTINCT ON (section_id, operation_code)
            section_id, operation_code, operation_name, is_significant
        FROM route_steps
        WHERE operation_code IS NOT NULL
        ORDER BY section_id, operation_code, sequence
        """
    )


def downgrade() -> None:
    op.drop_table("section_operations")
