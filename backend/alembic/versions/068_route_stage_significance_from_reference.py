"""Значимость этапа маршрута пересчитывается по справочнику операций (#221).

Запись этапа при импорте брала значимость **первого** шага группы, а сборка
маршрута и сигнатура (#214, ADR-0045) считают «значим, если значим хотя бы
один шаг». Для участка с несколькими группами это разные ответы, и маршрут,
созданный импортом, хранил ``is_significant = 0`` там, где его сигнатура
говорила ``1``. Отказ импорта по несовпадению сигнатур (#215) на таких
данных превратил бы молчаливое расхождение в отказ на исправных маршрутах,
поэтому данные приводятся в соответствие ДО #215.

Правило пересчёта — то же, что у ``app.services.route_signature``
(``signature_steps_from_built_steps``): этап значим, если значима хотя бы одна
его операция. Значимость берётся из справочника операций участка
(``section_operations``) по кодам операций, **реально сохранённым** на этапе
(``route_operations``), а не из прежнего значения этапа — прежнее значение и
есть то, что считалось не тем правилом.

Этап, на котором справочник не может ответить, сохраняет прежнее значение:

- у production-этапа нет ни одной операции с кодом, который есть в
  справочнике участка (код пустой — операция разрешается в рантайме);
- этап не привязан к участку.

Это не ослабление правила, а граница его применимости. Динамические
маршруты завода (``universal_rp`` / ``dynamic_packaging_map_rp``) хранят на
этапах пустые коды операций и различаются **только** значимостью (ADR-0045);
обнулив её «по справочнику», миграция стёрла бы их различие и склеила два
разных маршрута в один. Транзитные этапы складов операций не имеют вовсе и
по определению незначимы — их признак не пересчитывается вовсе.

Отчёт миграции — таблица ``route_stage_significance_migration``: по строке
на изменённый этап со старым и новым признаком. Без неё ``downgrade`` не
знал бы, что откатывать, а повторный прогон отличил бы «уже пересчитано» от
«пересчитано заново».

Идемпотентна: ``UPDATE`` отбирает только этапы, у которых новый признак
отличается от текущего, а отчёт защищён ``UNIQUE (route_stage_id)`` — после
первого прохода ни одна строка не меняется и не добавляется.

Сигнатуры маршрутов этой ревизией НЕ трогаются: они пересчитываются
отдельной следующей ревизией 069, которая обязана идти после.

Irreversible: no — ``downgrade`` возвращает прежние признаки и убирает отчёт.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "068_route_stage_significance_from_reference"
down_revision: str | None = "067_hanger_norm_key_normalization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REPORT_TABLE = "route_stage_significance_migration"

# Этапы, у которых справочник операций участка может ответить: есть участок
# и хотя бы одна сохранённая операция с кодом, зарегистрированным у него.
# Новый признак — «значима хотя бы одна такая операция».
_CANDIDATES = """
SELECT rs.id AS stage_id,
       rs.is_significant AS old_significant,
       EXISTS (
           SELECT 1
           FROM route_operations ro
           JOIN section_operations so
             ON so.section_id = rs.section_id
            AND so.operation_code = ro.operation_code
           WHERE ro.route_stage_id = rs.id
             AND so.is_significant
       ) AS new_significant
FROM route_stages rs
WHERE rs.section_id IS NOT NULL
  AND EXISTS (
      SELECT 1
      FROM route_operations ro
      JOIN section_operations so
        ON so.section_id = rs.section_id
       AND so.operation_code = ro.operation_code
      WHERE ro.route_stage_id = rs.id
  )
"""


def _report_table_exists(bind) -> bool:
    return REPORT_TABLE in set(sa.inspect(bind).get_table_names())


def _create_report_table() -> None:
    op.create_table(
        REPORT_TABLE,
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("route_stage_id", sa.BigInteger(), nullable=False),
        sa.Column("old_is_significant", sa.Boolean(), nullable=False),
        sa.Column("new_is_significant", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{REPORT_TABLE}")),
        sa.UniqueConstraint(
            "route_stage_id", name=op.f(f"uq_{REPORT_TABLE}_route_stage")
        ),
    )


def upgrade() -> None:
    bind = op.get_bind()
    if not _report_table_exists(bind):
        _create_report_table()

    # Отбор — в SQL: в Python приходят уже только те этапы, у которых
    # пересчитанный признак отличается от текущего.
    changed = list(
        bind.execute(
            sa.text(
                "SELECT stage_id, old_significant, new_significant "
                f"FROM ({_CANDIDATES}) AS candidates "
                "WHERE new_significant IS DISTINCT FROM old_significant "
                "ORDER BY stage_id"
            )
        ).mappings()
    )
    for row in changed:
        bind.execute(
            sa.text(
                f"INSERT INTO {REPORT_TABLE} "
                "(route_stage_id, old_is_significant, new_is_significant) "
                "VALUES (:stage_id, :old, :new) "
                "ON CONFLICT (route_stage_id) DO NOTHING"
            ),
            {
                "stage_id": row["stage_id"],
                "old": row["old_significant"],
                "new": row["new_significant"],
            },
        )
        bind.execute(
            sa.text(
                "UPDATE route_stages SET is_significant = :new "
                "WHERE id = :stage_id AND is_significant = :old"
            ),
            {
                "stage_id": row["stage_id"],
                "old": row["old_significant"],
                "new": row["new_significant"],
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not _report_table_exists(bind):
        return

    for row in bind.execute(
        sa.text(
            f"SELECT route_stage_id, old_is_significant, new_is_significant "
            f"FROM {REPORT_TABLE} ORDER BY id"
        )
    ).mappings():
        # Признак могли изменить уже после миграции — тогда откатывать нечего.
        bind.execute(
            sa.text(
                "UPDATE route_stages SET is_significant = :old "
                "WHERE id = :stage_id AND is_significant = :new"
            ),
            {
                "stage_id": row["route_stage_id"],
                "old": row["old_is_significant"],
                "new": row["new_is_significant"],
            },
        )

    op.drop_table(REPORT_TABLE)
