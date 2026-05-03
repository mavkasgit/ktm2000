"""add route stock sections

Revision ID: 0012_add_stock_sections
Revises: 0011_add_section_kind
Create Date: 2026-05-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0012_add_stock_sections"
down_revision: Union[str, None] = "0011_add_section_kind"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SECTIONS = [
    {"code": "WH", "name": "Склад сырья", "sort_order": 10, "description": "Стартовая точка выдачи сырья и заготовок", "kind": "raw_stock"},
    {"code": "WIP_WH", "name": "Склад полуфабриката", "sort_order": 60, "description": "Промежуточное хранение после анодирования", "kind": "wip_stock"},
    {"code": "FG_WH", "name": "Склад готовой продукции", "sort_order": 90, "description": "Финальная приемка готовой продукции", "kind": "finished_stock"},
]


def upgrade() -> None:
    for section in SECTIONS:
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


def downgrade() -> None:
    codes = ["WIP_WH", "FG_WH"]
    op.execute(
        sa.text("DELETE FROM sections WHERE code = ANY(:codes)").bindparams(codes=codes)
    )
    op.execute(
        sa.text(
            """
            UPDATE sections
            SET name = 'Склад',
                sort_order = 10,
                description = 'Выдача сырья и приём готовой продукции',
                kind = 'production'
            WHERE code = 'WH';
            """
        )
    )
