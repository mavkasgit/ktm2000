"""Бэкфилл plan_positions.validation_warnings из применённых change items (#334)

Миграция 079 добавила колонку ``plan_positions.validation_warnings`` без
бэкфилла, поэтому у позиций, созданных до неё, колонка пуста, а предупреждения
остались только в ``plan_change_items.warnings``. Этот проход переносит их на
позицию и делает колонку единственным источником предупреждений: API больше
не подмешивает ``plan_change_items.warnings`` в ответ (тикет #334).

Связь: ``plan_change_items.plan_position_id`` → ``plan_positions.id``. У
элемента сета есть и ``source_ref``/``source_row_number``, но только
``plan_position_id`` — прямая ссылка, и она проставляется при применении сета
(``pending_position_links`` в ``production_plan_service``). Элементы созданных
позиций получают её после flush; ``update_draft_position`` и
``mark_possible_duplicate`` ссылаются на найденную позицию, а у
``ignore_unchanged`` ссылки нет (NULL) — такие элементы в бэкфилл не входят.

Вид действия фильтруется: предупреждения на позицию пишут только
``create_position`` и ``update_draft_position`` (см. ветки применения в
``production_plan_service``). ``mark_possible_duplicate`` и
``cancel_draft_position`` ссылаются на позицию, но её
``validation_warnings`` не трогают — если бы они участвовали в выборе, их
(часто пустой) список гасил бы реальные предупреждения, которых в колонке
ещё нет.

«Последний применённый элемент» — элемент применённого change-set с
максимальным ``plan_change_sets.applied_at``; при равном времени (часы БД
могут совпасть в пределах одного прогона) побеждает больший ``plan_change_items.id``,
то есть элемент более позднего сета. ``applied_at`` — именно момент
применения, а не ``created_at`` элемента: сет можно применить позже или
повторно применить после отката, а откат обнуляет ``applied_at`` и помечает
сет ``cancelled``, поэтому откаченные сеты источником не считаются (история
применений в LIFO-порядке — #172).

Колонка ``applied_at`` появилась в 057 без бэкфилла. Сеты, применённые до
неё, остались ``status = 'applied'`` с ``applied_at IS NULL`` — они тоже
источник, иначе история до 057 выпала бы из бэкфилла. Отбор поэтому
``status = 'applied' OR applied_at IS NOT NULL``: у откаченного сета
``applied_at`` обнулён, а ``status`` — ``cancelled``. В сортировке такие
(до-057) сеты уходят в конец через ``coalesce(applied_at, '-infinity')``:
они старше любого сета с записанным моментом, а между собой упорядочены по
``id``.

Берётся список предупреждений именно последнего применённого элемента, даже
пустого: если более поздний сет очистил предупреждения, старые не
воскрешаются.

Копирование — только в пустую колонку (``[]``) и только непустой список:
позиции, обработанные после 079, уже несут своё значение, и миграция его не
трогает. Это же делает проход идемпотентным: повторный upgrade (stamp назад)
ничего не меняет.

Downgrade — no-op: отличить перенесённые значения от записанных после 079
нечем, а очистка колонки уничтожила бы актуальные предупреждения. Схема
при этом не меняется, так что откат версии безопасен.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "082_plan_position_validation_warnings_backfill"
#: 081 (`drop_stock_dimensions_gin`) — предыдущая в линейной цепочке.
down_revision: str | None = "081_drop_stock_dimensions_gin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: Последний применённый элемент на позицию → его warnings → позиция.
#: ``DISTINCT ON`` + ``ORDER BY`` даёт ровно одну строку на позицию; условие
#: ``jsonb_array_length = 0`` и ``> 0`` — идемпотентность и «не воскрешать
#: очищенные» (см. docstring). Колонка ``applied_at`` существует с миграции
#: 057 без бэкфилла, поэтому до-057 сеты ловятся по ``status = 'applied'``,
#: а сортируются с ``'-infinity'``.
_BACKFILL = """
WITH latest_applied AS (
    SELECT DISTINCT ON (item.plan_position_id)
           item.plan_position_id AS position_id,
           item.warnings AS warnings
    FROM plan_change_items AS item
    JOIN plan_change_sets AS change_set ON change_set.id = item.change_set_id
    WHERE item.plan_position_id IS NOT NULL
      AND (change_set.status = 'applied' OR change_set.applied_at IS NOT NULL)
      AND item.change_action IN ('create_position', 'update_draft_position')
    ORDER BY item.plan_position_id,
             coalesce(change_set.applied_at, '-infinity'::timestamptz) DESC,
             item.id DESC
)
UPDATE plan_positions AS position
SET validation_warnings = latest_applied.warnings
FROM latest_applied
WHERE position.id = latest_applied.position_id
  AND coalesce(jsonb_array_length(position.validation_warnings), 0) = 0
  AND coalesce(jsonb_array_length(latest_applied.warnings), 0) > 0
"""


def upgrade() -> None:
    op.execute(_BACKFILL)


def downgrade() -> None:
    # No-op: данные не восстановить однозначно, а очистка уничтожила бы
    # предупреждения, записанные после 079. Схема миграцией не меняется.
    pass
