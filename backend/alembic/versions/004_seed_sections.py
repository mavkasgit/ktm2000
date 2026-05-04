"""seed_sections

Revision ID: 004_seed_sections
Revises: 003_sections_icon
Create Date: 2026-05-04 00:03:00.000000
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '004_seed_sections'
down_revision: Union[str, None] = '003_sections_icon'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO sections (code, name, sort_order, is_active, kind, icon, icon_color)
        VALUES
            ('WH', 'Склад сырья', 10, true, 'raw_stock', 'Warehouse', '#F59E0B'),
            ('DRILL', 'Сверловка', 20, true, 'production', 'Drill', '#3B82F6'),
            ('PRESS', 'Пресс', 30, true, 'production', 'Anvil', '#EF4444'),
            ('SHOT', 'Дробеструй', 40, true, 'production', 'SprayCan', '#6B7280'),
            ('ANOD', 'Анодирование', 50, true, 'production', 'FlaskConical', '#06B6D4'),
            ('WIP_WH', 'Склад полуфабриката', 60, true, 'wip_stock', 'Boxes', '#84CC16'),
            ('SAW', 'Пила', 70, true, 'production', 'Fan', '#F97316'),
            ('PACK', 'Упаковка', 80, true, 'production', 'Package', '#10B981'),
            ('FG_WH', 'Склад готовой продукции', 90, true, 'finished_stock', 'Container', '#065F46')
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name,
            sort_order = EXCLUDED.sort_order,
            kind = EXCLUDED.kind,
            icon = EXCLUDED.icon,
            icon_color = EXCLUDED.icon_color
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM sections
        WHERE code IN ('WH', 'DRILL', 'PRESS', 'SHOT', 'ANOD', 'WIP_WH', 'SAW', 'PACK', 'FG_WH')
        """
    )
