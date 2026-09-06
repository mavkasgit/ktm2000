"""product_pairs — пары сырьевых артикулов вместо парных техкарт (ADR-0023, #146).

Пара — связь между двумя сырьевыми артикулами: канонический порядок
``product_a_id < product_b_id`` (CheckConstraint), уникальность неупорядоченной
пары (UniqueConstraint), несколько пар на артикул разрешены. Ручная N —
``quantity_per_hanger`` JSONB ``{length_mm: {"auto": null, "manual": int|null}}``
зеркально одиночным нормам на ``Product.attributes`` (ADR-0012); ``auto`` не
хранится — считается движком живьём. Длины пары = пересечение длин A и B,
фильтруется на чтение — вне пересечения пара не существует.

Флаг ``is_paired_profile`` на products становится выведенным (у артикула есть
пары) и дропается: колонку заменяет column_property (EXISTS по product_pairs) —
все читатели (фильтры, сортировка, search, route_selection) продолжают читать
``Product.is_paired_profile`` как вычисленное поле. «Чистый лист» (ADR-0023
§7): миграции данных из парных техкарт нет — техкарты удаляются тикетом #151.

Идемпотентна (конвенция 052): stamp назад + повторный upgrade — CREATE TABLE
IF NOT EXISTS / DROP COLUMN IF EXISTS; таблица и колонка на втором прогоне
уже в нужном состоянии.

Revises: 053_product_composition
Create Date: 2026-09-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "054_product_pairs"
down_revision: Union[str, None] = "053_product_composition"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Имена констрейнтов — по naming_convention Base (models/base.py), чтобы
# совпадали с метаданными моделей (create_all в тестах).
_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS product_pairs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_a_id BIGINT NOT NULL REFERENCES products (id),
    product_b_id BIGINT NOT NULL REFERENCES products (id),
    quantity_per_hanger JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_product_pairs_canonical_order CHECK (product_a_id < product_b_id),
    CONSTRAINT uq_product_pairs_unordered UNIQUE (product_a_id, product_b_id)
)
"""


def upgrade() -> None:
    op.execute(_CREATE_TABLE)
    op.create_index("ix_product_pairs_product_a_id", "product_pairs", ["product_a_id"], if_not_exists=True)
    op.create_index("ix_product_pairs_product_b_id", "product_pairs", ["product_b_id"], if_not_exists=True)
    # postgresql_if_exists у alembic-ops не пробрасывается в SQL — только raw.
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS is_paired_profile")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_paired_profile "
        "BOOLEAN NOT NULL DEFAULT false"
    )
    op.drop_index("ix_product_pairs_product_b_id", table_name="product_pairs", if_exists=True)
    op.drop_index("ix_product_pairs_product_a_id", table_name="product_pairs", if_exists=True)
    op.execute("DROP TABLE IF EXISTS product_pairs")
