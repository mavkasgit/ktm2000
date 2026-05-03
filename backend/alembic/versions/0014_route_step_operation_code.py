"""add route step operation code

Revision ID: 0014_route_step_operation_code
Revises: 0013_rename_sections
Create Date: 2026-05-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_route_step_operation_code"
down_revision: Union[str, None] = "0013_rename_sections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("route_steps", sa.Column("operation_code", sa.String(length=100), nullable=True))
    op.create_index("ix_route_steps_operation_code", "route_steps", ["operation_code"], unique=False)
    for section in [
        {
            "code": "WH",
            "name": "Склад сырья",
            "sort_order": 10,
            "description": "Стартовая точка выдачи сырья и заготовок",
            "kind": "raw_stock",
        },
        {
            "code": "WIP_WH",
            "name": "Склад полуфабриката",
            "sort_order": 60,
            "description": "Промежуточное хранение после анодирования",
            "kind": "wip_stock",
        },
        {
            "code": "FG_WH",
            "name": "Склад готовой продукции",
            "sort_order": 90,
            "description": "Финальная приемка готовой продукции",
            "kind": "finished_stock",
        },
    ]:
        op.execute(
            sa.text(
                """
                INSERT INTO sections (code, name, sort_order, description, kind, is_active, created_at)
                VALUES (:code, :name, :sort_order, :description, :kind, true, NOW())
                ON CONFLICT (code) DO UPDATE SET
                    name = EXCLUDED.name,
                    sort_order = EXCLUDED.sort_order,
                    description = EXCLUDED.description,
                    kind = EXCLUDED.kind,
                    is_active = true;
                """
            ).bindparams(**section)
        )
    for section in [
        {"code": "DRILL", "name": "Сверловка", "sort_order": 20},
        {"code": "PRESS", "name": "Пресс", "sort_order": 30},
        {"code": "SHOT", "name": "Дробеструйная обработка", "sort_order": 40},
        {"code": "ANOD", "name": "Анодирование", "sort_order": 50},
        {"code": "SAW", "name": "Пила", "sort_order": 70},
        {"code": "PACK", "name": "Упаковка", "sort_order": 80},
    ]:
        op.execute(
            sa.text(
                """
                UPDATE sections
                SET name = :name,
                    sort_order = :sort_order,
                    kind = 'production',
                    is_active = true
                WHERE code = :code;
                """
            ).bindparams(**section)
        )


def downgrade() -> None:
    op.drop_index("ix_route_steps_operation_code", table_name="route_steps")
    op.drop_column("route_steps", "operation_code")
