"""Сигнатуры маршрутов пересчитываются по исправленным этапам (#221).

Ревизия 068 восстановила признак значимости этапа по справочнику операций.
Сохранённые сигнатуры после этого считаются по прежним данным: у маршрута,
созданного импортом, в сигнатуре уже стояло «значим» (её писала сборка), а у
маршрута до #214 — «незначим» (её посчитал бэкфилл 066 по этапам, записанным
по старому правилу). Обе строки обязаны стать тем, что даёт вход сборки,
иначе #215 отклонит строку импорта на маршруте, который сегодня исправен.

Порядок ревизий обязателен: 068 → 069. Обратный порядок пересчитал бы
сигнатуры по ещё не исправленным этапам.

Сигнатура выводится из записанных этапов, как её считает
``app.services.route_signature.signature_steps_from_stages`` и как её уже
посчитал бэкфилл 066: формат шага
``stage_kind:section_code:op1,op2:is_significant:transforms_dimensions:is_final``,
шаги разделены ``>``, транзитный этап представляет складской участок.
Маршрут без этапов остаётся с ``NULL``: описывать нечего, и ``NULL`` —
признак «сигнатуры нет», по которому сверка отдаёт вердикт «неизвестно», а не
«расходится».

Отчёт миграции — таблица ``route_signature_migration``: прежняя сигнатура
маршрута, по одному значению на маршрут. Без неё ``downgrade`` не знал бы,
что вернуть, а повторный прогон не отличил бы «пересчитано» от «уже было».

Идемпотентна: пересчёт отбирает только маршруты, у которых пересчитанная
сигнатура отличается от сохранённой, а отчёт защищён ``UNIQUE (route_id)`` —
повторный прогон не меняет ни строки данных, ни строки отчёта.

Irreversible: no — ``downgrade`` возвращает прежние сигнатуры и убирает отчёт.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "069_route_signature_recalculation"
down_revision: str | None = "068_route_stage_significance_from_reference"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REPORT_TABLE = "route_signature_migration"

# Сборка шага сигнатуры — тот же расчёт, что в бэкфилле 066 и в
# ``app.services.route_signature``: код участка складской у транзитного
# этапа, операции по порядку внутри этапа, признаки флагами.
_SEGMENT_SQL = """
           rs.stage_kind || ':' || COALESCE(s.code, '') || ':' || COALESCE((
               SELECT string_agg(COALESCE(ro.operation_code, ''), ',' ORDER BY ro.sequence)
               FROM route_operations ro
               WHERE ro.route_stage_id = rs.id
           ), '') || ':' ||
           CASE WHEN rs.is_significant THEN '1' ELSE '0' END || ':' ||
           CASE WHEN rs.transforms_dimensions THEN '1' ELSE '0' END || ':' ||
           CASE WHEN rs.is_final THEN '1' ELSE '0' END
"""

_STEP_JOINS_SQL = """
    FROM route_stages rs
    LEFT JOIN sections s ON s.id = COALESCE(rs.storage_section_id, rs.section_id)
"""

# Пересчёт всех маршрутов разом: у маршрута без этапов в группировке нет
# строки, поэтому он сохраняет NULL и не попадает под UPDATE.
_RECALCULATE = f"""
WITH step_segments AS (
    SELECT rs.route_id, rs.sequence, {_SEGMENT_SQL} AS segment
    {_STEP_JOINS_SQL}
),
recalculated AS (
    SELECT route_id, string_agg(segment, '>' ORDER BY sequence) AS signature
    FROM step_segments
    GROUP BY route_id
)
UPDATE production_routes pr
SET route_signature = recalculated.signature
FROM recalculated
WHERE pr.id = recalculated.route_id
  AND pr.route_signature IS DISTINCT FROM recalculated.signature
"""


def _report_table_exists(bind) -> bool:
    return REPORT_TABLE in set(sa.inspect(bind).get_table_names())


def _create_report_table() -> None:
    op.create_table(
        REPORT_TABLE,
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("route_id", sa.BigInteger(), nullable=False),
        sa.Column("old_route_signature", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{REPORT_TABLE}")),
        sa.UniqueConstraint("route_id", name=op.f(f"uq_{REPORT_TABLE}_route")),
    )


def _route_signature_expr(route: str) -> str:
    """Выражение сигнатуры маршрута, этапы которого отобраны предикатом ``route``."""
    return (
        "SELECT string_agg(segment, '>' ORDER BY sequence) FROM ("
        f"SELECT rs.sequence, {_SEGMENT_SQL} AS segment"
        f"{_STEP_JOINS_SQL}"
        f"WHERE {route}"
        ") AS steps"
    )


def upgrade() -> None:
    bind = op.get_bind()
    if not _report_table_exists(bind):
        _create_report_table()

    # Список маршрутов, которым сигнатуру менять, — до пересчёта: после
    # UPDATE прежнее значение уже нечего прочитать.
    signature_of_route = _route_signature_expr("rs.route_id = pr.id")
    stale = list(
        bind.execute(
            sa.text(
                "SELECT pr.id AS route_id, pr.route_signature AS old_signature "
                "FROM production_routes pr "
                "WHERE EXISTS (SELECT 1 FROM route_stages WHERE route_id = pr.id) "
                f"  AND pr.route_signature IS DISTINCT FROM ({signature_of_route})"
            )
        ).mappings()
    )
    for row in stale:
        bind.execute(
            sa.text(
                f"INSERT INTO {REPORT_TABLE} (route_id, old_route_signature) "
                "VALUES (:route_id, :old) "
                "ON CONFLICT (route_id) DO NOTHING"
            ),
            {"route_id": row["route_id"], "old": row["old_signature"]},
        )
    op.execute(_RECALCULATE)


def downgrade() -> None:
    bind = op.get_bind()
    if not _report_table_exists(bind):
        return

    signature_of_route = _route_signature_expr("rs.route_id = pr.id")
    for row in bind.execute(
        sa.text(f"SELECT route_id, old_route_signature FROM {REPORT_TABLE} ORDER BY id")
    ).mappings():
        # Сигнатуру могли пересчитать уже после миграции (сборка, API, сид) —
        # тогда откатывать нечего.
        bind.execute(
            sa.text(
                "UPDATE production_routes pr SET route_signature = :old "
                "WHERE pr.id = :route_id "
                f"  AND pr.route_signature IS NOT DISTINCT FROM ({signature_of_route})"
            ),
            {"route_id": row["route_id"], "old": row["old_route_signature"]},
        )

    op.drop_table(REPORT_TABLE)
