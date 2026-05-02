"""seed factory sections

Revision ID: 0008_seed_factory_sections
Revises: 0007_add_section_sort_order
Create Date: 2026-05-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0008_seed_factory_sections"
down_revision: Union[str, None] = "0007_add_section_sort_order"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SECTIONS = [
    {"code": "WH", "name": "Склад", "sort_order": 10, "description": "Выдача сырья и приём готовой продукции"},
    {"code": "DRILL", "name": "Сверловка", "sort_order": 20, "description": "Сверловка отверстий"},
    {"code": "PRESS", "name": "Пресс", "sort_order": 30, "description": "Прессование профилей"},
    {"code": "SHOT", "name": "Дробеструйная обработка", "sort_order": 40, "description": "Подготовка поверхности перед анодированием"},
    {"code": "ANOD", "name": "Анодирование", "sort_order": 50, "description": "Анодирование алюминиевого профиля"},
    {"code": "SAW", "name": "Пила", "sort_order": 60, "description": "Резка профиля на заданную длину"},
    {"code": "PACK", "name": "Упаковка", "sort_order": 70, "description": "Упаковка готовой продукции"},
]


def upgrade() -> None:
    for section in SECTIONS:
        op.execute(
            sa.text(
                """
                INSERT INTO sections (code, name, sort_order, description, is_active, created_at)
                VALUES (:code, :name, :sort_order, :description, true, NOW())
                ON CONFLICT (code) DO NOTHING;
                """
            ).bindparams(**section)
        )


def downgrade() -> None:
    codes = [s["code"] for s in SECTIONS]
    op.execute(
        sa.text("DELETE FROM sections WHERE code = ANY(:codes)").bindparams(codes=codes)
    )
