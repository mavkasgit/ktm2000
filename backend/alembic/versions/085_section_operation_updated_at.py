"""Время последней правки операции участка: ``section_operations.updated_at``.

Справочник цветов Экранчика — локальная копия операций участка ``ANODIZING``,
и синк решает «чья правка новее» по метке времени (спека 0003, T-378).
Без колонки сравнивать нечего: ``created_at`` у операций нет вовсе, а
переименование или смена hex не оставляют следа.

Колонка ``timestamptz`` (``DateTime(timezone=True)``), not null, default
``now()``. Существующие строки получают метку момента миграции: истории правок
до неё не существует, и выдумывать её нельзя — «новее» для синка впервые
начнёт работать с первой правки после миграции.

``downgrade`` просто снимает колонку: метки правок — производная от данных,
которых на схеме без неё всё равно не сохранить.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "085_section_operation_updated_at"
down_revision: str | None = "084_issue_source_selection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Конвенция 052: повторный прогон (stamp назад + upgrade head) не должен
    # спотыкаться о уже добавленную колонку.
    op.add_column(
        "section_operations",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_column("section_operations", "updated_at", if_exists=True)
