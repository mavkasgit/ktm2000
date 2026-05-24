"""add_selected_operation_code_to_work_tasks

Revision ID: 020_task_operation_override
Revises: 019_output_sku
Create Date: 2026-05-24 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "020_task_operation_override"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "work_tasks",
        sa.Column("selected_operation_code", sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("work_tasks", "selected_operation_code")
