"""Трансформирующий этап маршрута + вход/выходы задания (ADR-0002)

Маркер «трансформирует габариты» на этапе маршрута и в справочнике
операций участка (заводская настройка через сид, не через код).
WorkTask получает вход (количество × габарит) и спецификацию выходов
позиции плана для трансформирующих этапов.

Revision ID: 025_route_stage_transform
Revises: 024_plan_position_dimensions
Create Date: 2026-07-31

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "025_route_stage_transform"
down_revision = "024_plan_position_dimensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "route_stages",
        sa.Column(
            "transforms_dimensions",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "section_operations",
        sa.Column(
            "transforms_dimensions",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "work_tasks",
        sa.Column("input_quantity", sa.Numeric(14, 3), nullable=True),
    )
    op.add_column(
        "work_tasks",
        sa.Column("input_dimensions", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "work_tasks",
        sa.Column(
            "outputs",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("work_tasks", "outputs")
    op.drop_column("work_tasks", "input_dimensions")
    op.drop_column("work_tasks", "input_quantity")
    op.drop_column("section_operations", "transforms_dimensions")
    op.drop_column("route_stages", "transforms_dimensions")
