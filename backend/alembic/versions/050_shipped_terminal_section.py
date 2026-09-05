"""SHIPPED → терминальная секция (тикет #136).

Отгруженная готовая продукция больше не участвует в оперативных остатках:
секции «Отправлено» (код SHIPPED) выставляется тип ``terminal`` вместо
``finished_stock``. Ledger хранит все проводки как раньше (след полный),
но ``StockProjectionManager`` не материализует ``StockBalance`` для
терминальных секций, а ``is_stock_section`` их не считает оборачиваемым
складом.

Модель ``Section.type`` — простой String(20) без CHECK, поэтому миграция
только data. Существующие строки ``StockBalance`` терминала удаляются:
проекция больше не пересчитывает терминальные локации, legacy-строки
зависли бы навсегда (след восстанавливается из ledger
``rebuild_all_balances`` при откате).

Идемпотентна: UPDATE меняет только строки с кодом SHIPPED и старым типом.

Irreversible: partially — downgrade возвращает ``finished_stock``, но
удалённые строки баланса не восстанавливает (они вычислимы из ledger).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "050_shipped_terminal_section"
down_revision: Union[str, None] = "049_stock_idempotency_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE sections SET type = 'terminal' "
        "WHERE code = 'SHIPPED' AND type <> 'terminal'"
    )
    op.execute(
        "DELETE FROM stock_balances sb "
        "USING sections s "
        "WHERE sb.location_id = s.id AND s.type = 'terminal'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE sections SET type = 'finished_stock' "
        "WHERE code = 'SHIPPED' AND type = 'terminal'"
    )
