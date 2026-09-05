"""Идемпотентность: partial unique на idempotency_key вне ledger (тикет #135).

Та же гонка SELECT-then-INSERT, что закрыл ADR-0022 для ledger, оставалась
в таблицах с ``idempotency_key`` без unique-констрейнта: transfers (007),
defects, defect_decisions, rework_tasks (009), attachments,
entity_comments (010). В READ COMMITTED две конкурентные подачи с одним
ключом обе не видят INSERT друг друга → двойные передачи/дефекты/вложения.
Partial unique-индекс — бэкстоп; проигравший гонку получает 409
(``IdempotencyConflict``, наследует KTMException, а не ValueError —
shopfloor-роуты переводят ValueError в 400) и повторяет операцию с тем же
ключом, попадая в replay-ветку предварительной проверки.

Каждая таблица разобрана отдельно (копипаста решения ADR-0022 недостаточна):
- transfers: side effects — пара ledger-проводок, статус приёмной задачи,
  auto-created task. Проигравшему 409; честный replay оставил бы их
  задвоенными (тот же аргумент, что в ADR-0022 §2). Ledger-бэкстоп на
  ``{key}:stock-send`` защищал и раньше, но косвенно и только при ключе на
  проводке — прямой бэкстоп срабатывает раньше и не зависит от схемы суффиксов.
  Позиционные проверки ключей (``_position_transfer_idempotency_keys`` в
  production_planning) только ЧИТАЮТ уже закоммиченные ключи Transfer для
  guard'ов/отображения — бэкстоп не меняет их семантику: незакоммиченный
  проигравший для них невидим и откатывается целиком.
- defects / defect_decisions / rework_tasks: replay-ветки уже есть
  (``_check_idempotency``); бэкстоп переводит гонку из «тихого дубля» в 409.
- attachments / entity_comments: replay-веток не было вовсе — добавлены в
  сервисах этого же тикета, иначе бэкстоп ломал бы retry клиента. Для
  attachments внешний side effect вызывающего (файл уже записан на диск до
  INSERT метаданных) 409/replay не отменяет — осиротевший файл остаётся
  заботой вызывающего, как и до бэкстопа; дубль-СТРОКИ в БД при этом нет.

Fail-fast: существующие дубликаты уронят создание unique-индекса —
сознательно, по конвенции ADR-0022 §4. Диагностика для оператора:
    SELECT 'transfers' t, idempotency_key, count(*) FROM transfers
      WHERE idempotency_key IS NOT NULL GROUP BY 2 HAVING count(*) > 1
    UNION ALL SELECT 'defects', idempotency_key, count(*) FROM defects
      WHERE idempotency_key IS NOT NULL GROUP BY 2 HAVING count(*) > 1
    UNION ALL SELECT 'defect_decisions', idempotency_key, count(*)
      FROM defect_decisions WHERE idempotency_key IS NOT NULL
      GROUP BY 2 HAVING count(*) > 1
    UNION ALL SELECT 'rework_tasks', idempotency_key, count(*)
      FROM rework_tasks WHERE idempotency_key IS NOT NULL
      GROUP BY 2 HAVING count(*) > 1
    UNION ALL SELECT 'attachments', idempotency_key, count(*)
      FROM attachments WHERE idempotency_key IS NOT NULL
      GROUP BY 2 HAVING count(*) > 1
    UNION ALL SELECT 'entity_comments', idempotency_key, count(*)
      FROM entity_comments WHERE idempotency_key IS NOT NULL
      GROUP BY 2 HAVING count(*) > 1;
Дубликаты некомпенсируемы компенсацией ledger — разбираются вручную
по nature дубликата (например, двойная передача → cancel_transfer).

Revision ID: 052_idempotency_backstops
Revises: 051_section_output_default
Create Date: 2026-09-05 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "052_idempotency_backstops"
down_revision: Union[str, None] = "051_section_output_default"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (таблица, имя индекса). Прошлых индексов на этих колонках не было —
# дропать нечего; partial unique обслуживает и replay-поиск по равенству.
_TABLES = [
    ("transfers", "uq_transfers_idempotency_key"),
    ("defects", "uq_defects_idempotency_key"),
    ("defect_decisions", "uq_defect_decisions_idempotency_key"),
    ("rework_tasks", "uq_rework_tasks_idempotency_key"),
    ("attachments", "uq_attachments_idempotency_key"),
    ("entity_comments", "uq_entity_comments_idempotency_key"),
]


def upgrade() -> None:
    # if_not_exists: конвенция проекта — повторный прогон миграции
    # (stamp назад + upgrade head, см. tests/test_migrations.py) безопасен.
    for table, index_name in _TABLES:
        op.create_index(
            index_name,
            table,
            ["idempotency_key"],
            unique=True,
            postgresql_where=sa.text("idempotency_key IS NOT NULL"),
            if_not_exists=True,
        )


def downgrade() -> None:
    for table, index_name in _TABLES:
        op.drop_index(
            index_name,
            table_name=table,
            postgresql_where=sa.text("idempotency_key IS NOT NULL"),
            if_exists=True,
        )
