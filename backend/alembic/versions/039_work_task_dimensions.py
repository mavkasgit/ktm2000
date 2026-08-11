"""WorkTask.dimensions — габарит задания из плана (ADR-0001, тикет #89).

Задание несёт длину передаваемого материала: передача со склада / между
этапами больше не теряет габарит и ищет остаток по своей размерной группе.

Revision ID: 039_work_task_dimensions
Revises: 038_paired_techcard_quantity_min
Create Date: 2026-08-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "039_work_task_dimensions"
down_revision: Union[str, None] = "038_paired_techcard_quantity_min"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "work_tasks",
        sa.Column("dimensions", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("work_tasks", "dimensions")
