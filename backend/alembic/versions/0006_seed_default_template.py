"""seed default import template

Revision ID: 0006_seed_default_template
Revises: 0005_import_templates
Create Date: 2026-05-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0006_seed_default_template"
down_revision: Union[str, None] = "0005_import_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO import_templates (name, column_mapping, created_at)
            VALUES (
                'Упаковочная карта КТМ',
                '{"sku": "Артикул", "product_name": "Наименование", "output_quantity": "кол-во штук готовой продукции", "replenishment": "пополнение", "raw_stock_ktm": "остатки сырья на КТМ", "color": "Цвет", "input_quantity": "кол-во шт. в 2,7", "input_length": "Длина, м", "operation": "Пробивка/сверловка", "packaging": "Упаковка", "note": "Примечание", "output_length": "Длина после упак, м", "west_quantity": "Запад", "east_quantity": "Восток", "output_kind": "Вид конечного продукта", "comments": "Комментарии", "packaging_1_8_quantity": "Упаковка в 1,8", "add_quantity": "добавить"}'::jsonb,
                NOW()
            )
            ON CONFLICT DO NOTHING;
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM import_templates WHERE name = 'Упаковочная карта КТМ';
            """
        )
    )
