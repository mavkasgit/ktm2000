"""Убрать шаблон остатков «ostaki_ktm» из import_templates (ADR-0003, Обновление).

Дефолтный маппинг остатков переезжает из таблицы шаблонов в JSON-файл
``app/stock/remainders_columns.json`` — он системный дефолт импорта остатков,
а не пользовательский шаблон, и не должен показываться в UI (страница планов,
«Шаблоны импорта»). Строка удаляется; план-шаблон не затрагивается.

Revision ID: 041_drop_ostaki_ktm_template
Revises: 040_transfer_dimensions
Create Date: 2026-08-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "041_drop_ostaki_ktm_template"
down_revision: Union[str, None] = "040_transfer_dimensions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text("DELETE FROM import_templates WHERE code = 'ostaki_ktm'")
    )


def downgrade() -> None:
    pass
