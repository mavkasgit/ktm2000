"""normalize default route sections

Revision ID: 0013_rename_sections
Revises: 0012_add_stock_sections
Create Date: 2026-05-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0013_rename_sections"
down_revision: Union[str, None] = "0012_add_stock_sections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE sections SET name = 'Сверловка', kind = 'production', sort_order = 20 WHERE code = 'DRILL';")
    )
    op.execute(
        sa.text("UPDATE sections SET name = 'Пресс', kind = 'production', sort_order = 30 WHERE code = 'PRESS';")
    )
    op.execute(
        sa.text("UPDATE sections SET name = 'Дробеструйная обработка', kind = 'production', sort_order = 40 WHERE code = 'SHOT';")
    )
    op.execute(
        sa.text("UPDATE sections SET name = 'Анодирование', kind = 'production', sort_order = 50 WHERE code = 'ANOD';")
    )
    op.execute(
        sa.text("UPDATE sections SET name = 'Пила', kind = 'production', sort_order = 70 WHERE code = 'SAW';")
    )
    op.execute(
        sa.text("UPDATE sections SET name = 'Упаковка', kind = 'production', sort_order = 80 WHERE code = 'PACK';")
    )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE sections SET name = 'Сверло' WHERE code = 'DRILL';")
    )
    op.execute(
        sa.text("UPDATE sections SET name = 'Дробеструй' WHERE code = 'SHOT';")
    )
