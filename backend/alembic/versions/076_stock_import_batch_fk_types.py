"""Типы FK-колонок `stock_import_batches` под `users.id BIGINT` (#261)

`stock_import_batches.created_by` / `rolled_back_by` / `deleted_by` объявлены в
модели как `mapped_column(ForeignKey("users.id"))` без явного типа — SQLAlchemy
берёт тип у родительской колонки, то есть `BIGINT` (`users.id`). Миграция 072
создала эти колонки как `INTEGER`, поэтому метаданные и схема разошлись, и
`alembic check` предлагал `ALTER` на каждом прогоне (drift-гейт в
`migrations.yml` был красным, вскрыто починкой ADR-0026-пути — тикет #261).

Правка идемпотентна: колонка приводится к `BIGINT` только если она ещё не
`BIGINT` (на базе, где тип уже приведён вручную, миграция — no-op).
Обратная операция сужает тип до `INTEGER`, тоже только если он не `INTEGER`.

FK на `users.id` при смене типа не трогается: `INTEGER` → `BIGINT` совместим с
родительской колонкой и расширяет диапазон, а не сужает.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "076_stock_import_batch_fk_types"
#: 075 (`import_batch_soft_delete`, ADR-0056) — предыдущая в линейной цепочке.
down_revision: str | None = "075_import_batch_soft_delete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "stock_import_batches"
#: Колонки-FK на `users.id` (`BIGINT`): в схеме 072 они оказались `INTEGER`.
_COLUMNS = ("created_by", "rolled_back_by", "deleted_by")


def _column_types() -> dict[str, sa.types.TypeEngine]:
    return {
        column["name"]: column["type"]
        for column in sa.inspect(op.get_bind()).get_columns(_TABLE)
    }


def upgrade() -> None:
    types = _column_types()
    for column in _COLUMNS:
        current = types.get(column)
        if current is None or isinstance(current, sa.BigInteger):
            continue
        op.alter_column(_TABLE, column, type_=sa.BigInteger(), existing_nullable=True)


def downgrade() -> None:
    types = _column_types()
    for column in _COLUMNS:
        current = types.get(column)
        # `BigInteger` — наследник `Integer`, поэтому узость проверяется явно:
        # сужаем только то, что сейчас действительно `BIGINT`.
        if current is None or not isinstance(current, sa.BigInteger):
            continue
        op.alter_column(_TABLE, column, type_=sa.Integer(), existing_nullable=True)
