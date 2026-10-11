from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import Date, String, case, cast, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from app.core.sorting import SortClause, apply_sort, parse_sort
from app.domain.dimensions import parse_dimensions_filter
from app.models.daily_plan import DailyPlanItem
from app.models.internal_plan import SectionPlanLine
from app.models.product import Product
from app.models.production_plan import PlanPosition
from app.models.route import RouteOperation, RouteStage, SectionOperation
from app.models.section import Section
from app.models.transfer import Transfer, TransferStatus
from app.models.work_task import (
    CLOSED_WORK_TASK_STATUSES,
    RESOLVED_WORK_TASK_STATUSES,
    WorkTask,
    WorkTaskStatus,
)
from app.stock.models import QualityState, Reason, StockBalance, StockTransaction

from .board_row import BoardRowContext, build_board_task_row
from .common import _to_decimal

# Прямое членство задания в дневном плане — единственный источник признака
# «занято» для режима создания плана (#301). Объявлено одним выражением, а не
# повторяется по запросам: признак не зависит от того, показывается ли задание
# в составе плана.
_IN_DAILY_PLAN_EXPR = (
    select(DailyPlanItem.work_task_id)
    .where(DailyPlanItem.work_task_id == WorkTask.id)
    .exists()
    .label("in_daily_plan")
)


# Единая таблица «поле ?sort= → выражение SQL» для доски. Она же — источник
# истины для валидации: apply_sort отвечает 400 на поле, которого здесь нет,
# поэтому поле нельзя объявить, но не резолвить (или наоборот).
#
# Значение — выражение SQLAlchemy для прямой колонки; callable для полей,
# выражение которых собирается на каждый запрос (JSONB-ключ здесь один).
_BOARD_SORT_COLUMNS: dict[str, object] = {
    "sequence": SectionPlanLine.sequence,
    "task_id": WorkTask.id,
    "product_sku": Product.sku,
    "status": WorkTask.status,
    "due_date": WorkTask.due_date,
    "dimensions": lambda: WorkTask.dimensions["length_mm"].as_float(),
}

# Курируемый набор полей сортировки: контракт для фронта. Валидация идёт по
# _BOARD_SORT_COLUMNS, поэтому набор выводится из таблицы, а не живёт отдельно.
BOARD_SORT_FIELDS = frozenset(_BOARD_SORT_COLUMNS)

# Поля, где значение может быть пустым: срок и длина задания не заполнены.
# Пустые уходят в конец в ЛЮБОМ направлении (в Postgres DESC по умолчанию
# ставит NULL первым — оператор кликнул «спустить», а пустые уехали наверх).
_BOARD_SORT_NULLS_LAST_FIELDS = ("due_date", "dimensions")

# Сортировка по умолчанию — порядок строк маршрута (тот же, что был до
# перехода на общий контракт ``?sort=``).
_BOARD_SORT_DEFAULT = SortClause("sequence", "asc")

DEFAULT_BOARD_LIMIT = 50
MAX_BOARD_LIMIT = 500


def _build_section_board_query(
    *,
    section_id: int,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    status: str | None = None,
    search: str | None = None,
    product_sku: str | None = None,
    dimensions: str | None = None,
):
    """Base board query with SQL-first filters (no pagination/sort)."""
    query = select(
        WorkTask,
        SectionPlanLine,
        RouteStage,
        Product.sku,
        PlanPosition.source_ref,
        PlanPosition.source_payload,
        PlanPosition.source_fingerprint,
        PlanPosition.source_sku,
        PlanPosition.output_sku,
        # Прямое членство в дневном плане (#301): булево без оглядки на то,
        # показывается ли задание в составе плана.
        _IN_DAILY_PLAN_EXPR,
    ).join(
        SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id,
    ).join(
        RouteStage, WorkTask.route_stage_id == RouteStage.id,
    ).join(
        Product, WorkTask.product_id == Product.id,
    ).outerjoin(
        PlanPosition, SectionPlanLine.plan_position_id == PlanPosition.id,
    ).where(
        WorkTask.section_id == section_id,
        (PlanPosition.deleted_at.is_(None)) | (PlanPosition.id.is_(None)),
        WorkTask.planned_quantity > 0,
    )

    if status:
        query = query.where(WorkTask.status == status)
    if date_from:
        query = query.where(WorkTask.created_at >= date_from)
    if date_to:
        query = query.where(WorkTask.created_at <= date_to)
    if product_sku:
        sku_like = f"%{product_sku}%"
        query = query.where(
            or_(
                Product.sku.ilike(sku_like),
                PlanPosition.source_sku.ilike(sku_like),
                PlanPosition.output_sku.ilike(sku_like),
            )
        )
    if dimensions:
        from app.stock.services import dimensions_match_clause

        dims_active, dims = parse_dimensions_filter(dimensions)
        if dims_active:
            query = query.where(dimensions_match_clause(WorkTask.dimensions, dims))
    if search:
        search_like = f"%{search}%"
        route_op_search = exists(
            select(1).where(
                RouteOperation.route_stage_id == RouteStage.id,
                RouteOperation.operation_name.ilike(search_like),
            )
        )
        section_op_search = exists(
            select(1).where(
                SectionOperation.section_id == WorkTask.section_id,
                SectionOperation.operation_code == WorkTask.selected_operation_code,
                SectionOperation.operation_name.ilike(search_like),
            )
        )
        query = query.where(
            or_(
                Product.sku.ilike(search_like),
                PlanPosition.source_sku.ilike(search_like),
                PlanPosition.output_sku.ilike(search_like),
                cast(WorkTask.id, String).ilike(search_like),
                route_op_search,
                section_op_search,
                PlanPosition.source_payload["operation_name"].astext.ilike(search_like),
            )
        )

    return query


def _apply_board_sort(query, clauses: list[SortClause]):
    """ORDER BY доски: приоритеты слева направо, в конце tiebreaker по PK задачи.

    Tiebreaker всегда возрастающий, хотя раньше повторял направление сортировки.
    Для уникального PK это тот же результат: направление последнего ключа
    влияет только на порядок среди строк с равными значениями ВСЕХ ключей, а
    равенства по id не бывает — порядок строк не меняется.
    """
    return apply_sort(
        query,
        clauses,
        _BOARD_SORT_COLUMNS,
        tiebreaker=WorkTask.id,
        nulls_last=_BOARD_SORT_NULLS_LAST_FIELDS,
    )


async def get_section_board(
    db: AsyncSession,
    *,
    section_id: int,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    status: str | None = None,
    search: str | None = None,
    product_sku: str | None = None,
    dimensions: str | None = None,
    sort: str | None = None,
    limit: int = DEFAULT_BOARD_LIMIT,
    offset: int = 0,
) -> dict:
    """Return the section board: tasks + previous stage progress."""
    limit = min(max(limit, 1), MAX_BOARD_LIMIT)
    offset = max(offset, 0)

    query = _build_section_board_query(
        section_id=section_id,
        date_from=date_from,
        date_to=date_to,
        status=status,
        search=search,
        product_sku=product_sku,
        dimensions=dimensions,
    )

    count_stmt = select(func.count()).select_from(
        query.with_only_columns(WorkTask.id).order_by(None).subquery()
    )
    total = (await db.execute(count_stmt)).scalar() or 0

    query = _apply_board_sort(query, parse_sort(sort, default=_BOARD_SORT_DEFAULT))
    query = query.limit(limit).offset(offset)
    rows = (await db.execute(query)).all()

    if not rows:
        return {
            "section_id": section_id,
            "tasks": [],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    # Справочники страницы собираются батчево одним контекстом (#293, fix
    # N+1). Контекст строит тот же код, которым пользуется ручка задания,
    # поэтому форму строки обе ручки берут из одной функции (ADR-0031, #319).
    ctx = await BoardRowContext.load(
        db,
        tasks=[row[0] for row in rows],
        lines=[row[1] for row in rows],
        section_id=section_id,
    )

    # Справочник операций текущего участка для дропдауна доски.
    available_operations = [
        {
            "id": op.id,
            "operation_code": op.operation_code,
            "operation_name": op.operation_name,
            "is_significant": op.is_significant,
            "icon": op.icon,
            "icon_color": op.icon_color,
            "group_code": op.group_code,
        }
        for op in ctx.section_ops
        if op.section_id == section_id
    ]

    # Статусы здесь НЕ синхронизируются: доска — чистое чтение. Свежесть
    # статуса (ADR-0041, «без F5 после чужой передачи») принадлежит
    # write-path: ``StockCommandService.record`` доводит статус до проекции
    # в той же транзакции, что и проводка. Раньше опрос доски сам писал
    # статусы (UPDATE + commit каждые 12 с с каждого терминала) — это и был
    # write-on-read, который сняла эта правка.

    tasks_data = []
    for row in rows:
        tasks_data.append(
            build_board_task_row(
                row[0],
                row[1],
                row[2],
                row_sku=row[3],
                source_ref=row[4],
                source_payload=row[5],
                source_sku=row[7],
                output_sku=row[8],
                in_daily_plan=row[9],
                ctx=ctx,
            )
        )

    return {
        "section_id": section_id,
        "tasks": tasks_data,
        "available_operations": available_operations,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


#: Колонки доски, для которых сервер отдаёт справочник значений (#211).
#: Ключ — `filterField` описания колонки (он же — параметр фильтра доски),
#: значение — SQL-выражение ровно того, что видно в колонке: подпись и выбор
#: в поповере обязаны совпадать, иначе выбранное значение не сузит выборку.
#:
#: «Размер» — габарит задания (`WorkTask.dimensions`), ровно то поле, что
#: сравнивает фильтр доски и по которому идёт её сортировка (#286). Вход
#: трансформирующего этапа (`input_dimensions`) в колонку не протекает: его
#: раскрой «вход → выходы» несёт колонка «Операция» (ADR-0058, ADR-0063).
BOARD_COLUMN_VALUE_FIELDS: frozenset[str] = frozenset({"product_sku", "dimensions"})


def _board_value_expression(column: str):
    if column not in BOARD_COLUMN_VALUE_FIELDS:
        return None
    if column == "product_sku":
        # Артикул строки (см. `effective_display_sku`): у парного профиля
        # видно собранный «A+B», у обычного — артикул продукта.
        return case(
            (PlanPosition.source_sku.like("%+%"), PlanPosition.source_sku),
            else_=Product.sku,
        )
    if column == "dimensions":
        return WorkTask.dimensions
    return None


async def get_section_board_column_values(
    db: AsyncSession,
    *,
    section_id: int,
    column: str,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    status: str | None = None,
    search: str | None = None,
    product_sku: str | None = None,
    dimensions: str | None = None,
    limit: int = DEFAULT_BOARD_LIMIT,
) -> dict:
    """Различные значения серверной колонки доски под текущими фильтрами.

    Фильтр САМОЙ колонки не применяется: список не должен схлопываться к уже
    выбранному значению. Прочие фильтры (окно дат, статус, поиск, соседняя
    колонка) сохраняются — справочник живёт в тех же границах, что и доска.
    """
    value_expr = _board_value_expression(column)
    if value_expr is None:
        raise ValueError(f"колонка {column!r} не отдаёт справочник значений")
    limit = min(max(limit, 1), MAX_BOARD_LIMIT)
    query = _build_section_board_query(
        section_id=section_id,
        date_from=date_from,
        date_to=date_to,
        status=status,
        search=search,
        product_sku=None if column == "product_sku" else product_sku,
        dimensions=None if column == "dimensions" else dimensions,
    )
    stmt = (
        query.with_only_columns(value_expr, maintain_column_froms=True)
        .order_by(None)
        .distinct()
        # «—» (безразмерные) — всегда первой строкой списка: безразмерное
        # значение хранится и как SQL `NULL`, и как JSON `null`, а их
        # натуральный порядок в Postgres разный (SQL NULL — в конец при ASC).
        .order_by(value_expr.nulls_first())
        .limit(limit + 1)
    )
    rows = (await db.execute(stmt)).scalars().all()
    if column == "dimensions":
        # Габарит уезжает в параметр фильтра JSON-строкой — в том же виде, что
        # собирает страничный список поповера: `{"length_mm":2700}`, у
        # безразмерных — `null` (отдельное выбираемое значение, «—»).
        # Безразмерные хранятся и как SQL `NULL`, и как JSON `null`: для
        # `DISTINCT` это разные значения, для оператора — одно «—», поэтому
        # сличаем уже сериализованные строки.
        values = list(
            dict.fromkeys(
                json.dumps(value, separators=(",", ":"), ensure_ascii=False)
                for value in rows
            )
        )[:limit]
    else:
        values = [value for value in rows[:limit] if value is not None]
    return {
        "column": column,
        "values": values,
        "limit": limit,
        "truncated": len(rows) > limit,
    }


async def get_sections_summary(db: AsyncSession) -> dict:
    """Return section counters for quick top-level switching tiles."""
    status_counts = (
        await db.execute(
            select(
                WorkTask.section_id.label("section_id"),
                func.count(WorkTask.id).label("total_tasks"),
                func.sum(
                    case(
                        (
                            WorkTask.status.in_([
                                WorkTaskStatus.ready,
                                WorkTaskStatus.in_progress,
                                WorkTaskStatus.partially_completed,
                            ]),
                            1,
                        ),
                        else_=0,
                    )
                ).label("in_progress_count"),
                func.sum(case((WorkTask.status == WorkTaskStatus.waiting_previous, 1), else_=0)).label("waiting_count"),
            )
            .outerjoin(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .outerjoin(PlanPosition, SectionPlanLine.plan_position_id == PlanPosition.id)
            .where(
                WorkTask.status.notin_(CLOSED_WORK_TASK_STATUSES),
                (PlanPosition.deleted_at.is_(None)) | (PlanPosition.id.is_(None)),
            )
            .group_by(WorkTask.section_id)
        )
    ).all()

    completed_counts = (
        await db.execute(
            select(
                WorkTask.section_id.label("section_id"),
                func.count(WorkTask.id).label("completed_count"),
            )
            .outerjoin(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .outerjoin(PlanPosition, SectionPlanLine.plan_position_id == PlanPosition.id)
            .where(
                WorkTask.status.in_(RESOLVED_WORK_TASK_STATUSES),
                (PlanPosition.deleted_at.is_(None)) | (PlanPosition.id.is_(None)),
            )
            .group_by(WorkTask.section_id)
        )
    ).all()
    completed_by_section: dict[int, int] = {
        row.section_id: int(row.completed_count or 0) for row in completed_counts
    }

    incoming_counts = (
        await db.execute(
            select(
                Transfer.to_section_id.label("section_id"),
                func.count(Transfer.id).label("incoming_transfers_count"),
            )
            .where(Transfer.status.in_([TransferStatus.sent, TransferStatus.partially_accepted]))
            .group_by(Transfer.to_section_id)
        )
    ).all()

    by_section: dict[int, dict] = {}
    for row in status_counts:
        by_section[row.section_id] = {
            "total_tasks": int(row.total_tasks or 0),
            "completed_count": completed_by_section.get(row.section_id, 0),
            "in_progress_count": int(row.in_progress_count or 0),
            "waiting_count": int(row.waiting_count or 0),
            "incoming_transfers_count": 0,
        }

    for row in incoming_counts:
        entry = by_section.setdefault(
            row.section_id,
            {
                "total_tasks": 0,
                "completed_count": 0,
                "in_progress_count": 0,
                "waiting_count": 0,
                "incoming_transfers_count": 0,
            },
        )
        entry["incoming_transfers_count"] = int(row.incoming_transfers_count or 0)

    sections = (
        await db.execute(
            # Только колонки: `users`, `operations` и `spg_links` объявлены
            # `lazy="selectin"` и грузятся на КАЖДОЕ чтение `Section` — три
            # лишних SELECT'а на каждый 12-секундный тик, а сводке они не
            # нужны (#295). `load_only` здесь не помогает: он ограничивает
            # колонки, а `selectin`-связи всё равно загружаются (проверено
            # замером). `raiseload("*")` запрещает связи целиком и, в отличие
            # от молчаливого lean-запроса, громко падает, если кто-то позже
            # потянет `section.users` в этой функции.
            select(Section)
            .options(raiseload("*"))
            .where(Section.is_active == True).order_by(Section.sort_order, Section.id)
        )
    ).scalars().all()

    return {
        "sections": [
            {
                "section_id": section.id,
                "section_code": section.code,
                "section_name": section.name,
                "type": section.type,
                "sort_order": section.sort_order,
                "icon": section.icon,
                "icon_color": section.icon_color,
                "total_tasks": by_section.get(section.id, {}).get("total_tasks", 0),
                "completed_count": by_section.get(section.id, {}).get("completed_count", 0),
                "in_progress_count": by_section.get(section.id, {}).get("in_progress_count", 0),
                "waiting_count": by_section.get(section.id, {}).get("waiting_count", 0),
                "incoming_transfers_count": by_section.get(section.id, {}).get("incoming_transfers_count", 0),
            }
            for section in sections
        ]
    }


async def get_section_daily_stats(
    db: AsyncSession,
    *,
    section_id: int,
    date_from: datetime,
    date_to: datetime,
) -> dict:
    """Return daily statistics for a section, aggregated by created_at date.

    День — UTC, а не TZ сессии БД: окно (``date_from``/``date_to``)
    вызывающий задаёт в UTC (docs/deployment.md — прод-контейнеры живут в
    ``TZ=UTC``), поэтому и группировка обязана читаться в той же шкале.
    """
    # `timezone('UTC', timestamptz)` возвращает UTC-стенные часы (timestamp
    # without time zone), `cast(..., Date)` берёт из них дату. Прямой
    # `CAST(timestamptz AS date)` посчитал бы день в TZ сессии БД и на
    # не-UTC сервере увёл бы метку дня от окна.
    stat_date = cast(func.timezone("UTC", StockTransaction.created_at), Date)

    # Aggregate by date and reason type from StockTransaction
    rows = (
        await db.execute(
            select(
                stat_date.label("stat_date"),
                StockTransaction.reason,
                func.count(StockTransaction.id).label("op_count"),
                func.coalesce(func.sum(StockTransaction.quantity), 0).label("total_qty"),
            )
            .where(
                StockTransaction.to_location_id == section_id,
                StockTransaction.created_at >= date_from,
                StockTransaction.created_at <= date_to,
            )
            .group_by(
                stat_date,
                StockTransaction.reason,
            )
            .order_by(stat_date)
        )
    ).all()

    daily_map: dict[str, dict] = {}
    for stat_date, reason, op_count, total_qty in rows:
        day_key = str(stat_date)
        if day_key not in daily_map:
            daily_map[day_key] = {
                "date": day_key,
                "good_quantity": "0",
                "rejected_quantity": "0",
                "op_count": 0,
                "avg_accounting_delay_seconds": "0",
            }

        reason_val = reason.value if hasattr(reason, "value") else str(reason)
        daily_map[day_key]["op_count"] += op_count

        if reason_val == Reason.COMPLETE.value:
            daily_map[day_key]["good_quantity"] = str(_to_decimal(total_qty))
        elif reason_val == Reason.SCRAP.value:
            daily_map[day_key]["rejected_quantity"] = str(_to_decimal(total_qty))

    return {"section_id": section_id, "daily_stats": list(daily_map.values())}


async def get_warehouse_remainders(
    db: AsyncSession,
    *,
    section_id: int | None = None,
    plan_position_id: int | None = None,
) -> dict:
    """Return available stock balances for a section (legacy API stub).

    Now backed by StockBalance instead of SpgRemainder.

    Одна строка ответа = одна строка ``StockBalance``, то есть полный ключ
    ``(product, location, quality_state, dimensions, completed_operations)``
    (ADR-0055). Артикул может лежать на участке несколькими строками —
    прошёл разные операции, — поэтому признак и габарит отдаются в ответе:
    без них две строки одного артикула неотличимы, и «остаток» в UI
    читался бы как дубль. Суммировать здесь нечего: это перечисление
    физически разных строк, а не «сколько всего на участке».
    """
    from app.stock.services import _format_completed_operations

    query = select(
        StockBalance,
        Product.sku,
        Product.name,
    ).join(
        Product, StockBalance.product_id == Product.id,
    ).where(
        StockBalance.balance_qty > 0,
        StockBalance.quality_state == QualityState.GOOD,
    )

    if section_id is not None:
        query = query.where(StockBalance.location_id == section_id)

    query = query.order_by(StockBalance.refreshed_at.desc())

    rows = (await db.execute(query)).all()

    remainders = []
    for bal, prod_sku, prod_name in rows:
        section = await db.get(Section, bal.location_id)
        remainders.append({
            "id": bal.id,
            "product_id": bal.product_id,
            "product_sku": prod_sku,
            "product_name": prod_name,
            "remainder_quantity": str(bal.balance_qty),
            "section_id": bal.location_id,
            "section_code": section.code if section else "",
            "section_name": section.name if section else "",
            "created_at": bal.refreshed_at.isoformat() if bal.refreshed_at else None,
            # Ось ADR-0055: NULL («состояние не зафиксировано») и []
            # («операций не было») — разные значения, оба доезжают как есть.
            "completed_operations": (
                list(bal.completed_operations)
                if bal.completed_operations is not None
                else None
            ),
            "completed_operations_label": _format_completed_operations(
                bal.completed_operations
            ),
            "dimensions": dict(bal.dimensions) if bal.dimensions else None,
        })

    return {"remainders": remainders}

