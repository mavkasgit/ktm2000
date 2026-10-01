"""Идентичность маршрута импорта — код, а не имя (#230, ADR-0051).

Маршруты, созданные импортом, получают ``production_routes.code`` —
детерминированную функцию их сигнатуры: ``'auto-' || substr(sha256(signature), 1, 16)``.
Формула обязана совпадать с ``app.services.route_signature.auto_route_code``,
иначе прод не узнал бы в своих маршрутах своих же и завёл бы дубль каждому.

Уникальность имени снимается: имя — подпись для человека, а шаблон имени
выбрасывает пустые слоты, поэтому два разных состава законно дают одно
имя (ADR-0045). Пока ``uq_production_routes_name`` стоит, второй маршрут с
тем же именем просто не создаётся, и #230 не имел бы смысла. Уникальность
маршрута обеспечивает ``uq_production_routes_code``.

Отчёт миграции — таблица ``route_code_migration``: прежний код маршрута
(у всех затронутых он ``NULL`` — импорт кода не писал), по одному значению
на маршрут. Без неё ``downgrade`` не знал бы, что вернуть, а повторный
прогон не отличил бы «код проставлен» от «кода не было никогда».

Маршруты без сигнатуры (``NULL`` — нет этапов) кода не получают: выводить
не из чего, и тождество таких маршрутов по-прежнему держится на имени.

Irreversible: partial — ``downgrade`` возвращает прежние коды и возвращает
уникальность имени; уникальность имени может не восстановиться, если после
#230 появились два маршрута с одинаковым именем (тогда ``downgrade``
падает на создании констрейнта — это честный отказ, а не тихая порча).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "071_route_code_identity"
down_revision: str | None = "070_production_plan_archive"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REPORT_TABLE = "route_code_migration"

NAME_UNIQUE_CONSTRAINT = "uq_production_routes_name"

# Тот же расчёт, что в ``app.services.route_signature.auto_route_code``.
# sha256 в PostgreSQL — встроенная функция (pgcrypto не нужен).

# Код получает только ПЕРВЫЙ маршрут каждой сигнатуры (``DISTINCT ON`` по
# ``id``): два маршрута с одинаковым составом и разными именами — это ровно
# тот случай, который #230 и разрешает, но код у них должен быть один, иначе
# ``uq_production_routes_code`` падает. Второй остаётся без кода и
# находится по имени — как и до миграции.
_CODE_EXPR = (
    "'auto-' || substr(encode(sha256(convert_to(route_signature, 'UTF8')), 'hex'), 1, 16)"
)

_BACKFILL = f"""
WITH codable AS (
    SELECT DISTINCT ON (pr.route_signature) pr.id, {_CODE_EXPR} AS code
    FROM production_routes pr
    WHERE pr.code IS NULL AND pr.route_signature IS NOT NULL
    ORDER BY pr.route_signature, pr.id
)
UPDATE production_routes pr
SET code = codable.code
FROM codable
WHERE pr.id = codable.id
  AND NOT EXISTS (
      SELECT 1 FROM production_routes taken WHERE taken.code = codable.code
  )
"""


def _report_table_exists(bind) -> bool:
    return REPORT_TABLE in set(sa.inspect(bind).get_table_names())


def _has_name_unique(bind) -> bool:
    return NAME_UNIQUE_CONSTRAINT in {
        item["name"] for item in sa.inspect(bind).get_unique_constraints("production_routes")
    }


def _create_report_table() -> None:
    op.create_table(
        REPORT_TABLE,
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("route_id", sa.BigInteger(), nullable=False),
        sa.Column("old_code", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{REPORT_TABLE}")),
        sa.UniqueConstraint("route_id", name=op.f(f"uq_{REPORT_TABLE}_route")),
    )


def upgrade() -> None:
    bind = op.get_bind()
    if not _report_table_exists(bind):
        _create_report_table()

    # Список маршрутов, которым код предстоит проставить, — до UPDATE: после
    # него прежнего состояния уже не прочитать. Отбор ДОЛЖЕН совпадать с
    # ``_BACKFILL`` (включая ``DISTINCT ON`` по сигнатуре), иначе отчёт
    # содержал бы строки, которым код не достался, и ``downgrade`` обнулил бы
    # чужой код.
    assigned = list(
        bind.execute(
            sa.text(
                "SELECT id AS route_id FROM ("
                "  SELECT DISTINCT ON (pr.route_signature) pr.id, pr.route_signature "
                "  FROM production_routes pr "
                "  WHERE pr.code IS NULL AND pr.route_signature IS NOT NULL "
                "  ORDER BY pr.route_signature, pr.id"
                ") AS codable ORDER BY id"
            )
        ).mappings()
    )
    for row in assigned:
        bind.execute(
            sa.text(
                f"INSERT INTO {REPORT_TABLE} (route_id, old_code) "
                "VALUES (:route_id, :old) ON CONFLICT (route_id) DO NOTHING"
            ),
            {"route_id": row["route_id"], "old": None},
        )
    op.execute(_BACKFILL)

    # Уникальность имени уходит только после бэкфилла: пока она стоит,
    # UPDATE по коду отработал бы при любом порядке, но отчёт собирать
    # нужно по тому же набору строк, которым код и достаётся.
    if _has_name_unique(bind):
        op.drop_constraint(NAME_UNIQUE_CONSTRAINT, "production_routes", type_="unique")


def downgrade() -> None:
    bind = op.get_bind()
    if not _report_table_exists(bind):
        return

    for row in bind.execute(
        sa.text(f"SELECT route_id, old_code FROM {REPORT_TABLE} ORDER BY id")
    ).mappings():
        # Код могли проставить заново уже после миграции (импорт, API) —
        # тогда откатывать нечего.
        bind.execute(
            sa.text(
                "UPDATE production_routes SET code = :old "
                "WHERE id = :route_id AND code LIKE 'auto-%'"
            ),
            {"route_id": row["route_id"], "old": row["old_code"]},
        )

    op.drop_table(REPORT_TABLE)

    # Уникальность имени возвращается последней: она может не восстановиться,
    # если после #230 появились два маршрута с одинаковым именем. Такой отказ
    # loud и правилен — молча оставить базу без ограничения значило бы
    # превратить откат в невидимую порчу схемы.
    if not _has_name_unique(bind):
        op.create_unique_constraint(NAME_UNIQUE_CONSTRAINT, "production_routes", ["name"])
