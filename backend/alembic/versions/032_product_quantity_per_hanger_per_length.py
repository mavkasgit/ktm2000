"""quantity_per_hanger становится словарём по длинам (#60).

Существующий скаляр в attributes['quantity_per_hanger'] мигрируется в
{первая_длина: {"auto": null, "manual": значение}} — первая длина берётся
из product_lengths (по возрастанию). Существующие артикулы остаются
ручными (auto=null), не пересчитываются.

Revision ID: 032_product_quantity_per_hanger_per_length
Revises: 031_users_profile_sync_failed_at
Create Date: 2026-08-08 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "032_product_quantity_per_hanger_per_length"
down_revision: Union[str, None] = "031_users_profile_sync_failed_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Скаляр → {первая_длина: {"auto": null, "manual": значение}}. Только для
    # продуктов, у которых есть хотя бы одна длина: без product_lengths
    # привязать значение не к чему (jsonb_build_object(NULL) недопустим).
    op.execute(
        """
        UPDATE products p
        SET attributes = jsonb_set(
            attributes,
            '{quantity_per_hanger}',
            jsonb_build_object(
                (
                    SELECT min(length_mm)::text
                    FROM product_lengths pl
                    WHERE pl.product_id = p.id
                ),
                jsonb_build_object(
                    'auto', 'null'::jsonb,
                    'manual', attributes->'quantity_per_hanger'
                )
            )
        )
        WHERE jsonb_typeof(attributes->'quantity_per_hanger') = 'number'
          AND EXISTS (
              SELECT 1 FROM product_lengths pl
              WHERE pl.product_id = p.id
          )
        """
    )
    # Артикулы без product_lengths: скаляр остаётся как есть (модель
    # допускает legacy-скаляр; длины неизвестны — привязать некуда).


def downgrade() -> None:
    # {первая_длина: {"auto": ..., "manual": значение}} → скаляр manual.
    # Обратная миграция best-effort: берём manual первой длины. Bare
    # {auto, manual} (legacy-скаляр) и любые нечисловые ключи пропускаем.
    op.execute(
        """
        UPDATE products p
        SET attributes = jsonb_set(
            attributes,
            '{quantity_per_hanger}',
            COALESCE(
                (
                    SELECT value->'manual'
                    FROM jsonb_each(attributes->'quantity_per_hanger') e(key, value)
                    WHERE jsonb_typeof(value) = 'object'
                      AND key ~ '^-?[0-9]+(\\.[0-9]+)?$'
                    ORDER BY key::float
                    LIMIT 1
                ),
                attributes->'quantity_per_hanger'
            )
        )
        WHERE jsonb_typeof(attributes->'quantity_per_hanger') = 'object'
        """
    )
