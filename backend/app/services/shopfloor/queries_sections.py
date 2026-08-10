from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, case, cast, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain.dimensions import (
    format_operation_summary,
    format_quantity,
    parse_dimensions_filter,
)
from app.models.internal_plan import SectionPlanLine
from app.models.production_plan import PlanPosition
from app.models.product import Product
from app.models.route import RouteOperation, RouteStage, SectionOperation
from app.models.section import Section
from app.models.transfer import Transfer, TransferStatus
from app.models.work_task import WorkTask, WorkTaskStatus
from app.stock.models import QualityState, Reason, StockBalance, StockTransaction

from .cache import _compute_available_from_balances
from .common import _to_decimal


def _compute_display_sku(source_sku: str, output_sku: str) -> str:
    return output_sku


def _compute_fingerprint(
    source_sku: str | None,
    output_sku: str | None,
    operation_code: str | None,
    source_payload: dict | None,
) -> str:
    payload = {
        "input_sku": source_sku or "",
        "output_sku": output_sku or "",
        "operation_code": operation_code or "",
        **(source_payload or {}),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


BOARD_SORT_FIELDS = frozenset({"sequence", "task_id", "product_sku", "status", "due_date", "dimensions"})
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


def _apply_board_sort(query, *, sort_by: str, sort_order: str):
    resolved_sort_by = sort_by if sort_by in BOARD_SORT_FIELDS else "sequence"
    if sort_order not in ("asc", "desc"):
        sort_order = "asc"

    if resolved_sort_by == "task_id":
        order_column = WorkTask.id
    elif resolved_sort_by == "product_sku":
        order_column = Product.sku
    elif resolved_sort_by == "status":
        order_column = WorkTask.status
    elif resolved_sort_by == "due_date":
        order_column = WorkTask.due_date
    elif resolved_sort_by == "dimensions":
        order_column = WorkTask.dimensions["length_mm"].as_float()
    else:
        order_column = SectionPlanLine.sequence

    nulls_last = resolved_sort_by in ("due_date", "dimensions")
    if sort_order == "asc":
        primary = order_column.asc()
        if nulls_last:
            primary = primary.nulls_last()
        return query.order_by(primary, WorkTask.id.asc())

    primary = order_column.desc()
    if nulls_last:
        primary = primary.nulls_last()
    return query.order_by(primary, WorkTask.id.desc())


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
    sort_by: str = "sequence",
    sort_order: str = "asc",
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

    query = _apply_board_sort(query, sort_by=sort_by, sort_order=sort_order)
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

    # --- Batched loading to fix N+1 ---
    route_ids: set[int] = set()
    plan_position_ids: set[int] = set()
    for row in rows:
        line = row[1]  # SectionPlanLine
        stage = row[2]  # RouteStage
        route_ids.add(stage.route_id)
        plan_position_ids.add(line.plan_position_id)

    # Load all route stages for involved routes
    all_stages = (await db.execute(
        select(RouteStage).where(RouteStage.route_id.in_(route_ids))
    )).scalars().all()
    stages_by_route: dict[int, list[RouteStage]] = {}
    for s in all_stages:
        stages_by_route.setdefault(s.route_id, []).append(s)

    # Load all SectionPlanLine for prev/next lookup
    all_lines = (await db.execute(
        select(SectionPlanLine).where(
            SectionPlanLine.plan_position_id.in_(plan_position_ids)
        )
    )).scalars().all()
    lines_by_pos_seq: dict[tuple[int, int], SectionPlanLine] = {}
    for line in all_lines:
        lines_by_pos_seq[(line.plan_position_id, line.sequence)] = line

    # Load PlanPosition for source_payload lookup
    all_positions = (await db.execute(
        select(PlanPosition).where(PlanPosition.id.in_(plan_position_ids))
    )).scalars().all()
    position_by_id: dict[int, PlanPosition] = {p.id: p for p in all_positions}

    # Load all WorkTask for next task lookup AND for previous stages operation lookup
    next_line_ids = [line.id for line in all_lines]
    all_tasks = (await db.execute(
        select(WorkTask).where(WorkTask.section_plan_line_id.in_(next_line_ids))
    )).scalars().all()
    # For each line, keep the latest task (highest id)
    tasks_by_line: dict[int, WorkTask] = {}
    for t in all_tasks:
        existing = tasks_by_line.get(t.section_plan_line_id)
        if existing is None or t.id > existing.id:
            tasks_by_line[t.section_plan_line_id] = t

    # Collect all section_ids from route stages
    all_section_ids = set()
    for s in all_stages:
        all_section_ids.add(s.section_id)
    all_section_ids.add(section_id)  # Ensure current section is included

    # Load section operations for ALL sections involved in the routes
    all_section_ops = (await db.execute(
        select(SectionOperation)
        .where(SectionOperation.section_id.in_(all_section_ids))
        .order_by(SectionOperation.operation_code)
    )).scalars().all()

    # Also load for current section dropdown
    section_ops = [op for op in all_section_ops if op.section_id == section_id]
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
        for op in section_ops
    ]

    # Build lookup: section_id -> {operation_code -> operation_name} for ALL sections
    op_name_by_section: dict[int, dict[str, str]] = {}
    for op in all_section_ops:
        op_name_by_section.setdefault(op.section_id, {})[op.operation_code] = op.operation_name

    # Build lookup: (section_id, operation_code) -> {icon, icon_color} for ALL sections
    icon_by_section_op: dict[tuple[int, str], dict] = {}
    for op in all_section_ops:
        if op.icon or op.icon_color:
            icon_by_section_op[(op.section_id, op.operation_code)] = {
                "icon": op.icon,
                "icon_color": op.icon_color,
            }

    # Load tasks cache (Этап 4: вычисляем из StockTransaction ledger)
    from app.stock.services import StockProjectionManager
    pm = StockProjectionManager()
    all_task_ids = [row[0].id for row in rows]
    tasks_cache = await pm.get_tasks_cache_bulk(db, all_task_ids)

    # Прогресс трансформации (ADR-0002) для карточек трансформирующих
    # этапов: списано входа и оприходовано по каждому выходу.
    from .operations_transform import (
        build_outputs_progress,
        distribute_output_quantities,
        get_transferred_by_task_dimensions_bulk,
        get_transform_progress_bulk,
    )
    transform_task_ids = [
        row[0].id for row in rows
        if row[2].transforms_dimensions and (row[0].outputs or [])
    ]
    transform_progress_map = await get_transform_progress_bulk(db, transform_task_ids)

    # Нетто-переданное по каждому габариту трансформирующих заданий —
    # для учётной колонки «Передано» строки «Сдачи» плана (тикет #95).
    transferred_by_task = await get_transferred_by_task_dimensions_bulk(
        db, transform_task_ids,
    )

    from .task_status import sync_work_tasks_status_bulk

    board_tasks = [row[0] for row in rows]
    await sync_work_tasks_status_bulk(db, tasks=board_tasks, tasks_cache=tasks_cache)

    tasks_data = []
    for task, line, stage, product_sku, source_ref, source_payload, source_fingerprint, source_sku, output_sku in rows:
        # Determine effective operation_code.
        effective_op_code = task.selected_operation_code
        if not effective_op_code:
            src_op = (source_payload or {}).get("operation_code")
            if src_op and src_op in op_name_by_section.get(task.section_id, {}):
                effective_op_code = src_op
            else:
                effective_op_code = stage.operations[0].operation_code if stage.operations else None

        stage_primary_op_name = stage.operations[0].operation_name if stage.operations else ""
        effective_op_name = op_name_by_section.get(task.section_id, {}).get(effective_op_code) or stage_primary_op_name
        effective_is_significant = False
        for op in all_section_ops:
            if op.section_id == task.section_id and op.operation_code == effective_op_code:
                effective_is_significant = op.is_significant
                break

        route_stages = stages_by_route.get(line.route_id, [])

        route_history = []
        route_history_full = []
        for s in route_stages:
            if s.sequence < stage.sequence:
                prev_line = lines_by_pos_seq.get((line.plan_position_id, s.sequence))
                prev_work_task = tasks_by_line.get(prev_line.id) if prev_line else None

                if prev_work_task:
                    prev_position = position_by_id.get(prev_line.plan_position_id) if prev_line else None
                    prev_source_payload = (prev_position.source_payload or {}) if prev_position else {}

                    prev_eff_op_code = prev_work_task.selected_operation_code
                    if not prev_eff_op_code:
                        prev_src_op = prev_source_payload.get("operation_code")
                        if prev_src_op and prev_src_op in op_name_by_section.get(prev_work_task.section_id, {}):
                            prev_eff_op_code = prev_src_op
                        else:
                            prev_eff_op_code = s.operations[0].operation_code if s.operations else None

                    prev_primary_op_name = s.operations[0].operation_name if s.operations else ""
                    prev_op_name = op_name_by_section.get(s.section_id, {}).get(prev_eff_op_code) or prev_primary_op_name

                    prev_is_significant = False
                    for op in all_section_ops:
                        if op.section_id == s.section_id and op.operation_code == prev_eff_op_code:
                            prev_is_significant = op.is_significant
                            break

                    prev_icon = icon_by_section_op.get((s.section_id, prev_eff_op_code))
                else:
                    prev_eff_op_code = s.operations[0].operation_code if s.operations else None
                    prev_op_name = s.operations[0].operation_name if s.operations else ""
                    prev_is_significant = False
                    for op in all_section_ops:
                        if op.section_id == s.section_id and op.operation_code == (prev_eff_op_code or ""):
                            prev_is_significant = op.is_significant
                            break
                    prev_icon = icon_by_section_op.get((s.section_id, prev_eff_op_code))

                op_obj = {
                    "operation_code": prev_eff_op_code or "",
                    "operation_name": prev_op_name,
                    "is_significant": prev_is_significant,
                    "icon": prev_icon["icon"] if prev_icon else None,
                    "icon_color": prev_icon["icon_color"] if prev_icon else None,
                }
                route_history_full.append(op_obj)
                if prev_is_significant:
                    route_history.append(op_obj)

        if stage.operations and stage.operations[0].operation_code:
            after_op_code = stage.operations[0].operation_code
            after_op_name = stage.operations[0].operation_name
            after_is_significant = effective_is_significant
            after_icon = icon_by_section_op.get((task.section_id, stage.operations[0].operation_code))
        else:
            after_op_code = effective_op_code or ""
            after_op_name = effective_op_name
            after_is_significant = effective_is_significant
            after_icon = icon_by_section_op.get((task.section_id, effective_op_code))

        current_op_obj = {
            "operation_code": after_op_code,
            "operation_name": after_op_name,
            "is_significant": after_is_significant,
            "icon": after_icon["icon"] if after_icon else None,
            "icon_color": after_icon["icon_color"] if after_icon else None,
        }
        route_history_after = route_history + [current_op_obj] if current_op_obj["operation_code"] else route_history
        route_history_after_full = route_history_full + [current_op_obj] if current_op_obj["operation_code"] else route_history_full
        prev_stage = next((s for s in route_stages if s.sequence == stage.sequence - 1), None)

        prev_stage_info = None
        if prev_stage:
            prev_line = lines_by_pos_seq.get((line.plan_position_id, prev_stage.sequence))
            if prev_line:
                prev_stage_info = {
                    "section_plan_line_id": prev_line.id,
                    "completed_quantity": str(prev_line.cached_completed_quantity),
                    "transferred_quantity": str(prev_line.cached_transferred_quantity),
                    "received_quantity": str(prev_line.cached_received_quantity),
                }

        # Next line — dict lookup
        next_line = lines_by_pos_seq.get((line.plan_position_id, stage.sequence + 1))
        next_task_id: int | None = None
        next_task_status: str | None = None
        next_operation_name: str | None = None
        if next_line:
            next_task = tasks_by_line.get(next_line.id)
            if next_task:
                next_task_id = next_task.id
                next_task_status = next_task.status.value
            next_route_stages = stages_by_route.get(next_line.route_id, [])
            next_stage = next((s for s in next_route_stages if s.id == next_line.route_stage_id), None)
            if next_stage:
                next_operation_name = ", ".join(op.operation_name for op in next_stage.operations) if next_stage.operations else ""

        task_cache = tasks_cache.get(task.id, {})
        available = _compute_available_from_balances(
            planned_quantity=_to_decimal(task.planned_quantity),
            received_quantity=task_cache.get("received_quantity", Decimal("0")),
            issued_quantity=task_cache.get("issued_quantity", Decimal("0")),
            returned_quantity=task_cache.get("returned_quantity", Decimal("0"))
            if "returned_quantity" in task_cache
            else Decimal("0"),
            is_first_stage=bool(line.sequence == 1),
        )

        display_sku = _compute_display_sku(source_sku or "", output_sku or "")
        fingerprint = _compute_fingerprint(
            source_sku, output_sku, effective_op_code, source_payload
        )

        is_paired = source_sku and "+" in source_sku
        effective_display_sku = source_sku if is_paired else (product_sku or "")

        op_icon_info = icon_by_section_op.get((task.section_id, effective_op_code))

        # Determine all operations for the task/stage
        operation_codes = []
        operation_names = []

        if stage.operations:
            for op in stage.operations:
                op_code = op.operation_code
                if not op_code:
                    op_code = effective_op_code
                op_name = op_name_by_section.get(task.section_id, {}).get(op_code) or op.operation_name
                operation_codes.append(op_code)
                operation_names.append(op_name)

        # Трансформирующий этап (ADR-0002): одна позиция плана = одна
        # карточка «вход → все выходы»: «150 шт × 2,7 м → 150 × 0,9 м + …».
        task_outputs = list(task.outputs or [])
        operation_summary = (
            format_operation_summary(task.input_quantity, task.input_dimensions, task_outputs)
            if stage.transforms_dimensions
            else None
        )

        # Прогресс по каждому выходу и списанный вход для UI пилы.
        outputs_progress = None
        input_consumed_quantity = None
        if task.id in transform_progress_map or (stage.transforms_dimensions and task_outputs):
            progress = transform_progress_map.get(task.id)
            produced_by_group = progress.produced_by_group if progress else {}
            produced_entries = build_outputs_progress(task_outputs, produced_by_group)
            transferred_rows = distribute_output_quantities(
                task_outputs,
                transferred_by_task.get(task.id) or {},
            )
            outputs_progress = [
                {
                    "row_number": entry["row_number"],
                    "dimensions": entry["dimensions"],
                    "quantity": format_quantity(entry["quantity"]),
                    "produced_quantity": format_quantity(entry["produced_quantity"]),
                    # Нетто-переданное по (задача, размер выхода) из ledger —
                    # учётная колонка «Передано» строки «Сдачи» плана.
                    "transferred_quantity": format_quantity(transferred),
                }
                for entry, transferred in zip(produced_entries, transferred_rows)
            ]
            input_consumed_quantity = format_quantity(
                progress.consumed_quantity if progress else Decimal("0")
            )

        tasks_data.append({
            "id": task.id,
            "section_id": task.section_id,
            "product_id": task.product_id,
            "product_sku": effective_display_sku,
            "section_plan_line_id": line.id,
            "plan_position_id": line.plan_position_id,
            "route_step_id": stage.id,
            "sequence": stage.sequence,
            "operation_code": effective_op_code,
            "operation_name": effective_op_name,
            "is_significant": effective_is_significant,
            "icon": op_icon_info["icon"] if op_icon_info else None,
            "icon_color": op_icon_info["icon_color"] if op_icon_info else None,
            "planned_quantity": str(task.planned_quantity),
            "status": task.status.value,
            "cache": {
                "available_quantity": str(available),
                "issued_quantity": str(task_cache.get("issued_quantity", "0")),
                "completed_quantity": str(task_cache.get("completed_quantity", "0")),
                "transferred_quantity": str(task_cache.get("transferred_quantity", "0")),
                "received_quantity": str(task_cache.get("received_quantity", "0")),
                "rejected_quantity": str(task_cache.get("rejected_quantity", "0")),
                "remaining_quantity": str(task_cache.get("remaining_quantity", "0")),
            },
            "previous_stage": prev_stage_info,
            "next_task_id": next_task_id,
            "next_task_status": next_task_status,
            "next_operation_name": next_operation_name,
            "source_ref": source_ref,
            "source_payload": source_payload or {},
            "source_fingerprint": fingerprint,
            # Размер задания (ADR-0001): габарит материала на этом этапе.
            # У трансформирующих этапов вход/выходы уже несут input_dimensions
            # и outputs — здесь только «размер» нетрансформирующего этапа.
            "dimensions": task.dimensions,
            "input_sku": source_sku or "",
            "output_sku": output_sku or "",
            "display_sku": effective_display_sku,
            "route_history": route_history,
            "route_history_after": route_history_after,
            "route_history_full": route_history_full,
            "route_history_after_full": route_history_after_full,
            "operation_codes": operation_codes,
            "operation_names": operation_names,
            # —— трансформация габаритов (ADR-0002) ——
            "transforms_dimensions": stage.transforms_dimensions,
            "input_quantity": format_quantity(task.input_quantity) if task.input_quantity is not None else None,
            "input_dimensions": task.input_dimensions,
            "outputs": task_outputs,
            "operation_summary": operation_summary,
            "outputs_progress": outputs_progress,
            "input_consumed_quantity": input_consumed_quantity,
        })

    return {
        "section_id": section_id,
        "tasks": tasks_data,
        "available_operations": available_operations,
        "total": total,
        "limit": limit,
        "offset": offset,
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
                WorkTask.status.notin_([WorkTaskStatus.cancelled, WorkTaskStatus.completed]),
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
                WorkTask.status == WorkTaskStatus.completed,
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
            select(Section).where(Section.is_active == True).order_by(Section.sort_order, Section.id)
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
    """Return daily statistics for a section, aggregated by created_at date."""
    from sqlalchemy import cast, Date as SQLADate

    # Aggregate by date and reason type from StockTransaction
    rows = (
        await db.execute(
            select(
                cast(StockTransaction.created_at, SQLADate).label("stat_date"),
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
                cast(StockTransaction.created_at, SQLADate),
                StockTransaction.reason,
            )
            .order_by(cast(StockTransaction.created_at, SQLADate))
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
        elif reason_val in (Reason.SCRAP.value,):
            daily_map[day_key]["rejected_quantity"] = str(_to_decimal(total_qty))

    return {"section_id": section_id, "daily_stats": list(daily_map.values())}


async def get_section_payload_keys(
    db: AsyncSession,
    *,
    section_id: int,
) -> dict:
    """
    Возвращает список уникальных ключей из source_payload для всех задач участка.

    Используется в GroupingSettingsModal для показа чекбоксов кастомных полей.

    ПОЧЕМУ ОТДЕЛЬНЫЙ ЗАПРОС, А НЕ ЧАСТЬ get_section_board:
      Этот запрос нужен только при открытии модалки настроек (~1 раз в сессию),
      а не при каждой загрузке доски. Разделение снижает объём данных в основном запросе.

    PostgreSQL jsonb_object_keys() — встроенная функция для извлечения ключей JSONB.
    """
    stmt = (
        select(
            func.jsonb_object_keys(PlanPosition.source_payload).label("key")
        )
        .join(SectionPlanLine, SectionPlanLine.plan_position_id == PlanPosition.id)
        .where(SectionPlanLine.section_id == section_id)
        .distinct()
        .order_by(func.jsonb_object_keys(PlanPosition.source_payload))
    )

    rows = (await db.execute(stmt)).scalars().all()
    return {"keys": list(rows)}


async def get_warehouse_remainders(
    db: AsyncSession,
    *,
    section_id: int | None = None,
    plan_position_id: int | None = None,
) -> dict:
    """Return available stock balances for a section (legacy API stub).

    Now backed by StockBalance instead of SpgRemainder.
    """
    from app.stock.models import QualityState, StockBalance

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
        })

    return {"remainders": remainders}

