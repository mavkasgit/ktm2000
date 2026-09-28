"""Нормализация складских этапов маршрута в транзит-хопы (тикет #178).

Маршруты, собранные импортом плана, материализовали каждый шаг как
``RouteStage(section_id=<секция шага>)`` — склад и терминал получали
``stage_kind='production'``, то есть выглядели цехом. Сидер маршрутов и
билдер уже делают их транзит-хопами (``section_id IS NULL``,
``storage_section_id=<склад>``), и тот же контракт проверяет BEFORE-триггер
``trg_route_stage_transit_invariants`` (см. ``app/db/triggers.py``).

Миграция приводит существующие строки к тому же виду: этап на складской или
терминальной секции становится транзитным, его склад переезжает в
``storage_section_id``, а ``section_id`` обнуляется — ровно то, что пишет
сид-путь. Операции этапа не трогаются: нормализация касается строк
``route_stages``, а удаление операций было бы необратимой потерей данных
сверх задачи.

``is_final`` не трогается: правило финальности маршрута (#176) не менялось.

Идемпотентна: UPDATE отбирает строки по ``section_id`` складской секции,
который после первого прохода пуст, — повторный прогон не меняет ничего.

Irreversible: no — downgrade возвращает ``section_id`` и ``stage_kind``.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "065_route_stage_transit_normalization"
down_revision: Union[str, None] = "064_plan_position_validation_overridden"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Замороженный снимок app.services.route_storage_classifier.STORAGE_TYPES —
# тот же набор, что проверяет fn_check_route_stage_transit_invariants.
_STORAGE_TYPES = ("raw_stock", "wip_stock", "finished_stock", "scrap", "terminal")
_STORAGE_LIST = ", ".join(f"'{value}'" for value in _STORAGE_TYPES)

_CONVERT_TO_TRANSIT = f"""
UPDATE route_stages rs
SET stage_kind = 'transit',
    section_id = NULL,
    storage_section_id = rs.section_id
FROM sections s
WHERE s.id = rs.section_id
  AND s.type IN ({_STORAGE_LIST})
  AND rs.stage_kind = 'production'
"""



def upgrade() -> None:
    op.execute(_CONVERT_TO_TRANSIT)


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE route_stages rs
        SET stage_kind = 'production',
            section_id = rs.storage_section_id,
            storage_section_id = NULL
        FROM sections s
        WHERE s.id = rs.storage_section_id
          AND s.type IN ({_STORAGE_LIST})
          AND rs.stage_kind = 'transit'
        """
    )
