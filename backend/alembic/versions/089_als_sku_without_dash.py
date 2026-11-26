"""Канон ALS-артикулов без дефиса: ``ALS-1290`` → ``ALS1290`` (#474).

Дефис между буквой и цифрой — оформление, а не часть кода: 1С и упаковочная
карта пишут ``ALS1103``, а миграция 083 привела справочник к обратному
написанию. Решение развёрнуто осознанно: канон хранения — слитная форма,
совместимость с дефисным написанием даёт правило ``sku_loose`` в точках
сравнения, а не второй артикул-алиас.

Миграция правит обе формы, где написание хранится как данные:

1. ``products.sku`` — дефисная форма приводится к слитной;
2. ``products.aliases`` — то же поэлементно: массив разворачивается по
   элементам (запятая внутри ``Ш-15,6_8,8`` — не разделитель), порядок
   сохраняется, дубли после замены схлопываются.

Регистр не трогается: ``~ '^ALS-[0-9]+$'`` (не ``~*``) — в данных префикс
заглавный, тихая перебивка регистра чужих артикулов была бы правкой того, о
чём задача не просила. Дефис между цифрами (``12-34``) — часть номера.

Столкновение целевой формы — падение, а не молчаливый пропуск. Если в базе
есть и ``ALS-1290``, и ``ALS1290``, переименование упёрлось бы в уникальный
индекс ``sku``, а слияние двух строк — решение про данные (какой id, чьи длины,
чьи нормативы), которого у миграции нет. Внятное сообщение оставляет базу в
исходном состоянии (транзакционный DDL) и называет пару для ручного разбора.

Исторические таблицы не трогаются: ``plan_positions.source_sku``/``output_sku``,
``stock_import_rows``, ``audit_logs`` — снимок источника импорта; терпимым к
дефису делается чтение, а не записанная история. ``normalize_sku`` не меняется:
он остаётся байт-точным для ключей словарей и групп.

Идемпотентность: после первого прохода ни ``sku``, ни ``aliases`` уже не
удовлетворяют предикату, поэтому повторный upgrade ничего не меняет.
``downgrade`` симметричен и защищён той же проверкой коллизий.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "089_als_sku_without_dash"
#: 088 (`product_1c_skipped`) — предыдущая в линейной цепочке.
down_revision: str | None = "088_product_1c_skipped"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: Дефисная форма ALS + цифры. ``varchar`` приведён к ``text``: ``substring``
#: возвращает text, и приведение держит выражение однострочным по обоим
#: столбцам (sku и элементы aliases).
_LEGACY = "^ALS-[0-9]+$"

#: Слитная форма ALS + цифры — источник обратного прохода.
_CANON = "^ALS[0-9]+$"

_CHECK_SKU_COLLISIONS = f"""
DO $$
DECLARE
    details text;
BEGIN
    SELECT string_agg(p.sku || ' -> ' || q.sku, ', ')
    INTO details
    FROM products AS p
    JOIN products AS q
      ON q.id <> p.id
     AND q.sku = 'ALS' || substring(p.sku FROM 5)
    WHERE p.sku ~ '{_LEGACY}';

    IF details IS NOT NULL THEN
        RAISE EXCEPTION 'Нельзя переименовать ALS-артикулы: целевая слитная форма уже занята (%)', details;
    END IF;
END $$;
"""

_UPDATE_SKU = f"""
UPDATE products AS p
SET sku = 'ALS' || substring(p.sku FROM 5)
WHERE p.sku ~ '{_LEGACY}'
"""

_UPDATE_ALIASES = f"""
WITH expanded AS (
    SELECT p.id AS product_id,
           t.ord,
           CASE WHEN t.value ~ '{_LEGACY}'
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

_CHECK_ROLLBACK_COLLISIONS = f"""
DO $$
DECLARE
    details text;
BEGIN
    SELECT string_agg(p.sku || ' -> ' || q.sku, ', ')
    INTO details
    FROM products AS p
    JOIN products AS q
      ON q.id <> p.id
     AND q.sku = 'ALS-' || substring(p.sku FROM 4)
    WHERE p.sku ~ '{_CANON}';

    IF details IS NOT NULL THEN
        RAISE EXCEPTION 'Нельзя вернуть дефисное написание ALS-артикулов: целевая форма уже занята (%)', details;
    END IF;
END $$;
"""

_ROLLBACK_SKU = f"""
UPDATE products AS p
SET sku = 'ALS-' || substring(p.sku FROM 4)
WHERE p.sku ~ '{_CANON}'
"""

_ROLLBACK_ALIASES = f"""
WITH expanded AS (
    SELECT p.id AS product_id,
           t.ord,
           CASE WHEN t.value ~ '{_CANON}'
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


def upgrade() -> None:
    op.execute(_CHECK_SKU_COLLISIONS)
    op.execute(_UPDATE_SKU)
    op.execute(_UPDATE_ALIASES)


def downgrade() -> None:
    op.execute(_CHECK_ROLLBACK_COLLISIONS)
    op.execute(_ROLLBACK_ALIASES)
    op.execute(_ROLLBACK_SKU)
