"""seed_reference_data

Revision ID: 89fd6a7d5f21
Revises: 231b7895bf40
Create Date: 2026-05-03 14:52:00
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "89fd6a7d5f21"
down_revision: Union[str, None] = "231b7895bf40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO sections (code, name, sort_order, is_active, kind)
        VALUES
            ('WH', 'Склад сырья', 10, true, 'raw_stock'),
            ('DRILL', 'Сверловка', 20, true, 'production'),
            ('PRESS', 'Пресс', 30, true, 'production'),
            ('SHOT', 'Дробеструй', 40, true, 'production'),
            ('ANOD', 'Анодирование', 50, true, 'production'),
            ('WIP_WH', 'Склад полуфабриката', 60, true, 'wip_stock'),
            ('SAW', 'Пила', 70, true, 'production'),
            ('PACK', 'Упаковка', 80, true, 'production'),
            ('FG_WH', 'Склад готовой продукции', 90, true, 'finished_stock')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM sections
        WHERE code IN ('WH', 'DRILL', 'PRESS', 'SHOT', 'ANOD', 'WIP_WH', 'SAW', 'PACK', 'FG_WH')
        """
    )

