"""Read services for the transfer module.

The bodies of ``get_transfer_details`` and
``get_section_incoming_transfers`` are moved from the historical
``app.services.shopfloor.queries_details`` and
``app.services.shopfloor.queries_sections`` — no behaviour change.

The new ``list_ready_to_transfer`` query surfaces SectionTasks that
have quantity ready to be sent to the next route step, with the
auto-resolved next-section info.  This is the data source for the
dedicated ``/transfers`` UI page.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from typing import cast as tcast

from fastapi import HTTPException
from sqlalchemy import String, Subquery, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, lazyload

from app.core.sorting import SortClause, apply_sort, parse_sort, sort_items
from app.domain.dimensions import format_dimensions, parse_dimensions_filter
from app.models.defect import DefectItem, TransferDiscrepancyDefectItem
from app.models.internal_plan import SectionPlanLine
from app.models.product import Product
from app.models.route import RouteOperation, RouteStage
from app.models.section import Section
from app.models.spg import SpgSection
from app.models.transfer import (
    Transfer,
    TransferDiscrepancy,
    TransferStatus,
)
from app.models.work_task import CLOSED_WORK_TASK_STATUSES, WorkTask, WorkTaskStatus
from app.services.plan_position_hanger import position_dimensions_for_task
from app.services.route_storage_classifier import (
    SECTION_TYPE_PRODUCTION,
    STOCK_TYPES,
    accepts_ordinary_transfer,
    is_stock_section,
)
from app.services.shopfloor.common import _get_transfer, _to_decimal
from app.transfers.budget import (
    sendable_qty_sql,
    transferable_qty_sql,
)
from app.transfers.transferable import (
    BudgetKind,
    TransferableLine,
    completed_qty_sq,
    task_transferable_lines_bulk,
)


def _fmt_qty(value: Decimal | None) -> str:
    """Format a quantity Decimal for JSON: ``Decimal("100.000")`` -> ``"100"``.

    Strips trailing zeros while preserving precision for fractional
    values (``Decimal("0.500")`` -> ``"0.5"``).
    """
    if value is None:
        return "0"
    d = _to_decimal(value)
    if d == d.to_integral_value():
        return str(d.to_integral_value())
    s = format(d, "f")
    # Strip trailing zeros after the decimal point, but keep the dot
    # if there's at least one significant fractional digit.
    if "." in s:
        s = s.rstrip("0").rstrip(".")
        if not s or s == "-":
            s = "0"
    return s


async def get_transfer_details(db: AsyncSession, transfer_id: int) -> dict:
    transfer = await _get_transfer(db, transfer_id)
    discrepancies = (
        await db.execute(
            select(TransferDiscrepancy)
            .where(TransferDiscrepancy.transfer_id == transfer.id)
            .order_by(TransferDiscrepancy.id)
        )
    ).scalars().all()
    # Ссылки на дефекты — одним запросом на все расхождения (#294): раньше
    # на каждое расхождение уходил свой SELECT, и детали передачи с n
    # расхождениями стоили n+1 запросов. Порядок внутри расхождения задаётся
    # явно (раньше он был произвольным, без ORDER BY).
    links_by_discrepancy: dict[int, list] = {}
    if discrepancies:
        rows = (
            await db.execute(
                select(TransferDiscrepancyDefectItem, DefectItem)
                .join(DefectItem, DefectItem.id == TransferDiscrepancyDefectItem.defect_item_id)
                .where(
                    TransferDiscrepancyDefectItem.transfer_discrepancy_id.in_(
                        [d.id for d in discrepancies]
                    )
                )
                .order_by(
                    TransferDiscrepancyDefectItem.transfer_discrepancy_id,
                    TransferDiscrepancyDefectItem.id,
                )
            )
        ).all()
        for link, item in rows:
            links_by_discrepancy.setdefault(link.transfer_discrepancy_id, []).append(
                (link, item)
            )
    result_discrepancies = []
    for d in discrepancies:
        links = links_by_discrepancy.get(d.id, [])
        result_discrepancies.append(
            {
                "id": d.id,
                "discrepancy_quantity": _fmt_qty(d.discrepancy_quantity),
                "resolved_quantity": _fmt_qty(d.resolved_quantity),
                "unresolved_quantity": _fmt_qty(d.unresolved_quantity),
                "status": d.status.value,
                "reason": d.reason,
                "comment": d.comment,
                "links": [
                    {
                        "id": link.id,
                        "defect_item_id": item.id,
                        "defect_id": item.defect_id,
                        "quantity": _fmt_qty(link.quantity),
                    }
                    for link, item in links
                ],
            }
        )
    return {
        "id": transfer.id,
        "transfer_no": transfer.transfer_no,
        "status": transfer.status.value,
        "from_task_id": transfer.from_task_id,
        "to_task_id": transfer.to_task_id,
        "sent_quantity": _fmt_qty(transfer.sent_quantity),
        "accepted_quantity": _fmt_qty(transfer.accepted_quantity) if transfer.accepted_quantity is not None else None,
        "rejected_quantity": _fmt_qty(transfer.rejected_quantity) if transfer.rejected_quantity is not None else None,
        "discrepancies": result_discrepancies,
    }


async def get_section_incoming_transfers(
    db: AsyncSession,
    *,
    section_id: int,
) -> dict:
    """Return incoming open transfers for a section."""
    from_section = aliased(Section)
    to_section = aliased(Section)
    from_task = aliased(WorkTask)
    to_task = aliased(WorkTask)
    from_stage = aliased(RouteStage)
    to_stage = aliased(RouteStage)
    from_line = aliased(SectionPlanLine)

    rows = (
        await db.execute(
            select(
                Transfer,
                from_section,
                to_section,
                from_task,
                to_task,
                from_stage,
                to_stage,
                from_line,
                Product.sku,
            )
            .join(from_section, from_section.id == Transfer.from_section_id)
            .join(to_section, to_section.id == Transfer.to_section_id)
            .join(from_task, from_task.id == Transfer.from_task_id)
            .join(to_task, to_task.id == Transfer.to_task_id)
            .join(from_stage, from_stage.id == from_task.route_stage_id)
            .join(to_stage, to_stage.id == to_task.route_stage_id)
            .join(from_line, from_line.id == from_task.section_plan_line_id)
            .join(Product, Product.id == from_task.product_id)
            .where(
                Transfer.to_section_id == section_id,
                Transfer.status.in_([TransferStatus.sent, TransferStatus.partially_accepted]),
            )
            .order_by(Transfer.sent_at.desc().nullslast(), Transfer.id.desc())
        )
    ).all()

    transfers = []
    for transfer, from_sec, to_sec, src_task, dst_task, src_stage, dst_stage, src_line, product_sku in rows:
        sent = _to_decimal(transfer.sent_quantity or 0)
        accepted = _to_decimal(transfer.accepted_quantity or 0)
        rejected = _to_decimal(transfer.rejected_quantity or 0)
        remaining = sent - accepted - rejected
        if remaining < 0:
            remaining = Decimal(0)

        from_op_name = ", ".join(op.operation_name for op in src_stage.operations) if src_stage and src_stage.operations else ""
        to_op_name = ", ".join(op.operation_name for op in dst_stage.operations) if dst_stage and dst_stage.operations else ""

        transfers.append(
            {
                "transfer_id": transfer.id,
                "transfer_no": transfer.transfer_no,
                "status": transfer.status.value,
                "from_task_id": transfer.from_task_id,
                "to_task_id": transfer.to_task_id,
                "from_section_id": transfer.from_section_id,
                "from_section_code": from_sec.code,
                "from_section_name": from_sec.name,
                "to_section_id": transfer.to_section_id,
                "to_section_code": to_sec.code,
                "to_section_name": to_sec.name,
                "from_operation_name": from_op_name,
                "to_operation_name": to_op_name,
                "sent_quantity": _fmt_qty(sent),
                "accepted_quantity": _fmt_qty(accepted),
                "rejected_quantity": _fmt_qty(rejected),
                "remaining_quantity": _fmt_qty(remaining),
                "comment": transfer.comment,
                "sent_at": transfer.sent_at.isoformat() if transfer.sent_at else None,
                "created_at": transfer.created_at.isoformat() if transfer.created_at else None,
                "is_post_factum": transfer.is_post_factum,
                "physical_handover_at": transfer.physical_handover_at.isoformat() if transfer.physical_handover_at else None,
                "from_task_status": src_task.status.value,
                "to_task_status": dst_task.status.value,
                "product_sku": product_sku,
                "from_line_id": src_line.id,
                "from_line_sequence": src_line.sequence,
                "plan_position_id": src_line.plan_position_id,
                # Габарит переданного (тикет #95): колонка «Размер» в UI.
                "dimensions": transfer.dimensions,
            }
        )

    return {
        "section_id": section_id,
        "incoming_transfers": transfers,
    }


STOCK_SECTION_TYPES = STOCK_TYPES


def _operation_names_subquery():
    return (
        select(
            RouteOperation.route_stage_id,
            func.string_agg(RouteOperation.operation_name, ", ").label("operation_names"),
        )
        .group_by(RouteOperation.route_stage_id)
        .subquery("op_names_sq")
    )


def _ready_dimensions_fields(dims: dict | None) -> dict:
    """Пара полей готовой строки: габарит + его UI-подпись (ADR-0001)."""
    return {
        "dimensions": dims,
        "dimensions_label": format_dimensions(dims),
    }


def _ready_row_common(row) -> dict:
    """Общие поля ready-строки (без количеств и габарита) — основа для
    обычной строки и строк выходов трансформирующей задачи (тикет #91)."""
    (
        task,
        line,
        stage,
        section,
        product_sku,
        next_l,
        next_stg,
        next_sec,
        _completed,
        _transferred,
        _released,
        _transferable_qty,
        _sendable_qty,
    ) = row
    # Текущий этап финальный (тикет #96): строка получает «Отправить»
    # (final release) вместо «Передать»; следующего шага у неё нет.
    is_final = bool(stage.is_final)
    has_next = (
        next_l is not None
        and next_stg is not None
        and not is_final
    )

    op_code = stage.operations[0].operation_code if stage and stage.operations else None
    op_name = ", ".join(op.operation_name for op in stage.operations) if stage and stage.operations else ""
    next_op_name = ", ".join(op.operation_name for op in next_stg.operations) if next_stg and next_stg.operations else None

    return {
        "task_id": task.id,
        "section_id": task.section_id,
        "section_code": section.code,
        "section_name": section.name,
        "plan_position_id": line.plan_position_id,
        "route_stage_id": stage.id,
        "sequence": stage.sequence,
        "operation_code": op_code,
        "operation_name": op_name,
        "product_id": task.product_id,
        "product_sku": product_sku,
        "has_next_step": has_next,
        "next_section_id": next_sec.id if next_sec is not None else None,
        "next_section_code": next_sec.code if next_sec is not None else None,
        "next_section_name": next_sec.name if next_sec is not None else None,
        "next_operation_name": next_op_name,
        "next_step_sequence": next_stg.sequence if next_stg is not None else None,
        "next_step_is_final": bool(next_stg.is_final) if next_stg is not None else None,
        "is_final": is_final,
    }


def _hydrate_production_ready_row(
    row,
    *,
    lines_by_task: dict[int, list[TransferableLine]],
) -> list[dict]:
    """Ready-строки одной production-задачи.

    Бюджет собирает глубокий модуль ``transferable`` (#131): трёхветочный
    dispatch (обычная задача / трансформация / склад) и выбор формулы по
    финальности участка живут там; гидратор только разворачивает строки
    бюджета в JSON готовой страницы. Строки приходят готовыми из
    bulk-словаря ``task_transferable_lines_bulk`` (follow-up #131: один
    bulk-проход на всю страницу вместо запроса на задачу).

    Обычная задача — одна строка ``dimensions = task.dimensions``.
    Трансформирующая (резка, тикет #91) — строка на каждый выход
    спецификации. Строки с бюджетом <= 0 (и выходы с планом <= 0)
    отбрасываются.

    Финальный этап (тикет #96): «уже отданное» по размеру — net
    FINAL_RELEASE (released), а не TRANSFER_SEND; смысл бюджета — отправка
    (``remaining_send``, тикет #119) — выбран внутри модуля ``transferable``.
    """
    task = row[0]
    common = _ready_row_common(row)
    lines = lines_by_task.get(task.id, [])

    items: list[dict] = []
    for line in lines:
        # Выход трансформации с неположительным планом не показываем;
        # обычная задача видна, пока положителен её бюджет.
        if line.kind is BudgetKind.TRANSFORM and line.planned <= 0:
            continue
        if line.budget <= 0:
            continue
        items.append({
            **common,
            "planned_quantity": _fmt_qty(line.planned),
            "completed_quantity": _fmt_qty(line.produced),
            "already_transferred_quantity": _fmt_qty(line.used),
            "transferable_quantity": _fmt_qty(line.budget),
            **_ready_dimensions_fields(line.dims),
        })
    return items


# ─── Сортировка ready-страницы (единый контракт ?sort=field:order,...) ───────
# Две таблицы резолва одного и того же набора полей:
#   * _READY_SORT_KEYS — значения уже готовых строк (Python, ФИНАЛЬНЫЙ порядок,
#     общий для производственных и складских строк);
#   * _ready_production_sort_columns() — выражения SQL для производственных
#     заданий (порядок строк-заданий ДО гидрации).
# Расхождение таблиц означало бы, что одни и те же задания приходят в разном
# порядке в зависимости от ветки; его ловит тест test_ready_sort_tables_agree.
def _ready_dimensions_length(item: dict) -> float | None:
    """Длина из габарита готовой строки; None — безразмерная."""
    dims = item.get("dimensions")
    if not isinstance(dims, dict):
        return None
    raw = dims.get("length_mm")
    if raw is None:
        return None
    try:
        return float(_to_decimal(raw))
    except InvalidOperation:
        return None


def _ready_transferable_qty(item: dict) -> Decimal:
    try:
        return _to_decimal(item.get("transferable_quantity") or "0")
    except InvalidOperation:
        return Decimal(0)


_READY_SORT_KEYS: dict[str, Callable[[dict], Any]] = {
    "sequence": lambda item: item.get("sequence") or 0,
    "task_id": lambda item: item.get("task_id") or 0,
    "plan_position_id": lambda item: item.get("plan_position_id") or 0,
    "product_sku": lambda item: item.get("product_sku") or "",
    # «Этап» — это номер этапа маршрута, текст операции лишь дополняет его.
    "operation_name": lambda item: (
        (item.get("sequence") or 0, item.get("operation_name") or "")
    ),
    "transferable_qty": _ready_transferable_qty,
    "next_section_name": lambda item: item.get("next_section_name") or "",
    "dimensions": _ready_dimensions_length,
}

READY_SORT_FIELDS = frozenset(_READY_SORT_KEYS)

# Безразмерные строки уходят в конец в ЛЮБОМ направлении (как в SQL-пути).
_READY_SORT_NULLS_LAST_FIELDS = ("dimensions",)

# Без параметра сортировки порядок прежний: этап по возрастанию.
_READY_SORT_DEFAULT = SortClause("sequence", "asc")


def _ready_item_tiebreaker(item: dict) -> tuple:
    """Последний уровень порядка ready-строк.

    Строки одного задания (в том числе выходы трансформирующей задачи) не
    должны «мигать» между страницами: их раскладывает габарит, а затем план.
    """
    length = _ready_dimensions_length(item)
    return (
        item.get("task_id") or 0,
        0 if length is None else 1,
        0.0 if length is None else length,
        _ready_transferable_qty(item),
    )


def _next_operation_names_subquery():
    next_stage_ops = aliased(RouteOperation, name="next_stage_op")
    return (
        select(
            next_stage_ops.route_stage_id,
            func.string_agg(next_stage_ops.operation_name, ", ").label("next_operation_names"),
        )
        .group_by(next_stage_ops.route_stage_id)
        .subquery("next_op_names_sq")
    )


def _ready_production_sort_columns(
    *,
    transferable_expr,
    from_line,
    from_stage,
    next_section,
) -> dict[str, object]:
    """«поле ?sort= → выражение SQL» для производственных заданий.

    Алиасы запроса приходят аргументами, поэтому таблица собирается на
    каждый вызов. Набор полей обязан совпадать с ``_READY_SORT_KEYS``: иначе
    задание и складская строка окажутся в разном порядке (ловит тест
    test_ready_sort_tables_agree).
    """
    return {
        "sequence": from_line.sequence,
        "task_id": WorkTask.id,
        "plan_position_id": from_line.plan_position_id,
        "product_sku": Product.sku,
        "operation_name": from_stage.sequence,
        "transferable_qty": transferable_expr,
        "next_section_name": next_section.name,
        "dimensions": lambda: WorkTask.dimensions["length_mm"].as_float(),
    }


def _apply_ready_production_order(
    query,
    *,
    clauses,
    transferable_expr,
    from_line,
    from_stage,
    next_section,
):
    """ORDER BY производственных заданий: приоритеты ``?sort=`` + tiebreaker.

    Этот порядок действует ДО гидрации строк; финальный порядок страницы
    (включая складские строки) задаёт общий Python-проход ``sort_items``.
    """
    return apply_sort(
        query,
        clauses,
        _ready_production_sort_columns(
            transferable_expr=transferable_expr,
            from_line=from_line,
            from_stage=from_stage,
            next_section=next_section,
        ),
        tiebreaker=WorkTask.id,
        nulls_last=_READY_SORT_NULLS_LAST_FIELDS,
    )


def _build_production_ready_query(
    *,
    section_ids: list[int] | None = None,
    section_id: int | None = None,
    search: str | None = None,
    product_sku: str | None = None,
    operation_name: str | None = None,
    next_operation_name: str | None = None,
    next_section_name: str | None = None,
    task_id: int | None = None,
    plan_position_id: int | None = None,
    transferable_qty: Decimal | None = None,
    dimensions: str | None = None,
    sort_clauses: Sequence[SortClause] = (),
):
    from_section = aliased(Section, name="from_section")
    next_section = aliased(Section, name="next_section")
    from_stage = aliased(RouteStage, name="from_stage")
    next_stage = aliased(RouteStage, name="next_stage")
    from_line = aliased(SectionPlanLine, name="from_line")
    next_line = aliased(SectionPlanLine, name="next_line")

    from app.stock.ledger import net_by_reason_sq
    from app.stock.models import Reason
    # «Произведено/завершено» — публичная SQL-форма модуля transferable (#131).
    completed_sq = completed_qty_sq()
    transferred_sq = tcast(
        Subquery, net_by_reason_sq(Reason.TRANSFER_SEND, "transferred_qty_sq")
    )
    released_sq = tcast(Subquery, net_by_reason_sq(Reason.FINAL_RELEASE, "released_qty_sq"))
    # Единственный владелец формулы — transfers/budget (#119): ready-запрос
    # отдаёт ДВА именованных столбца (передача / отправка); семантику по
    # финальности участка выбирает потребитель, фабрика CASE не строит.
    # (#131) Выражения ниже — грубый set-based ПРЕДФИЛЬТР по задачным
    # агрегатам: выходы трансформации живут в JSON и в SQL не
    # разворачиваются. Точные бюджеты готовых строк считает модуль
    # app.transfers.transferable при гидрации — формулы тут не копируются.
    completed_col = func.coalesce(completed_sq.c.completed_qty, 0)
    transferable_expr = transferable_qty_sql(
        completed_col,
        func.coalesce(transferred_sq.c.net_quantity, 0),
    ).label("transferable_qty")
    sendable_expr = sendable_qty_sql(
        completed_col,
        func.coalesce(released_sq.c.net_quantity, 0),
    ).label("sendable_qty")
    stage_qty_expr = case(
        (from_stage.is_final.is_(True), sendable_expr), else_=transferable_expr
    )


    query = (
        select(
            WorkTask,
            from_line,
            from_stage,
            from_section,
            Product.sku,
            next_line,
            next_stage,
            next_section,
            func.coalesce(completed_sq.c.completed_qty, 0).label("completed_qty"),
            func.coalesce(transferred_sq.c.net_quantity, 0).label("transferred_qty"),
            func.coalesce(released_sq.c.net_quantity, 0).label("released_qty"),
            transferable_expr,
            sendable_expr,
        )
        .join(from_line, from_line.id == WorkTask.section_plan_line_id)
        .join(from_stage, from_stage.id == WorkTask.route_stage_id)
        .join(from_section, from_section.id == WorkTask.section_id)
        .join(Product, Product.id == WorkTask.product_id)
        .outerjoin(completed_sq, completed_sq.c.task_id == WorkTask.id)
        .outerjoin(transferred_sq, transferred_sq.c.task_id == WorkTask.id)
        .outerjoin(released_sq, released_sq.c.task_id == WorkTask.id)
        .outerjoin(
            next_line,
            (next_line.plan_position_id == from_line.plan_position_id)
            & (next_line.sequence == from_line.sequence + 1),
        )
        .outerjoin(next_stage, next_stage.id == next_line.route_stage_id)
        .outerjoin(next_section, next_section.id == next_line.section_id)
        .options(
            # ready-строке нужны только code/name/type секций: списки
            # пользователей, операций и СПГ грузились selectin'ом на КАЖДЫЙ
            # алиас секции впустую — шесть запросов на каждый проход (#290).
            lazyload(from_section.users),
            lazyload(from_section.operations),
            lazyload(from_section.spg_links),
            lazyload(next_section.users),
            lazyload(next_section.operations),
            lazyload(next_section.spg_links),
        )
        .where(
            WorkTask.status.notin_(
                [WorkTaskStatus.cancelled, WorkTaskStatus.waiting_previous]
            ),
            from_section.type == SECTION_TYPE_PRODUCTION,
            # Финальный этап (тикет #96) попадает в ready-список без
            # следующего шага: для него «отправить» = final release.
            or_(
                from_stage.is_final.is_(True),
                and_(
                    from_stage.is_final.is_(False),
                    next_line.id.isnot(None),
                ),
            ),
            stage_qty_expr > 0,
        )
    )

    if section_ids is not None:
        query = query.where(WorkTask.section_id.in_(section_ids))
    elif section_id is not None:
        query = query.where(WorkTask.section_id == section_id)

    op_names_sq = _operation_names_subquery()
    next_op_names_sq = _next_operation_names_subquery()
    query = query.outerjoin(op_names_sq, op_names_sq.c.route_stage_id == from_stage.id)
    query = query.outerjoin(next_op_names_sq, next_op_names_sq.c.route_stage_id == next_stage.id)

    if search:
        search_like = f"%{search.strip()}%"
        query = query.where(
            or_(
                Product.sku.ilike(search_like),
                cast(WorkTask.id, String).ilike(search_like),
                cast(from_line.plan_position_id, String).ilike(search_like),
                op_names_sq.c.operation_names.ilike(search_like),
            )
        )

    if product_sku:
        query = query.where(Product.sku.ilike(f"%{product_sku.strip()}%"))
    if operation_name and operation_name.strip() not in ("", "—"):
        query = query.where(op_names_sq.c.operation_names.ilike(f"%{operation_name.strip()}%"))
    if next_operation_name:
        query = query.where(
            next_op_names_sq.c.next_operation_names.ilike(f"%{next_operation_name.strip()}%")
        )
    if next_section_name:
        query = query.where(
            or_(
                next_section.name.ilike(f"%{next_section_name.strip()}%"),
                next_section.code.ilike(f"%{next_section_name.strip()}%"),
            )
        )
    if task_id is not None:
        query = query.where(WorkTask.id == task_id)
    if plan_position_id is not None:
        query = query.where(from_line.plan_position_id == plan_position_id)
    if transferable_qty is not None:
        query = query.where(stage_qty_expr == transferable_qty)
    if dimensions:
        from app.stock.services import dimensions_match_clause

        dims_active, dims = parse_dimensions_filter(dimensions)
        if dims_active:
            query = query.where(dimensions_match_clause(WorkTask.dimensions, dims))

    return _apply_ready_production_order(
        query,
        clauses=sort_clauses,
        transferable_expr=stage_qty_expr,
        from_line=from_line,
        from_stage=from_stage,
        next_section=next_section,
    )


async def _scope_has_stock_sections(
    db: AsyncSession,
    *,
    section_id: int | None,
    spg_id: int | None,
) -> bool:
    if section_id is not None:
        sec = await db.get(Section, section_id)
        return is_stock_section(sec)
    if spg_id is not None:
        count = await db.scalar(
            select(func.count())
            .select_from(Section)
            .join(SpgSection, SpgSection.section_id == Section.id)
            .where(
                SpgSection.spg_id == spg_id,
                Section.type.in_(STOCK_SECTION_TYPES),
            )
        )
        return bool(count)
    return True


def _ready_item_matches_column_filters(
    item: dict,
    *,
    product_sku: str | None,
    operation_name: str | None,
    next_operation_name: str | None,
    next_section_name: str | None,
    task_id: int | None,
    plan_position_id: int | None,
    transferable_qty: Decimal | None,
    dimensions: str | None = None,
) -> bool:
    if task_id is not None and item.get("task_id") != task_id:
        return False
    if plan_position_id is not None and item.get("plan_position_id") != plan_position_id:
        return False
    if product_sku:
        sku = (item.get("product_sku") or "").lower()
        if product_sku.strip().lower() not in sku:
            return False
    if operation_name and operation_name.strip() not in ("", "—"):
        op = (item.get("operation_name") or "").lower()
        if operation_name.strip().lower() not in op:
            return False
    if next_operation_name:
        next_op = (item.get("next_operation_name") or "").lower()
        if next_operation_name.strip().lower() not in next_op:
            return False
    if next_section_name:
        code = (item.get("next_section_code") or "").lower()
        name = (item.get("next_section_name") or "").lower()
        needle = next_section_name.strip().lower()
        if needle not in code and needle not in name:
            return False
    if transferable_qty is not None:
        try:
            item_qty = _to_decimal(item.get("transferable_quantity"))
        except InvalidOperation:
            return False
        if item_qty != transferable_qty:
            return False
    if dimensions:
        dims_active, dims = parse_dimensions_filter(dimensions)
        if dims_active:
            item_dims = item.get("dimensions")
            if dims is None:
                if item_dims is not None:
                    return False
            elif item_dims != dims:
                return False
    return True


@dataclass(frozen=True)
class _StockReadyCandidate:
    """Подготовленная складская строка: объекты уже прочитаны, бюджет ещё нет.

    Порядок обхода — как в построчном цикле (#290): сначала выбор
    кандидатов (next_line / SPG / next_task / fake task / план), затем
    бюджет списком, затем фильтры ответа.
    """

    section: Section
    spl: SectionPlanLine
    own_stage: RouteStage | None
    next_stage: RouteStage
    next_section: Section
    task: WorkTask
    is_new_task: bool
    planned_qty: Decimal


async def _fetch_stock_ready_items(
    db: AsyncSession,
    *,
    section_id: int | None,
    spg_id: int | None,
    search: str | None,
    product_sku: str | None = None,
    operation_name: str | None = None,
    next_operation_name: str | None = None,
    next_section_name: str | None = None,
    task_id: int | None = None,
    plan_position_id: int | None = None,
    transferable_qty: Decimal | None = None,
    dimensions: str | None = None,
) -> list[dict]:
    """Складские ready-строки: prefetch списков, те же фильтры в Python (#290).

    Раньше на каждую released-план-строку каждого складского участка уходило
    ~7 запросов (2836 на страницу из 48 строк). Теперь шесть запросов на
    всю ветку: секции → план-строки → задачи → операции → изделия →
    бюджеты списком (:func:`stock_line_bulk`).

    Фильтры и порядок отбора — строка в строку, как в построчном цикле:
    search-haystack, членство в СПГ ∧ «адресат не принимает обычную
    передачу», обязательность next_task, цепочка резолва ``product_id``,
    ``planned_qty <= 0 → PlanPosition.quantity``, бюджет > 0, затем
    :func:`_ready_item_matches_column_filters`.
    """
    from app.models.production_plan import PlanPosition
    from app.transfers.transferable import StockLineRequest, stock_line_bulk

    search_like = f"%{search.strip()}%" if search else None

    # ── 1. Секции объёма: одна выборка + членство в СПГ подзапросом ───────
    # «Первое членство» секции — тот же смысл, что db.scalar(spg_id по
    # секции) в sections_share_spg, только без запроса на секцию.
    # Явный correlate гасит авто-корреляцию общих FROM: в SPG-ветке внешний
    # запрос тоже берёт spg_sections, и без неё подзапрос потерял бы свой FROM.
    own_spg_sq = (
        select(SpgSection.spg_id)
        .where(SpgSection.section_id == Section.id)
        .correlate(Section)
        .limit(1)
        .scalar_subquery()
    )
    sections_query = select(Section, own_spg_sq.label("spg_id")).options(
        # Списки пользователей/операций/СПГ ready-строке не нужны: раньше
        # selectin грузил их на каждую секцию впустую (#290).
        lazyload(Section.users),
        lazyload(Section.operations),
        lazyload(Section.spg_links),
    )
    if spg_id is not None:
        sections_query = (
            sections_query.join(SpgSection, SpgSection.section_id == Section.id)
            .where(SpgSection.spg_id == spg_id)
        )
    elif section_id is not None:
        sections_query = sections_query.where(Section.id == section_id)
    else:
        sections_query = sections_query.where(Section.type.in_(STOCK_SECTION_TYPES))

    scope = [
        (sec, spg)
        for sec, spg in (await db.execute(sections_query)).all()
        # Участок чужого типа и участок без СПГ — не источник ready-строк
        # (раньше: is_stock_section + «sec_spg_id is None → continue»).
        if is_stock_section(sec) and spg is not None
    ]
    if not scope:
        return []
    section_by_id = {sec.id: sec for sec, _spg in scope}
    own_spg_by_section = {sec.id: spg for sec, spg in scope}
    section_ids = list(section_by_id)

    # ── 2. Released-план-строки одним запросом ─────────────────────────────
    next_line = aliased(SectionPlanLine, name="stock_next_line")
    own_stage = aliased(RouteStage, name="stock_own_stage")
    next_stage = aliased(RouteStage, name="stock_next_stage")
    next_sec = aliased(Section, name="stock_next_sec")
    next_spg_sq = (
        select(SpgSection.spg_id)
        .where(SpgSection.section_id == next_line.section_id)
        .correlate(next_line)
        .limit(1)
        .scalar_subquery()
    )
    lines_query = (
        select(
            SectionPlanLine,
            PlanPosition,
            next_line,
            own_stage,
            next_stage,
            next_sec,
            next_spg_sq.label("next_spg_id"),
        )
        .join(PlanPosition, PlanPosition.id == SectionPlanLine.plan_position_id)
        .join(Product, Product.id == PlanPosition.product_id)
        .outerjoin(
            next_line,
            (next_line.plan_position_id == SectionPlanLine.plan_position_id)
            & (next_line.sequence == SectionPlanLine.sequence + 1),
        )
        .outerjoin(own_stage, own_stage.id == SectionPlanLine.route_stage_id)
        .outerjoin(next_stage, next_stage.id == next_line.route_stage_id)
        .outerjoin(next_sec, next_sec.id == next_line.section_id)
        .where(
            SectionPlanLine.section_id.in_(section_ids),
            PlanPosition.status == "released",
        )
        .options(
            # Операции следующего этапа читает общий запрос операций ниже,
            # членство СПГ — подзапрос next_spg_sq: selectin здесь дал бы
            # два лишних запроса (и N+1 по lazy, если лезть по одному).
            lazyload(own_stage.operations),
            lazyload(next_stage.operations),
            lazyload(next_sec.users),
            lazyload(next_sec.operations),
            lazyload(next_sec.spg_links),
        )
    )
    if search_like:
        lines_query = lines_query.where(
            or_(
                Product.sku.ilike(search_like),
                cast(SectionPlanLine.plan_position_id, String).ilike(search_like),
            )
        )
    elif product_sku:
        lines_query = lines_query.where(Product.sku.ilike(f"%{product_sku.strip()}%"))
    if plan_position_id is not None:
        lines_query = lines_query.where(
            SectionPlanLine.plan_position_id == plan_position_id
        )

    line_rows = (await db.execute(lines_query)).all()
    if not line_rows:
        return []

    # ── 3. Задачи-кандидаты (fake/next) для собственных и соседних строк ──
    own_line_ids = {row[0].id for row in line_rows}
    next_line_ids = {row[2].id for row in line_rows if row[2] is not None}
    task_line_ids = own_line_ids | next_line_ids
    tasks_by_line: dict[int, list[WorkTask]] = {}
    if task_line_ids:
        tasks = (
            await db.execute(
                select(WorkTask)
                .where(
                    WorkTask.section_plan_line_id.in_(task_line_ids),
                    WorkTask.status != WorkTaskStatus.cancelled,
                )
                .order_by(WorkTask.id.asc())
            )
        ).scalars().all()
        for task in tasks:
            tasks_by_line.setdefault(task.section_plan_line_id, []).append(task)

    # Габариты заданий — из позиций, которые основной запрос уже принёс
    # (join `plan_pos` в `line_rows`). Поштучный `task_dimensions_for_plan_line`
    # делал `db.get(PlanPosition)`, который попадал в identity-map и не стоил
    # ничего; отдельный bulk-запрос был бы лишним, поэтому берём готовые
    # объекты (#299).
    dimensions_by_position: dict[int, dict | None] = {
        plan_pos.id: position_dimensions_for_task(plan_pos)
        for plan_pos in {row[1] for row in line_rows}
        if plan_pos is not None
    }

    prepared: list[_StockReadyCandidate] = []
    for spl, plan_pos, next_l, own_stg, next_stg, next_s, next_spg in line_rows:
        if next_l is None or next_stg is None or next_s is None:
            continue

        sec = section_by_id[spl.section_id]
        # Адресат передачи со склада — склад оборачиваемого запаса или
        # терминальная секция (#136): «Отправлено» принимает материал
        # обычной передачей («Передать»), остатков там не возникает
        # (StockProjectionManager пропускает терминал). Задача на терминале
        # появляется лениво — при первой передаче, как на складах (#176),
        # поэтому её отсутствие до передачи строку не скрывает.
        destination_accepts_transfer = accepts_ordinary_transfer(next_s)
        # sections_share_spg по уже прочитанному членству (без запросов).
        share_spg = spl.section_id == next_l.section_id or (
            own_spg_by_section[spl.section_id] is not None
            and own_spg_by_section[spl.section_id] == next_spg
        )
        if share_spg and not destination_accepts_transfer:
            continue

        next_task = next(
            (
                task
                for task in tasks_by_line.get(next_l.id, ())
                if task.status not in CLOSED_WORK_TASK_STATUSES
            ),
            None,
        )
        if next_task is None and not destination_accepts_transfer:
            continue

        fake_task = next(iter(tasks_by_line.get(spl.id, ())), None)
        planned_qty = spl.planned_quantity or Decimal(0)
        if planned_qty <= 0:
            planned_qty = plan_pos.quantity if plan_pos else Decimal(0)

        is_new_task = fake_task is None
        if is_new_task:
            if next_task is not None:
                product_id = next_task.product_id
            else:
                product_id = spl.product_id
                if product_id is None:
                    product_id = plan_pos.product_id if plan_pos else None
                if product_id is None:
                    continue
            fake_task = WorkTask(
                section_plan_line_id=spl.id,
                section_id=sec.id,
                product_id=product_id,
                route_stage_id=spl.route_stage_id,
                planned_quantity=planned_qty,
                status=WorkTaskStatus.ready,
                due_date=spl.due_date,
                dimensions=dimensions_by_position.get(spl.plan_position_id),
            )

        prepared.append(
            _StockReadyCandidate(
                section=sec,
                spl=spl,
                own_stage=own_stg,
                next_stage=next_stg,
                next_section=next_s,
                task=fake_task,
                is_new_task=is_new_task,
                planned_qty=planned_qty,
            )
        )

    if not prepared:
        return []

    # ── 4. Операции: имена следующего шага + пройденные операции ───────────
    # Один запрос закрывает оба чтения route_operations: имена операций
    # следующего этапа (как selectin next_stage.operations) и коды
    # операций маршрута до своего этапа (как completed_operations_*).
    pairs = {
        (row.spl.route_id, row.own_stage.sequence)
        for row in prepared
        if row.own_stage is not None
    }
    next_stage_ids = {row.next_stage.id for row in prepared}
    op_conditions = []
    if next_stage_ids:
        op_conditions.append(RouteOperation.route_stage_id.in_(next_stage_ids))
    op_conditions.extend(
        and_(RouteStage.route_id == route_id, RouteStage.sequence <= through_sequence)
        for route_id, through_sequence in sorted(pairs)
    )
    names_by_stage: dict[int, list[str]] = {}
    ops_by_route: dict[int, list[tuple[int, str]]] = {}
    if op_conditions:
        op_rows = (
            await db.execute(
                select(
                    RouteOperation.route_stage_id,
                    RouteStage.route_id,
                    RouteStage.sequence.label("stage_sequence"),
                    RouteOperation.operation_code,
                    RouteOperation.operation_name,
                )
                .join(RouteStage, RouteStage.id == RouteOperation.route_stage_id)
                .where(or_(*op_conditions))
                .order_by(RouteOperation.route_stage_id, RouteOperation.sequence)
            )
        ).all()
        for stage_id, route_id, stage_sequence, code, name in op_rows:
            names_by_stage.setdefault(stage_id, []).append(name)
            if code:
                ops_by_route.setdefault(route_id, []).append((stage_sequence, code))
    next_op_names = {
        stage_id: ", ".join(names)
        for stage_id, names in names_by_stage.items()
        if names
    }
    consume_ops = {
        (route_id, through_sequence): sorted({
            code
            for stage_sequence, code in ops_by_route.get(route_id, ())
            if stage_sequence <= through_sequence
        })
        for route_id, through_sequence in sorted(pairs)
    }

    # ── 5. Изделия для sku (одним IN, без гидрации сущности) ──────────────
    product_ids = {row.task.product_id for row in prepared if row.task.product_id is not None}
    skus: dict[int, str] = {}
    if product_ids:
        skus = dict(
            (
                await db.execute(
                    select(Product.id, Product.sku).where(Product.id.in_(product_ids))
                )
            ).all()
        )

    # ── 6. Бюджет складских строк — один bulk-проход transferable ──────────
    budget_results = await stock_line_bulk(
        db,
        [
            StockLineRequest(
                task=row.task,
                section=row.section,
                planned_qty=row.planned_qty,
            )
            for row in prepared
        ],
        lines={row.spl.id: row.spl for row in prepared},
        stages={
            row.spl.route_stage_id: row.own_stage
            for row in prepared
            if row.own_stage is not None
        },
        consume_ops=consume_ops,
    )

    passing = [
        (row, result)
        for row, result in zip(prepared, budget_results, strict=True)
        if result.line.budget > 0
    ]
    # Запись в read-ручке — одна пачкой и только для строк, прошедших
    # бюджетный фильтр (раньше db.add + db.flush стояли в цикле до бюджета).
    new_tasks = [row.task for row, _result in passing if row.is_new_task]
    if new_tasks:
        db.add_all(new_tasks)
        await db.flush()

    stock_items: list[dict] = []
    for row, result in passing:
        line = result.line
        item_sku = skus.get(row.task.product_id) or ""
        candidate = {
            "task_id": row.task.id,
            "section_id": row.task.section_id,
            "section_code": row.section.code,
            "section_name": row.section.name,
            "plan_position_id": row.spl.plan_position_id,
            "route_stage_id": row.spl.route_stage_id,
            "sequence": row.spl.sequence,
            "operation_code": None,
            "operation_name": "",
            "product_id": row.task.product_id,
            "product_sku": item_sku,
            "planned_quantity": _fmt_qty(row.planned_qty),
            "completed_quantity": _fmt_qty(line.produced),
            "already_transferred_quantity": _fmt_qty(line.used),
            "transferable_quantity": _fmt_qty(line.budget),
            "has_next_step": True,
            "next_section_id": row.next_section.id,
            "next_section_code": row.next_section.code,
            "next_section_name": row.next_section.name,
            "next_operation_name": next_op_names.get(row.next_stage.id),
            "next_step_sequence": row.next_stage.sequence,
            "next_step_is_final": bool(row.next_stage.is_final),
            "is_final": False,
            **_ready_dimensions_fields(row.task.dimensions),
        }
        if search and search.strip():
            search_lower = search.strip().lower()
            haystacks = (
                candidate.get("product_sku") or "",
                candidate.get("operation_name") or "",
                str(candidate.get("plan_position_id") or ""),
                str(candidate.get("task_id") or ""),
            )
            if not any(search_lower in value.lower() for value in haystacks):
                continue
        if not _ready_item_matches_column_filters(
            candidate,
            product_sku=product_sku,
            operation_name=operation_name,
            next_operation_name=next_operation_name,
            next_section_name=next_section_name,
            task_id=task_id,
            plan_position_id=plan_position_id,
            transferable_qty=transferable_qty,
            dimensions=dimensions,
        ):
            continue
        stock_items.append(candidate)

    return stock_items


async def list_ready_to_transfer(
    db: AsyncSession,
    *,
    section_id: int | None = None,
    spg_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    sort: str = "sequence:asc",
    product_sku: str | None = None,
    operation_name: str | None = None,
    next_operation_name: str | None = None,
    next_section_name: str | None = None,
    task_id: int | None = None,
    plan_position_id: int | None = None,
    transferable_qty: str | None = None,
    dimensions: str | None = None,
) -> dict:
    """List SectionTasks that have quantity ready to be transferred.

    A task is "ready to transfer" when:
      * it has a next route step (``SectionPlanLine.sequence + 1``
        exists), or it sits on the final route stage (тикет #96 —
        такой задаче доступен final release),
      * the next step is not final (для межучастковых передач),
      * бюджет по финальности участка > 0 (фабрики ``app.transfers.budget``
        поверх ledger-агрегатов, тикет #119): финальный этап —
        ``sendable_qty`` (produced − released), остальные —
        ``transferable_qty`` (completed − transferred).

    Filters:
      * ``section_id`` — restrict to a single section.
      * ``spg_id`` — restrict to all sections of an SPG (overrides
        ``section_id`` if both given).
    """
    # Сортировка разбирается и проверяется ДО выборки, в том числе до раннего
    # выхода по пустому СПГ: кликнул неизвестную колонку — 400, а не пустая
    # таблица. Молчаливого отката на дефолт нет.
    sort_clauses = parse_sort(sort, default=_READY_SORT_DEFAULT)
    for clause in sort_clauses:
        if clause.field not in READY_SORT_FIELDS:
            raise HTTPException(status_code=400, detail=f"Invalid sort field: {clause.field}")

    spg_section_ids: list[int] | None = None
    if spg_id is not None:
        spg_section_ids = (
            await db.execute(
                select(SpgSection.section_id).where(SpgSection.spg_id == spg_id)
            )
        ).scalars().all()
        if not spg_section_ids:
            return {
                "items": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
                "filters": {"section_id": section_id, "spg_id": spg_id},
            }

    parsed_transferable_qty: Decimal | None = None
    if transferable_qty:
        try:
            parsed_transferable_qty = _to_decimal(transferable_qty)
        except InvalidOperation:
            parsed_transferable_qty = None

    # transferable_qty/dimensions применяются по строке в Python (тикет #91):
    # трансформирующая задача разворачивается в строки выходов, и эти фильтры
    # на уровне SQL-задачи неверны. Остальные фильтры (task-level атрибуты)
    # остаются в SQL.
    production_query = _build_production_ready_query(
        section_ids=spg_section_ids,
        section_id=section_id if spg_id is None else None,
        search=search,
        product_sku=product_sku,
        operation_name=operation_name,
        next_operation_name=next_operation_name,
        next_section_name=next_section_name,
        task_id=task_id,
        plan_position_id=plan_position_id,
        transferable_qty=None,
        dimensions=None,
        sort_clauses=sort_clauses,
    )

    has_stock = await _scope_has_stock_sections(db, section_id=section_id, spg_id=spg_id)

    # Все production-строки гидратируются сразу (обычная задача → 1 строка,
    # трансформирующая → N строк выходов); пагинация идёт по готовым строкам.
    # Бюджеты строк — один bulk-проход transferable на всю страницу
    # (follow-up #131): секции/этапы уже в руках основного запроса.
    rows = (await db.execute(production_query)).all()
    lines_by_task = await task_transferable_lines_bulk(
        db,
        [row[0] for row in rows],
        sections={row[3].id: row[3] for row in rows},
        stages={row[2].id: row[2] for row in rows},
        # Строки плана тоже уже в руках: без подсказки складская ветка
        # добирала их поштучным `db.get` (#299).
        lines={
            row[0].section_plan_line_id: row[1]
            for row in rows
            if row[0].section_plan_line_id is not None
        },
    )
    items: list[dict] = []
    for row in rows:
        items.extend(_hydrate_production_ready_row(row, lines_by_task=lines_by_task))

    items = [
        item
        for item in items
        if _ready_item_matches_column_filters(
            item,
            product_sku=product_sku,
            operation_name=operation_name,
            next_operation_name=next_operation_name,
            next_section_name=next_section_name,
            task_id=task_id,
            plan_position_id=plan_position_id,
            transferable_qty=parsed_transferable_qty,
            dimensions=dimensions,
        )
    ]

    if has_stock:
        stock_items = await _fetch_stock_ready_items(
            db,
            section_id=section_id,
            spg_id=spg_id,
            search=search,
            product_sku=product_sku,
            operation_name=operation_name,
            next_operation_name=next_operation_name,
            next_section_name=next_section_name,
            task_id=task_id,
            plan_position_id=plan_position_id,
            transferable_qty=parsed_transferable_qty,
            dimensions=dimensions,
        )
        items.extend(stock_items)

    # Финальный порядок страницы — общий Python-проход по ОБЕИМ веткам
    # (производственные и складские строки), поэтому одинаковый вход даёт
    # одинаковый порядок независимо от ветки.
    items = sort_items(
        items,
        sort_clauses,
        _READY_SORT_KEYS,
        nulls_last=_READY_SORT_NULLS_LAST_FIELDS,
        tiebreaker=_ready_item_tiebreaker,
    )
    total = len(items)
    items = items[offset : offset + limit]

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "filters": {"section_id": section_id, "spg_id": spg_id},
    }



# ─── Сортировка журнала передач (единый контракт ?sort=field:order,...) ───────
# Короткие имена ``sku`` / ``from`` / ``to`` / ``quantity`` — часть контракта
# журнала: фронт шлёт именно их. Переименование — отдельное решение, здесь они
# остаются вторыми именами тех же колонок внутри общей таблицы резолва.
def _history_sort_columns(*, from_section, to_section) -> dict[str, object]:
    return {
        "created_at": Transfer.created_at,
        "status": Transfer.status,
        "product_sku": Product.sku,
        "sku": Product.sku,
        "from_section_name": from_section.name,
        "from": from_section.name,
        "to_section_name": to_section.name,
        "to": to_section.name,
        "sent_quantity": Transfer.sent_quantity,
        "quantity": Transfer.sent_quantity,
        "transfer_no": Transfer.transfer_no,
    }


# Без параметра сортировки порядок прежний: новые передачи сверху.
_HISTORY_SORT_DEFAULT = SortClause("created_at", "desc")


async def get_section_transfer_history(
    db: AsyncSession,
    *,
    section_id: int | None = None,
    spg_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    status: str | None = None,
    sort: str = "created_at:desc",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    product_sku: str | None = None,
    from_section_name: str | None = None,
    to_section_name: str | None = None,
) -> dict:
    """Return both incoming and outgoing transfers for a section or SPG (history log)."""
    sort_clauses = parse_sort(sort, default=_HISTORY_SORT_DEFAULT)

    from_section = aliased(Section)
    to_section = aliased(Section)
    from_task = aliased(WorkTask)
    to_task = aliased(WorkTask)
    from_stage = aliased(RouteStage)
    to_stage = aliased(RouteStage)
    from_line = aliased(SectionPlanLine)

    # 400 на неизвестное поле — до раннего выхода по пустому СПГ: кликнул
    # колонку, которой сервер не умеет сортировать, и получил пустой журнал.
    sort_columns = _history_sort_columns(from_section=from_section, to_section=to_section)
    for clause in sort_clauses:
        if clause.field not in sort_columns:
            raise HTTPException(status_code=400, detail=f"Invalid sort field: {clause.field}")

    base_query = (
        select(
            Transfer,
            from_section,
            to_section,
            from_task,
            to_task,
            from_stage,
            to_stage,
            from_line,
            Product.sku,
        )
        .join(from_section, from_section.id == Transfer.from_section_id)
        .join(to_section, to_section.id == Transfer.to_section_id)
        .join(from_task, from_task.id == Transfer.from_task_id)
        .join(to_task, to_task.id == Transfer.to_task_id)
        .join(from_stage, from_stage.id == from_task.route_stage_id)
        .join(to_stage, to_stage.id == to_task.route_stage_id)
        .join(from_line, from_line.id == from_task.section_plan_line_id)
        .join(Product, Product.id == from_task.product_id)
    )

    if spg_id is not None:
        from app.models.spg import SpgSection
        spg_section_ids = (
            await db.execute(
                select(SpgSection.section_id).where(SpgSection.spg_id == spg_id)
            )
        ).scalars().all()
        if not spg_section_ids:
            return {
                "section_id": None,
                "spg_id": spg_id,
                "transfers": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
            }
        base_query = base_query.where(
            (Transfer.from_section_id.in_(spg_section_ids)) | (Transfer.to_section_id.in_(spg_section_ids))
        )
    elif section_id is not None:
        base_query = base_query.where(
            (Transfer.from_section_id == section_id) | (Transfer.to_section_id == section_id)
        )

    if status:
        try:
            status_enum = TransferStatus(status)
        except ValueError:
            status_enum = None
        if status_enum is not None:
            base_query = base_query.where(Transfer.status == status_enum)
    if date_from is not None:
        base_query = base_query.where(Transfer.created_at >= date_from)
    if date_to is not None:
        base_query = base_query.where(Transfer.created_at <= date_to)
    if product_sku:
        product_sku_like = f"%{product_sku}%"
        base_query = base_query.where(Product.sku.ilike(product_sku_like))
    if from_section_name:
        from_section_name_like = f"%{from_section_name}%"
        base_query = base_query.where(from_section.name.ilike(from_section_name_like))
    if to_section_name:
        to_section_name_like = f"%{to_section_name}%"
        base_query = base_query.where(to_section.name.ilike(to_section_name_like))
    if search:
        search_like = f"%{search}%"
        base_query = base_query.where(
            or_(
                Product.sku.ilike(search_like),
                from_section.name.ilike(search_like),
                to_section.name.ilike(search_like),
                Transfer.transfer_no.ilike(search_like),
                Transfer.comment.ilike(search_like),
                cast(from_line.plan_position_id, String).ilike(search_like),
            )
        )

    count_stmt = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # Приоритеты слева направо, в конце tiebreaker по PK.
    base_query = apply_sort(
        base_query, sort_clauses, sort_columns, tiebreaker=Transfer.id,
    )

    rows = (await db.execute(base_query.offset(offset).limit(limit))).all()

    transfers = []
    for transfer, from_sec, to_sec, src_task, dst_task, src_stage, dst_stage, src_line, row_sku in rows:
        sent = _to_decimal(transfer.sent_quantity or 0)
        accepted = _to_decimal(transfer.accepted_quantity or 0)
        rejected = _to_decimal(transfer.rejected_quantity or 0)
        remaining = sent - accepted - rejected
        if remaining < 0:
            remaining = Decimal(0)

        from_op_name = ", ".join(op.operation_name for op in src_stage.operations) if src_stage and src_stage.operations else ""
        to_op_name = ", ".join(op.operation_name for op in dst_stage.operations) if dst_stage and dst_stage.operations else ""

        transfers.append(
            {
                "transfer_id": transfer.id,
                "transfer_no": transfer.transfer_no,
                "status": transfer.status.value,
                "from_task_id": transfer.from_task_id,
                "to_task_id": transfer.to_task_id,
                "from_section_id": transfer.from_section_id,
                "from_section_code": from_sec.code,
                "from_section_name": from_sec.name,
                "to_section_id": transfer.to_section_id,
                "to_section_code": to_sec.code,
                "to_section_name": to_sec.name,
                "from_operation_name": from_op_name,
                "to_operation_name": to_op_name,
                "sent_quantity": _fmt_qty(sent),
                "accepted_quantity": _fmt_qty(accepted),
                "rejected_quantity": _fmt_qty(rejected),
                "remaining_quantity": _fmt_qty(remaining),
                "comment": transfer.comment,
                "sent_at": transfer.sent_at.isoformat() if transfer.sent_at else None,
                "created_at": transfer.created_at.isoformat() if transfer.created_at else None,
                "is_post_factum": transfer.is_post_factum,
                "physical_handover_at": transfer.physical_handover_at.isoformat() if transfer.physical_handover_at else None,
                "from_task_status": src_task.status.value,
                "to_task_status": dst_task.status.value,
                "product_sku": row_sku,
                "from_line_id": src_line.id,
                "from_line_sequence": src_line.sequence,
                "plan_position_id": src_line.plan_position_id,
                # Габарит переданного (тикет #95): колонка «Размер» в UI.
                "dimensions": transfer.dimensions,
            }
        )

    return {
        "section_id": section_id,
        "spg_id": spg_id,
        "transfers": transfers,
        "total": total,
        "limit": limit,
        "offset": offset,
    }

