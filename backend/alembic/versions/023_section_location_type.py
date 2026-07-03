"""023_section_location_type

Этап 3.0 рефакторинга Stock Ledger (см. PLAN_stock_ledger.md).

Финализирует Location-домен, начатый миграцией 022:

* ``sections.type`` уже создан и заполнен data-migration kind→type
  (storage-секции) + production-fallback.
* Этап 3.0 в суженном скоупе добавляет:

  - ``server_default='production'::location_type`` — все новые секции
    без явного ``type`` получают ``type='production'`` на уровне БД.
    Это страхует от NOT NULL violation, пока 132 существующих
    тест-фикстуры (``Section(kind='raw_stock', ...)``) не обновлены.
    **Долг**: kind↔type drift для storage-секций, созданных после
    этой миграции без явного ``type``. Закрывается на Этапе 3.1
    (честная ledger-геометрия issue_to_work), где тесты начнут
    указывать ``type`` явно.

  - ``NOT NULL`` constraint на ``sections.type`` — migration guard,
    пойманный в PLAN_stock_ledger.md. Существующие строки уже имеют
    ``type`` (0 NULL после 022), поэтому downgrade безопасен.

Что НЕ делается в суженном 3.0 (отложено, см. PLAN 3.0 advisory):

* Уточнение ``production`` → ``laser/welding/painting/assembly``:
  в dev-БД нет ни одной такой секции, ``SectionOperation.operation_type``
  имеет только ``production/transport``, эвристика по ``name`` даёт
  0 матчей. Возвращаемся, когда появится ``RouteStage``-маппинг
  или ручной UI.

* ``spg_id`` FK на Section: спорно, дублирует m2m ``spg_sections``.
  В dev-БД все 6 production-секций уже привязаны через m2m.

Revision ID: 023_section_location_type
Revises: 022_stock_ledger_core
Create Date: 2026-07-03 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "023_section_location_type"
down_revision: Union[str, None] = "022_stock_ledger_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Защитный default: новые Section(...) без явного type получают
    # type='production' на уровне БД. Существующие строки (12 шт в dev)
    # уже мигрированы в 022, default на них не действует.
    op.execute(
        "ALTER TABLE sections "
        "ALTER COLUMN type SET DEFAULT 'production'::location_type"
    )
    # Migration guard: type обязателен на уровне БД.
    # CheckConstraint через DDL — не Alembic-обёртку, чтобы не зависеть
    # от naming conventions и оставить явный control.
    op.execute(
        "ALTER TABLE sections ALTER COLUMN type SET NOT NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE sections ALTER COLUMN type DROP NOT NULL")
    op.execute("ALTER TABLE sections ALTER COLUMN type DROP DEFAULT")
