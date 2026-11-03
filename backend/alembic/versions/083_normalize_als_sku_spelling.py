"""Нормализация написания ALS-артикулов: ``ALS1290`` → ``ALS-1290`` (sku и эквиваленты).

Прод переименован вручную (2026-11-02), но написание артикула живёт не только в
``products.sku``: его держат ``products.aliases`` (колонка «Эквиваленты» из
импорта каталога) и демо-сид. Пока в базе остался хоть один слитный вариант,
резолвер поиска ломается: импорт и план ищут позицию по точному совпадению
``(Product.sku == sku) | (Product.aliases.op("@>")(cast([sku], ARRAY(String))))``
(``app/api/routes/catalog_import.py:169``, ``:335``). Строка ``{"335":
["ALS917"]}`` после переименования ``ALS917 → ALS-917`` не указывает ни на что:
эквивалент перестает находиться, а повторный ``db:seed:packing-demo`` на базе,
сидированной до переименования, заводит второй артикул рядом со старым —
``_upsert_product`` сравнивает ``sku`` буквально
(``app/seeds/seeders/packing_plan_demo_seeder.py:1964``).

Поэтому миграция закрывает обе формы, а не только ``sku``:

1. ``products.sku`` — слитная форма приводится к дефисной;
2. ``products.aliases`` — то же с каждым элементом массива.

Регистр не трогается: ``~ '^ALS[0-9]+$'`` (не ``~*``) — в данных и в сиде
префикс всегда заглавный, а тихая перебивка регистра чужих артикулов была бы
правкой того, о чём задача не просила.

Столкновение целевой формы пропускается, а не разруливается. Если в базе уже
есть и ``ALS1290``, и ``ALS-1290`` (следствие повторного сида до этой
миграции), переименование упёрлось бы в уникальный индекс ``sku``, а слияние
двух строк — это решение про данные (какой id, чьи длины, чьи нормативы),
которого у миграции нет. Такие пары остаются как есть и правятся руками;
``downgrade`` симметричен по той же причине.

Исторические таблицы не трогаются: ``audit_logs.product_sku`` и
``hanger_norm_key_migration.sku`` — протоколы прошлых прогонов, их написание
соответствует данным на тот момент (решение заказчика 2026-11-02).
``plan_positions.source_sku``/``output_sku`` и ``stock_import_rows`` — слепок
источника импорта; на момент правки все эти таблицы пусты, а смысл колонок тот
же, что у журнала.

Идемпотентность: после первого прохода ни ``sku``, ни ``aliases`` уже не
удовлетворяют условию (второй проход отсекается предикатом
``p.aliases IS DISTINCT FROM rebuilt.aliases``), поэтому повторный upgrade
ничего не меняет.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "083_normalize_als_sku_spelling"
#: 082 (`plan_position_validation_warnings_backfill`) — предыдущая в линейной цепочке.
down_revision: str | None = "082_plan_position_validation_warnings_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: Слитая форма ALS + цифры. ``varchar`` приведён к ``text``: ``substring``
#: возвращает text, и приведение держит выражение однострочным по обоим
#: столбцам (sku и элементы aliases).
_LEGACY = "^ALS[0-9]+$"

_UPDATE_SKU = f"""
UPDATE products AS p
SET sku = 'ALS-' || substring(p.sku FROM 4)
WHERE p.sku ~ '{_LEGACY}'
  AND NOT EXISTS (
      SELECT 1 FROM products AS q
      WHERE q.id <> p.id AND q.sku = 'ALS-' || substring(p.sku FROM 4)
  )
"""

_UPDATE_ALIASES = f"""
WITH expanded AS (
    SELECT p.id AS product_id,
           t.ord,
           CASE WHEN t.value ~ '{_LEGACY}'
                THEN 'ALS-' || substring(t.value FROM 4)
                ELSE t.value END AS normalized
    FROM products AS p
    CROSS JOIN LATERAL UNNEST(p.aliases) WITH ORDINALITY AS t(value, ord)
),
deduped AS (
    SELECT DISTINCT ON (product_id, normalized) product_id, ord, normalized
    FROM expanded
    ORDER BY product_id, normalized, ord
),
rebuilt AS (
    SELECT product_id, array_agg(normalized ORDER BY ord)::varchar[] AS aliases
    FROM deduped
    GROUP BY product_id
)
UPDATE products AS p
SET aliases = rebuilt.aliases
FROM rebuilt
WHERE p.id = rebuilt.product_id
  AND p.aliases IS DISTINCT FROM rebuilt.aliases
"""

_ROLLBACK_SKU = """
UPDATE products AS p
SET sku = 'ALS' || substring(p.sku FROM 5)
WHERE p.sku ~ '^ALS-[0-9]+$'
  AND NOT EXISTS (
      SELECT 1 FROM products AS q
      WHERE q.id <> p.id AND q.sku = 'ALS' || substring(p.sku FROM 5)
  )
"""

_ROLLBACK_ALIASES = """
WITH expanded AS (
    SELECT p.id AS product_id,
           t.ord,
           CASE WHEN t.value ~ '^ALS-[0-9]+$'
                THEN 'ALS' || substring(t.value FROM 5)
                ELSE t.value END AS normalized
    FROM products AS p
    CROSS JOIN LATERAL UNNEST(p.aliases) WITH ORDINALITY AS t(value, ord)
),
deduped AS (
    SELECT DISTINCT ON (product_id, normalized) product_id, ord, normalized
    FROM expanded
    ORDER BY product_id, normalized, ord
),
rebuilt AS (
    SELECT product_id, array_agg(normalized ORDER BY ord)::varchar[] AS aliases
    FROM deduped
    GROUP BY product_id
)
UPDATE products AS p
SET aliases = rebuilt.aliases
FROM rebuilt
WHERE p.id = rebuilt.product_id
  AND p.aliases IS DISTINCT FROM rebuilt.aliases
"""


def upgrade() -> None:
    op.execute(_UPDATE_SKU)
    op.execute(_UPDATE_ALIASES)


def downgrade() -> None:
    op.execute(_ROLLBACK_ALIASES)
    op.execute(_ROLLBACK_SKU)
