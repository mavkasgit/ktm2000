"""Синхронизация уникальных индексов code (dimension_types, products).

Модели объявляют ``code`` как ``unique=True, index=True`` — один уникальный
индекс. Миграции 022/033 создавали дублирующую пару: inline-уникальный
констрейнт + не-unique индекс. Убираем избыточный констрейнт и делаем индекс
уникальным (уникальность не ослабляется — индекс выполняет ту же роль).

Revision ID: 042_sync_unique_code_indexes
Revises: 041_drop_ostaki_ktm_template
Create Date: 2026-08-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "042_sync_unique_code_indexes"
down_revision: Union[str, None] = "041_drop_ostaki_ktm_template"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- SCHEMA ---
    op.drop_constraint("uq_dimension_types_code", "dimension_types", type_="unique")
    op.drop_index("ix_dimension_types_code", table_name="dimension_types")
    op.create_index(op.f("ix_dimension_types_code"), "dimension_types", ["code"], unique=True)

    op.drop_constraint("uq_products_code", "products", type_="unique")
    op.create_index(op.f("ix_products_code"), "products", ["code"], unique=True)

    # --- DATA ---
    pass

    # --- TRIGGERS ---
    pass


def downgrade() -> None:
    op.drop_index(op.f("ix_products_code"), table_name="products")
    op.create_unique_constraint("uq_products_code", "products", ["code"])

    op.drop_index(op.f("ix_dimension_types_code"), table_name="dimension_types")
    op.create_index("ix_dimension_types_code", "dimension_types", ["code"], unique=False)
    op.create_unique_constraint("uq_dimension_types_code", "dimension_types", ["code"])
