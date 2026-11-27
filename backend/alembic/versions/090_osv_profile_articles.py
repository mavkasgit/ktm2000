"""Два артикула ОСВ: 10×10×10 с длиной 2,0 м и профиль 1212 без длины.

Строки файла заказчика (#461/#471):

* ``14323`` — «П-образный профиль 10*10*10 2,0м алюминий». Это профиль
  группы ``ЮП-2397`` / ``П101010`` / ``389``: 10×10×10 уже есть, но длина
  2000 мм в реестре длин отсутствовала. Добавляем её и привязываем код 1С,
  чтобы строка считалась в штуках (4200 м → 2100 шт).
* ``13923`` — «Профиль алюм.#1212-00 сер.». Артикула в каталоге нет. Заводим
  карточку ``1212`` **без длин**: длина не указана ни в наименовании 1С, ни
  в источнике, и подставлять догадку нельзя. Импорт найдёт артикул по коду,
  но покажет видимую ошибку «Длина не определена: в наименовании её нет,
  у артикула она не задана» — это и есть требуемое поведение (решение
  заказчика 27.11.2026).

Почему не создаём отдельный артикул для 14323: ``П101010`` — уже алиас
группы ``ЮП-2397``; вторая карточка того же сечения развела бы остатки и
нормативы. Длины группы живут на её представителях, поэтому 2000 мм
добавляется канону ``ЮП-2397``.

Миграция идемпотентна: продукты, длины и коды вставляются только при
отсутствии. ``product_1c_skipped`` очищается от обоих кодов: каталог теперь
главнее реестра, а строка «не заводим» больше не соответствует решению.

Откат: коды и длина удаляются; карточка ``1212`` — только если она создана
этой миграцией (маркер в ``notes``) и на неё больше никто не ссылается.
Основной откат прод-данных — восстановление бэкапа «до» (docs/deployment.md).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "090_osv_profile_articles"
down_revision: str | None = "089_als_sku_without_dash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Метка карточки, созданной миграцией: по ней ``downgrade`` отличает свою
#: строку от артикула, который мог существовать до миграции.
_CREATED_NOTE = "Создан из ОСВ 1С: длина не задана"

_ADD_LENGTH_2000 = """
INSERT INTO product_lengths (product_id, length_mm, raw_length_mm, is_primary)
SELECT p.id, 2000, NULL, false
FROM products AS p
WHERE p.sku = 'ЮП-2397'
  AND NOT EXISTS (
      SELECT 1
      FROM product_lengths AS l
      WHERE l.product_id = p.id
        AND l.length_mm = 2000
  )
"""

_CREATE_PROFILE_1212 = f"""
INSERT INTO products (
    sku, name, type, unit, is_active, is_catalog_item, aliases, attributes,
    source, color, notes
)
SELECT
    '1212',
    'Профиль алюминиевый 1212-00 (серебро)',
    'component',
    'шт',
    true,
    true,
    ARRAY[]::varchar[],
    '{{}}'::jsonb,
    '1c_osv',
    'Серебро',
    '{_CREATED_NOTE}'
WHERE NOT EXISTS (SELECT 1 FROM products WHERE sku = '1212')
"""

_LINK_CODE = """
INSERT INTO product_1c_codes (product_id, code, source)
SELECT p.id, CAST(:code AS varchar), '1c_osv'
FROM products AS p
WHERE p.sku = :sku
  AND NOT EXISTS (
      SELECT 1
      FROM product_1c_codes AS c
      WHERE c.code = CAST(:code AS varchar)
  )
"""


def upgrade() -> None:
    bind = op.get_bind()

    bind.execute(sa.text(_ADD_LENGTH_2000))
    bind.execute(sa.text(_CREATE_PROFILE_1212))
    bind.execute(sa.text(_LINK_CODE), {"code": "14323", "sku": "ЮП-2397"})
    bind.execute(sa.text(_LINK_CODE), {"code": "13923", "sku": "1212"})
    bind.execute(
        sa.text(
            "DELETE FROM product_1c_skipped WHERE code IN ('14323', '13923')"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()

    bind.execute(
        sa.text("DELETE FROM product_1c_codes WHERE code IN ('14323', '13923')")
    )
    bind.execute(
        sa.text(
            """
            DELETE FROM product_lengths AS l
            USING products AS p
            WHERE l.product_id = p.id
              AND p.sku = 'ЮП-2397'
              AND l.length_mm = 2000
            """
        )
    )
    bind.execute(
        sa.text(
            """
            DELETE FROM products AS p
            WHERE p.sku = '1212'
              AND p.notes = :note
              AND NOT EXISTS (
                  SELECT 1 FROM product_1c_codes AS c WHERE c.product_id = p.id
              )
            """
        ),
        {"note": _CREATED_NOTE},
    )
