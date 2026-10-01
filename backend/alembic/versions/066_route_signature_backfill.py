"""Сигнатура маршрута: колонка и backfill (тикет #214, ADR-0045).

Маршрут получает ``production_routes.route_signature`` — упорядоченный
набор шагов с признаками этапа. Тождество маршрута задаёт сигнатура, а не
имя: имя — подпись, шаблон имени выбрасывает пустые слоты, и два разных
маршрута законно дают одно имя.

Существующие маршруты получают сигнатуру ЗДЕСЬ, по уже записанным этапам,
идемпотентно и без пересборки этапов: ``UPDATE`` отбирает маршруты с
``route_signature IS NULL``, а после первого прохода таких не остаётся.
Считать сигнатуру из входа сборки для маршрутов, созданных до #214, нечем —
входа нет; с этого момента маршруты, собираемые из профиля, получают
сигнатуру из входа сборки, а не из записанных этапов.

Формат шага — тот же, что у ``app.services.route_signature``:
``stage_kind:section_code:op1,op2:is_significant:transforms_dimensions:is_final``,
шаги разделены ``>``. Транзитный этап представляет складской участок.

Маршрут без этапов сигнатуры не получает (``NULL``): описывать нечего.

Irreversible: yes — downgrade убирает колонку; сигнатуры выводятся из
этапов и восстанавливаются повторным upgrade или пересчётом при сборке.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "066_route_signature_backfill"
down_revision: str | None = "065_route_stage_transit_normalization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_BACKFILL = """
UPDATE production_routes pr
SET route_signature = agg.signature
FROM (
    SELECT route_id, string_agg(segment, '>' ORDER BY sequence) AS signature
    FROM (
        SELECT rs.route_id,
               rs.sequence,
               rs.stage_kind || ':' || COALESCE(s.code, '') || ':' || COALESCE((
                   SELECT string_agg(COALESCE(ro.operation_code, ''), ',' ORDER BY ro.sequence)
                   FROM route_operations ro
                   WHERE ro.route_stage_id = rs.id
               ), '') || ':' ||
               CASE WHEN rs.is_significant THEN '1' ELSE '0' END || ':' ||
               CASE WHEN rs.transforms_dimensions THEN '1' ELSE '0' END || ':' ||
               CASE WHEN rs.is_final THEN '1' ELSE '0' END AS segment
        FROM route_stages rs
        LEFT JOIN sections s ON s.id = COALESCE(rs.storage_section_id, rs.section_id)
    ) AS segments
    GROUP BY route_id
) AS agg
WHERE pr.id = agg.route_id
  AND pr.route_signature IS NULL
"""


def upgrade() -> None:
    # Конвенция 052: миграция безопасна при повторном прогоне (stamp назад +
    # upgrade head), поэтому DDL — сырой, с IF NOT EXISTS.
    op.execute("ALTER TABLE production_routes ADD COLUMN IF NOT EXISTS route_signature TEXT")
    op.execute(_BACKFILL)


def downgrade() -> None:
    op.execute("ALTER TABLE production_routes DROP COLUMN IF EXISTS route_signature")
