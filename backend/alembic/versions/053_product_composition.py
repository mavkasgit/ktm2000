"""Состав ГП на Product: таблица product_compositions (тикет #147).

Нормативная связь «продукт → компонент + количество» (спека #145, ADR-0023 —
замена техкарт). По образцу BoM: component_id + qty + unit, без факта и
остатков. Компонент — только сырьё (products.type='component') и лимит
«не более 2 компонентов на продукт» держит триггер; количество > 0 и
уникальность компонента в составе — констрейнтами.

Наполнение — «чистый лист» (ADR-0023): составы создаются заново вручную,
миграции данных из techcard_lines нет — техкарты удаляются отдельным тикетом.

Повторный прогон безопасен (конвенция 052, проверяется тестом 048:
stamp назад + upgrade head гоняет хвост цепочки): CREATE TABLE IF NOT EXISTS,
CREATE INDEX IF NOT EXISTS, CREATE OR REPLACE FUNCTION + DROP TRIGGER IF EXISTS.

Revision ID: 053_product_composition
Revises: 052_idempotency_backstops
Create Date: 2026-09-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "053_product_composition"
down_revision: Union[str, None] = "052_idempotency_backstops"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Инварианты состава держит один BEFORE-триггер (SQL-констрейнтом не выразить,
# а API-валидация — не защита от прямых записей):
# - компонент — только сырьё products.type='component', не сам продукт;
# - не более 2 компонентов на продукт (BEFORE-триггер считает уже существующие
#   строки владельца, при UPDATE исключая саму строку, и отвергает третью).
# product_id FK каскадит удаление владельца; component FK — NO ACTION:
# сырье, входящее в состав, нельзя удалить, не разобрав состав.
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS product_compositions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id bigint NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    component_product_id bigint NOT NULL REFERENCES products(id),
    quantity numeric(14, 3) NOT NULL,
    unit varchar(50) NOT NULL DEFAULT 'pcs',
    CONSTRAINT ck_product_compositions_quantity_positive CHECK (quantity > 0),
    CONSTRAINT uq_product_compositions_component UNIQUE (product_id, component_product_id)
);
"""

_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS ix_product_compositions_product_id ON product_compositions (product_id);",
    "CREATE INDEX IF NOT EXISTS ix_product_compositions_component_product_id ON product_compositions (component_product_id);",
]

_INVARIANTS_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION fn_check_product_composition_invariants()
RETURNS TRIGGER AS $fn$
DECLARE
    v_type text;
BEGIN
    IF NEW.component_product_id = NEW.product_id THEN
        RAISE EXCEPTION 'product_compositions: product cannot be its own component (product_id=%)', NEW.product_id
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT type INTO v_type FROM products WHERE id = NEW.component_product_id;
    IF v_type IS NULL OR v_type <> 'component' THEN
        RAISE EXCEPTION 'product_compositions: component must be raw material type=component (product_id=% component_id=%)', NEW.product_id, NEW.component_product_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF (
        SELECT count(*)
        FROM product_compositions
        WHERE product_id = NEW.product_id
          AND (TG_OP = 'INSERT' OR id <> NEW.id)
    ) >= 2 THEN
        RAISE EXCEPTION 'product_compositions: at most 2 components per product (product_id=%)', NEW.product_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;
"""

_DROP_INVARIANTS_TRIGGER_SQL = "DROP TRIGGER IF EXISTS trg_product_composition_invariants ON product_compositions;"

_INVARIANTS_TRIGGER_SQL = """
CREATE TRIGGER trg_product_composition_invariants
BEFORE INSERT OR UPDATE OF product_id, component_product_id ON product_compositions
FOR EACH ROW
EXECUTE FUNCTION fn_check_product_composition_invariants();
"""


def upgrade() -> None:
    # --- SCHEMA ---
    op.execute(_CREATE_TABLE_SQL)
    for stmt in _CREATE_INDEXES_SQL:
        op.execute(stmt)

    # --- TRIGGERS ---
    op.execute(_INVARIANTS_FUNCTION_SQL)
    op.execute(_DROP_INVARIANTS_TRIGGER_SQL)
    op.execute(_INVARIANTS_TRIGGER_SQL)


def downgrade() -> None:
    op.execute(_DROP_INVARIANTS_TRIGGER_SQL)
    op.execute("DROP FUNCTION IF EXISTS fn_check_product_composition_invariants();")
    op.execute("DROP TABLE IF EXISTS product_compositions;")

