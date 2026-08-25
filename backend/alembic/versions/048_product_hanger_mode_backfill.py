"""hanger_mode backfill — явный режим подвеса вместо data-driven приоритета.

Тикет #127: режим «кол-ва на подвес» становится явным полем
``attributes->>'hanger_mode'`` (auto|manual), а не выводом из наличия
данных. Существующие 1D-артикулы без режима получают его по правилу:
заполнены ОБА поля ``perimeter_mm`` И ``mount_width_mm`` → ``auto``,
иначе → ``manual``. Листы (area/volume) не трогаются — у них дефолт
'auto' геттера (#126).

Для артикулов, попавших в ``auto``, авто-значения в per-length dict
досчитываются формулой движка (#62, константы 13/1450/20/2):
``total = min(floor(13 / (perimeter * length / 1e6)), floor(1450 /
(mount_width + 20)) * 2)``; при несовместимых габаритах
(``mount_width + 20 > 1450``) auto остаётся null (ошибку покажет
валидация планирования). Ручные значения не затираются.

Идемпотентна: все шаги защищены отсутствием ключа ``hanger_mode``.

Irreversible: partially — downgrade убирает ключ hanger_mode у 1D
(возврат к data-driven поведению старого кода); досчитанные авто-значения
остаются (старый COALESCE использует их так же, как после PATCH).

Revises: 047_transfer_status_amended
"""
from typing import Sequence, Union

from alembic import op


revision: str = "048_product_hanger_mode_backfill"
down_revision: Union[str, None] = "047_transfer_status_amended"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_AUTO_FIELDS_COND = """
    p.dimension_state = 'length'
    AND NOT (p.attributes ? 'hanger_mode')
    AND p.attributes ? 'perimeter_mm'
    AND p.attributes ? 'mount_width_mm'
    AND (p.attributes->>'perimeter_mm')::float8 > 0
    AND (p.attributes->>'mount_width_mm')::float8 > 0
"""


def upgrade() -> None:
    # 1. Досчитать auto в per-length dict для артикулов, попадающих в
    # авто-режим (без ключа hanger_mode; bare-записи без числового ключа
    # длины сохраняются как есть).
    op.execute(
        f"""
        UPDATE products p
        SET attributes = jsonb_set(
            p.attributes,
            '{{quantity_per_hanger}}',
            (
                SELECT COALESCE(jsonb_object_agg(
                    kv.key,
                    CASE
                        WHEN kv.key !~ '^-?[0-9]+(\\.[0-9]+)?$' THEN kv.value
                        WHEN (p.attributes->>'mount_width_mm')::float8 + 20.0 > 1450.0 THEN
                            jsonb_build_object('auto', NULL, 'manual', kv.value->'manual')
                        ELSE jsonb_build_object(
                            'auto',
                            LEAST(
                                FLOOR(13.0 / ((p.attributes->>'perimeter_mm')::float8 * kv.key::float8 / 1000000.0)),
                                FLOOR(1450.0 / ((p.attributes->>'mount_width_mm')::float8 + 20.0)) * 2
                            )::bigint,
                            'manual', kv.value->'manual'
                        )
                    END
                ), '{{}}'::jsonb)
                FROM jsonb_each(p.attributes->'quantity_per_hanger') AS kv
            )
        )
        WHERE {_AUTO_FIELDS_COND}
            AND jsonb_typeof(p.attributes->'quantity_per_hanger') = 'object'
        """
    )

    # 2. Периметр И габарит заполнены → режим auto.
    op.execute(
        f"""
        UPDATE products p
        SET attributes = p.attributes || jsonb_build_object('hanger_mode', 'auto')
        WHERE {_AUTO_FIELDS_COND}
        """
    )

    # 3. Остальные 1D-артикулы без режима → manual.
    op.execute(
        """
        UPDATE products
        SET attributes = attributes || jsonb_build_object('hanger_mode', 'manual')
        WHERE dimension_state = 'length'
            AND NOT (attributes ? 'hanger_mode')
        """
    )


def downgrade() -> None:
    # Убираем ключ только у 1D (листам режим поставил #126/UI).
    op.execute(
        """
        UPDATE products
        SET attributes = attributes - 'hanger_mode'
        WHERE dimension_state = 'length'
        """
    )
