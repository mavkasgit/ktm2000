"""Предупреждения импорта персистятся на позицию: plan_positions.validation_warnings (#328)

Импортный проход кладёт предупреждения строки в ``plan_change_items.warnings``,
но при применении change-set на позицию уходили одни ошибки: предупреждение
оператор видел только на экране импорта, а решение по строке принимается на
странице плана.

Колонка — зеркало соседа ``validation_errors`` (005_planning_and_imports):
``JSONB``, ``NOT NULL``, ``server_default '[]'::jsonb``. Бэкфилла нет: все
существующие позиции получают ``[]`` — источник предупреждений для старых
строк остаётся в ``plan_change_items`` (ADR-0066: два прохода построчных
правил не сводятся, предупреждения берутся с элемента сета, а не
пересчитываются валидацией).

Правило статуса не меняется: ``validation_status`` считается только по
ошибкам — колонка предупреждений на него не влияет.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "079_plan_position_validation_warnings"
#: 078 (`hot_path_indexes`, #291) — предыдущая в линейной цепочке.
down_revision: str | None = "078_hot_path_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "plan_positions",
        sa.Column(
            "validation_warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("plan_positions", "validation_warnings")
