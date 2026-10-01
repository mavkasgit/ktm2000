"""Мягкое удаление батча импорта плана: `import_batches.deleted_at` (ADR-0056)

`DELETE /production-plans/{p}/batches/{b}` у батча плана был единственным
способом убрать импорт из истории, и он физический: откатывает сеты, сносит
позиции, удаляет строку `import_batches`, а след остаётся только в `AuditLog`.
«Спрятать» батч было нечем — колонок не было, а `_plan_files_query` фильтровал
только `ProductionPlan.deleted_at IS NULL`.

Схема повторяет архивирование плана (миграция 070) и `stock_import_batches`
(ADR-0052 п.5): `deleted_at` + автор + причина. Статус и скрытость ортогональны —
скрытым может быть и применённый, и распознанный, и откаченный батч, а
восстановления из скрытых нет (п.6), поэтому значения заполняются только
самим скрытием.

Бэкфилла нет и быть не может (п.7): физически удалённые батчи невосстановимы —
их нет ни в одной таблице, кроме `AuditLog`. Миграция только добавляет колонки,
все существующие строки остаются видимыми (`deleted_at IS NULL`).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "075_import_batch_soft_delete"
#: 074 (`stock_balance_completed_operations`, ADR-0055) — предыдущая миграция
#: в дереве: цепочка линейна, и 075 обязана висеть на нём, иначе у схемы будет
#: два head. Пока 074 не закоммичена, `upgrade head` из чистого клона падает —
#: это цена общей очереди миграций, а не свойство этой правки.
down_revision: str | None = "074_stock_balance_completed_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("import_batches")
    }
    if "deleted_at" not in columns:
        op.add_column(
            "import_batches",
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "deleted_by" not in columns:
        op.add_column(
            "import_batches",
            sa.Column("deleted_by", sa.BigInteger(), nullable=True),
        )
        op.create_foreign_key(
            "fk_import_batches_deleted_by_users",
            "import_batches",
            "users",
            ["deleted_by"],
            ["id"],
            ondelete="SET NULL",
        )
    if "delete_reason" not in columns:
        op.add_column(
            "import_batches",
            sa.Column("delete_reason", sa.Text(), nullable=True),
        )
    indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("import_batches")
    }
    if "ix_import_batches_deleted_at" not in indexes:
        op.create_index(
            "ix_import_batches_deleted_at",
            "import_batches",
            ["deleted_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("import_batches")
    }
    indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("import_batches")
    }
    if "ix_import_batches_deleted_at" in indexes:
        op.drop_index("ix_import_batches_deleted_at", table_name="import_batches")
    if "delete_reason" in columns:
        op.drop_column("import_batches", "delete_reason")
    if "deleted_by" in columns:
        constraints = {
            item["name"]
            for item in sa.inspect(bind).get_foreign_keys("import_batches")
        }
        if "fk_import_batches_deleted_by_users" in constraints:
            op.drop_constraint(
                "fk_import_batches_deleted_by_users",
                "import_batches",
                type_="foreignkey",
            )
        op.drop_column("import_batches", "deleted_by")
    if "deleted_at" in columns:
        op.drop_column("import_batches", "deleted_at")
