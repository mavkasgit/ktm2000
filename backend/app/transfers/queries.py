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

from datetime import datetime
from decimal import Decimal
from typing import cast as tcast

from sqlalchemy import String, Subquery, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.defect import DefectItem, TransferDiscrepancyDefectItem
from app.models.internal_plan import SectionPlanLine
from app.models.product import Product
from app.models.route import RouteStage, RouteOperation
from app.models.section import Section
from app.models.spg import SpgSection
from app.services.route_storage_classifier import (
    SECTION_TYPE_PRODUCTION,
    STOCK_TYPES,
    is_stock_section,
)
from app.models.transfer import (
    Transfer,
    TransferDiscrepancy,
    TransferStatus,
)
from app.models.work_task import WorkTask, WorkTaskStatus
from app.domain.dimensions import parse_dimensions_filter, format_dimensions
from app.services.plan_position_hanger import task_dimensions_for_plan_line

from app.services.shopfloor.common import _get_transfer, _to_decimal
from app.stock.ledger import net_transferred_sq
from app.services.shopfloor.output_rows import UsedSource, build_task_output_rows
from app.transfers.budget import (
    remaining_plain,
    remaining_send,
    remaining_transform,
    sendable_qty_sql,
    transferable_qty_sql,
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
    result_discrepancies = []
    for d in discrepancies:
        links = (
            await db.execute(
                select(TransferDiscrepancyDefectItem, DefectItem)
                .join(DefectItem, DefectItem.id == TransferDiscrepancyDefectItem.defect_item_id)
                .where(TransferDiscrepancyDefectItem.transfer_discrepancy_id == d.id)
            )
        ).all()
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
            remaining = Decimal("0")

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


def _completed_qty_subquery():
    from app.stock.models import Reason, StockTransaction

    return (
        select(
            StockTransaction.task_id,
            func.coalesce(func.sum(StockTransaction.quantity), 0).label("completed_qty"),
        )
        .where(StockTransaction.reason == Reason.COMPLETE)
        .group_by(StockTransaction.task_id)
        .subquery("completed_qty_sq")
    )


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
        completion_comment,
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
        "completion_comment": completion_comment,
    }


def _hydrate_plain_ready_row(row) -> dict | None:
    (
        task,
        _line,
        stage,
        _section,
        _product_sku,
        _next_l,
        _next_stg,
        _next_sec,
        _completion_comment,
        completed,
        transferred,
        released,
        _transferable_qty,
        _sendable_qty,
    ) = row
    # Финальный этап (тикет #96): «отдано» = уже выпущено (FINAL_RELEASE),
    # а не переданное на следующий участок; смысл бюджета — отправка
    # (``remaining_send``, тикет #119). Нефинальный — передача
    # (``remaining_plain``).
    if bool(stage.is_final):
        used = _to_decimal(released)
        transferable = remaining_send(_to_decimal(completed), used)
    else:
        used = _to_decimal(transferred)
        transferable = remaining_plain(_to_decimal(completed), used)
    if transferable <= 0:
        return None
    return {
        **_ready_row_common(row),
        "planned_quantity": _fmt_qty(task.planned_quantity),
        "completed_quantity": _fmt_qty(completed),
        "already_transferred_quantity": _fmt_qty(used),
        "transferable_quantity": _fmt_qty(transferable),
        **_ready_dimensions_fields(task.dimensions),
    }


async def _hydrate_production_ready_row(db: AsyncSession, row) -> list[dict]:
    """Ready-строки одной production-задачи.

    Обычная задача — одна строка ``dimensions = task.dimensions``.
    Трансформирующая (резка, тикет #91) — строка на каждый выход
    спецификации: ``dimensions = outputs[i].dimensions``,
    ``planned_quantity = outputs[i].quantity``; transferable выхода =
    ``min(outputs[i].quantity, произведено по размеру) − уже переданное
    по этому размеру`` (инвариант D2). Строки с transferable <= 0
    отбрасываются.

    Финальный этап (тикет #96): «уже отданное» по размеру — net
    FINAL_RELEASE (released), а не TRANSFER_SEND; transferable выхода =
    releasable = произведено по размеру − уже выпущено по размеру.
    """
    task = row[0]
    stage = row[2]
    is_final = bool(stage.is_final)
    outputs = task.outputs or []
    if not outputs:
        item = _hydrate_plain_ready_row(row)
        return [item] if item is not None else []

    common = _ready_row_common(row)
    rows = await build_task_output_rows(
        db,
        task_id=task.id,
        outputs=outputs,
        used_source=(
            UsedSource.NET_FINAL_RELEASE if is_final else UsedSource.NET_TRANSFERRED
        ),
    )

    items: list[dict] = []
    for output in rows:
        planned = output.quantity
        if planned <= 0:
            continue
        # Смысл бюджета выбирает потребитель по финальности участка (#119):
        # финальный — отправка (``remaining_send``), остальные — передача
        # (``remaining_transform``).
        if is_final:
            transferable = remaining_send(
                output.produced_quantity, output.used_quantity,
            )
        else:
            transferable = remaining_transform(
                output.produced_quantity, output.used_quantity,
            )
        if transferable <= 0:
            continue
        items.append({
            **common,
            "planned_quantity": _fmt_qty(planned),
            "completed_quantity": _fmt_qty(output.produced_quantity),
            "already_transferred_quantity": _fmt_qty(output.used_quantity),
            "transferable_quantity": _fmt_qty(transferable),
            **_ready_dimensions_fields(output.dimensions),
        })
    return items

READY_SORT_FIELDS = frozenset({
    "sequence",
    "task_id",
    "plan_position_id",
    "product_sku",
    "operation_name",
    "transferable_qty",
    "next_section_name",
    "dimensions",
})


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


def _apply_ready_production_order(
    query,
    *,
    sort_by: str,
    sort_order: str,
    transferable_expr,
    from_line,
    from_stage,
    next_section,
    next_op_names_sq,
):
    order_column = from_line.sequence
    if sort_by == "task_id":
        order_column = WorkTask.id
    elif sort_by == "plan_position_id":
        order_column = from_line.plan_position_id
    elif sort_by == "product_sku":
        order_column = Product.sku
    elif sort_by == "operation_name":
        order_column = from_stage.sequence
    elif sort_by == "transferable_qty":
        order_column = transferable_expr
    elif sort_by == "next_section_name":
        order_column = next_section.name
    elif sort_by == "dimensions":
        order_column = WorkTask.dimensions["length_mm"].as_float()

    nulls_last = sort_by == "dimensions"
    if sort_order == "asc":
        primary = order_column.asc()
        if nulls_last:
            primary = primary.nulls_last()
        return query.order_by(primary, WorkTask.id.asc())
    primary = order_column.desc()
    if nulls_last:
        primary = primary.nulls_last()
    return query.order_by(primary, WorkTask.id.desc())


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
    sort_by: str = "sequence",
    sort_order: str = "asc",
):
    from_section = aliased(Section, name="from_section")
    next_section = aliased(Section, name="next_section")
    from_stage = aliased(RouteStage, name="from_stage")
    next_stage = aliased(RouteStage, name="next_stage")
    from_line = aliased(SectionPlanLine, name="from_line")
    next_line = aliased(SectionPlanLine, name="next_line")

    from app.stock.ledger import net_by_reason_sq
    from app.stock.models import Reason, StockTransaction
    completed_sq = _completed_qty_subquery()
    transferred_sq = tcast(Subquery, net_transferred_sq("transferred_qty_sq"))
    released_sq = tcast(Subquery, net_by_reason_sq(Reason.FINAL_RELEASE, "released_qty_sq"))
    # Единственный владелец формулы — transfers/budget (#119): ready-запрос
    # отдаёт ДВА именованных столбца (передача / отправка); семантику по
    # финальности участка выбирает потребитель, фабрика CASE не строит.
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

    latest_complete = (
        select(
            StockTransaction.task_id,
            StockTransaction.id.label("st_id"),
        )
        .where(StockTransaction.reason == Reason.COMPLETE)
        .distinct(StockTransaction.task_id)
        .order_by(StockTransaction.task_id, StockTransaction.id.desc())
        .subquery()
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
            StockTransaction.id.label("completion_tx_id"),
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
        .outerjoin(
            latest_complete,
            latest_complete.c.task_id == WorkTask.id,
        )
        .outerjoin(
            StockTransaction,
            StockTransaction.id == latest_complete.c.st_id,
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

    if sort_by not in READY_SORT_FIELDS:
        sort_by = "sequence"
    if sort_order not in ("asc", "desc"):
        sort_order = "asc"

    return _apply_ready_production_order(
        query,
        sort_by=sort_by,
        sort_order=sort_order,
        transferable_expr=stage_qty_expr,
        from_line=from_line,
        from_stage=from_stage,
        next_section=next_section,
        next_op_names_sq=next_op_names_sq,
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
        except Exception:
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


def _ready_item_sort_key(item: dict, sort_by: str, sort_order: str = "asc") -> tuple:
    if sort_by == "task_id":
        return (item.get("task_id") or 0,)
    if sort_by == "plan_position_id":
        return (item.get("plan_position_id") or 0,)
    if sort_by == "product_sku":
        return (item.get("product_sku") or "",)
    if sort_by == "operation_name":
        return (item.get("sequence") or 0, item.get("operation_name") or "")
    if sort_by == "transferable_qty":
        return (_to_decimal(item.get("transferable_quantity") or "0"),)
    if sort_by == "next_section_name":
        return (item.get("next_section_name") or "",)
    if sort_by == "dimensions":
        return _ready_dimensions_sort_key(item, sort_order)
    return (item.get("sequence") or 0, item.get("task_id") or 0)


def _ready_dimensions_sort_key(item: dict, sort_order: str) -> tuple:
    """Сортировочный ключ размера: длина от большей к меньшей, безразмерные — в конец.

    ``sort_order`` нужен, потому что общий путь (has_stock) сортирует через
    ``reverse=sort_order == "desc"`` — инверсия «переворачивает» null-флаг.
    """
    dims = item.get("dimensions")
    length = None
    if isinstance(dims, dict):
        raw = dims.get("length_mm")
        if raw is not None:
            try:
                length = _to_decimal(raw)
            except Exception:
                length = None
    has_length = length is not None
    if sort_order == "desc":
        # reverse=True: первый элемент — наибольший ключ. Безразмерные — наименьший ключ → последние.
        return (1, float(length)) if has_length else (0, 0)
    # reverse=False: безразмерные — наибольший ключ → последние.
    return (0, float(length)) if has_length else (1, 0)


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
    from app.models.production_plan import PlanPosition
    from app.transfers.services import compute_stock_section_transferable

    if spg_id is not None:
        sections = (
            await db.execute(
                select(Section)
                .join(SpgSection, SpgSection.section_id == Section.id)
                .where(SpgSection.spg_id == spg_id)
            )
        ).scalars().all()
    elif section_id is not None:
        sec = await db.get(Section, section_id)
        sections = [sec] if sec else []
    else:
        sections = (
            await db.execute(
                select(Section).where(Section.type.in_(STOCK_SECTION_TYPES))
            )
        ).scalars().all()

    stock_items: list[dict] = []
    search_like = f"%{search.strip()}%" if search else None

    for sec in sections:
        if not is_stock_section(sec):
            continue

        sec_spg_id = await db.scalar(
            select(SpgSection.spg_id).where(SpgSection.section_id == sec.id)
        )
        if sec_spg_id is None:
            continue

        lines_query = (
            select(SectionPlanLine)
            .join(PlanPosition, PlanPosition.id == SectionPlanLine.plan_position_id)
            .join(Product, Product.id == PlanPosition.product_id)
            .where(
                SectionPlanLine.section_id == sec.id,
                PlanPosition.status == "released",
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

        lines = (await db.execute(lines_query)).scalars().all()

        for spl in lines:
            next_line = await db.scalar(
                select(SectionPlanLine).where(
                    SectionPlanLine.plan_position_id == spl.plan_position_id,
                    SectionPlanLine.sequence == spl.sequence + 1,
                )
            )
            if next_line is None:
                continue

            next_stage = await db.get(RouteStage, next_line.route_stage_id)
            next_sec = await db.get(Section, next_line.section_id)
            if next_stage is None or next_sec is None:
                continue

            from app.services.shopfloor.common import sections_share_spg

            if await sections_share_spg(db, spl.section_id, next_line.section_id):
                if not is_stock_section(next_sec):
                    continue

            next_task = await db.scalar(
                select(WorkTask).where(
                    WorkTask.section_plan_line_id == next_line.id,
                    WorkTask.status.notin_([WorkTaskStatus.completed, WorkTaskStatus.cancelled]),
                )
            )
            if next_task is None and not is_stock_section(next_sec):
                continue

            fake_task = await db.scalar(
                select(WorkTask)
                .where(
                    WorkTask.section_plan_line_id == spl.id,
                    WorkTask.status != WorkTaskStatus.cancelled,
                )
                .order_by(WorkTask.id.asc())
            )

            planned_qty = spl.planned_quantity or Decimal("0")
            if planned_qty <= 0:
                plan_pos = await db.get(PlanPosition, spl.plan_position_id)
                planned_qty = plan_pos.quantity if plan_pos else Decimal("0")

            if fake_task is None:
                if next_task is not None:
                    product_id = next_task.product_id
                else:
                    product_id = spl.product_id
                    if product_id is None:
                        plan_pos = await db.get(PlanPosition, spl.plan_position_id)
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
                    dimensions=await task_dimensions_for_plan_line(db, spl.plan_position_id),
                )
                db.add(fake_task)
                await db.flush()

            transferable, _plan_remaining, physical_stock, transferred = (
                await compute_stock_section_transferable(
                    db,
                    task=fake_task,
                    section=sec,
                    planned_qty=planned_qty,
                )
            )
            if transferable <= 0:
                continue

            await db.flush()

            product = await db.get(Product, fake_task.product_id)
            product_sku = product.sku if product else ""

            next_op_name = (
                ", ".join(op.operation_name for op in next_stage.operations)
                if next_stage and next_stage.operations
                else None
            )

            candidate = {
                    "task_id": fake_task.id,
                    "section_id": fake_task.section_id,
                    "section_code": sec.code,
                    "section_name": sec.name,
                    "plan_position_id": spl.plan_position_id,
                    "route_stage_id": spl.route_stage_id,
                    "sequence": spl.sequence,
                    "operation_code": None,
                    "operation_name": "",
                    "product_id": fake_task.product_id,
                    "product_sku": product_sku,
                    "planned_quantity": _fmt_qty(planned_qty),
                    "completed_quantity": _fmt_qty(physical_stock),
                    "already_transferred_quantity": _fmt_qty(transferred),
                    "transferable_quantity": _fmt_qty(transferable),
                    "has_next_step": True,
                    "next_section_id": next_sec.id,
                    "next_section_code": next_sec.code,
                    "next_section_name": next_sec.name,
                    "next_operation_name": next_op_name,
                    "next_step_sequence": next_stage.sequence,
                    "next_step_is_final": bool(next_stage.is_final),
                    "is_final": False,
                    "completion_comment": None,
                    **_ready_dimensions_fields(fake_task.dimensions),
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
    sort_by: str = "sequence",
    sort_order: str = "asc",
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
        except Exception:
            parsed_transferable_qty = None

    if sort_by not in READY_SORT_FIELDS:
        sort_by = "sequence"
    if sort_order not in ("asc", "desc"):
        sort_order = "asc"

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
        sort_by=sort_by,
        sort_order=sort_order,
    )

    has_stock = await _scope_has_stock_sections(db, section_id=section_id, spg_id=spg_id)

    # Все production-строки гидратируются сразу (обычная задача → 1 строка,
    # трансформирующая → N строк выходов); пагинация идёт по готовым строкам.
    rows = (await db.execute(production_query)).all()
    items: list[dict] = []
    for row in rows:
        items.extend(await _hydrate_production_ready_row(db, row))

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

    reverse = sort_order == "desc"
    items.sort(key=lambda item: _ready_item_sort_key(item, sort_by, sort_order), reverse=reverse)
    total = len(items)
    items = items[offset : offset + limit]

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "filters": {"section_id": section_id, "spg_id": spg_id},
    }


async def get_section_transfer_history(
    db: AsyncSession,
    *,
    section_id: int | None = None,
    spg_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    status: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    product_sku: str | None = None,
    from_section_name: str | None = None,
    to_section_name: str | None = None,
) -> dict:
    """Return both incoming and outgoing transfers for a section or SPG (history log)."""
    from_section = aliased(Section)
    to_section = aliased(Section)
    from_task = aliased(WorkTask)
    to_task = aliased(WorkTask)
    from_stage = aliased(RouteStage)
    to_stage = aliased(RouteStage)
    from_line = aliased(SectionPlanLine)

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

    order_column = Transfer.created_at
    if sort_by == "status":
        order_column = Transfer.status
    elif sort_by in ("product_sku", "sku"):
        order_column = Product.sku
    elif sort_by in ("from_section_name", "from"):
        order_column = from_section.name
    elif sort_by in ("to_section_name", "to"):
        order_column = to_section.name
    elif sort_by in ("sent_quantity", "quantity"):
        order_column = Transfer.sent_quantity
    elif sort_by == "transfer_no":
        order_column = Transfer.transfer_no

    if sort_order == "asc":
        order_by = (order_column.asc(), Transfer.id.asc())
    else:
        order_by = (order_column.desc(), Transfer.id.desc())

    rows = (
        await db.execute(
            base_query
            .order_by(*order_by)
            .offset(offset)
            .limit(limit)
        )
    ).all()

    transfers = []
    for transfer, from_sec, to_sec, src_task, dst_task, src_stage, dst_stage, src_line, product_sku in rows:
        sent = _to_decimal(transfer.sent_quantity or 0)
        accepted = _to_decimal(transfer.accepted_quantity or 0)
        rejected = _to_decimal(transfer.rejected_quantity or 0)
        remaining = sent - accepted - rejected
        if remaining < 0:
            remaining = Decimal("0")

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
        "spg_id": spg_id,
        "transfers": transfers,
        "total": total,
        "limit": limit,
        "offset": offset,
    }

