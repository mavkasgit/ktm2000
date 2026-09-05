"""«Склад выпуска» — глобальный дефолт адресата FINAL_RELEASE (тикет #137).

Адресат финального выпуска резолвится каскадом: транзитный хоп маршрута
после финального этапа → глобальный дефолт «склад выпуска» → отказ.
Глобальный дефолт — флаг ``sections.is_output_default``: в сид-каталоге
он стоит у FINISHED_STOCK. «Первая по sort_order» удалена — молчаливый
выбор недопустим; несколько помеченных секций → резолв отказывает
(тест ``test_ambiguous_default_rejected``).

Idempotent backfill: FINISHED_STOCK получает флаг, только если его нет
ни у одной секции — чужая ручная настройка не перетирается.

Downgrade: дроп колонки.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "051_section_output_default"
down_revision: Union[str, None] = "050_shipped_terminal_section"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Идемпотентно: тест test_migration_048 перезапускает "stamp 047 →
    # upgrade head" на живой схеме — повторный прогон обязан проходить.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'sections'
                  AND column_name = 'is_output_default'
            ) THEN
                ALTER TABLE sections
                    ADD COLUMN is_output_default BOOLEAN DEFAULT false NOT NULL;
            END IF;
        END $$;
    """)
    # Backfill: дефолт ещё нигде не проставлен → пометить склад ГП.
    op.execute(
        "UPDATE sections SET is_output_default = true "
        "WHERE code = 'FINISHED_STOCK' "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM sections s2 WHERE s2.is_output_default)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE sections DROP COLUMN IF EXISTS is_output_default")
