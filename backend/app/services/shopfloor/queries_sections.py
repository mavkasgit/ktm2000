from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.internal_plan import SectionPlanLine
from app.models.production_plan import PlanPosition
from app.models.movement import Movement, MovementType
from app.models.product import Product
from app.models.route import RouteStage, SectionOperation
from app.models.section import Section
from app.models.transfer import Transfer, TransferStatus
from app.models.warehouse_remainder import WarehouseRemainder
from app.models.work_task import WorkTask, WorkTaskStatus

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


async def get_section_board(
    db: AsyncSession,
    *,
    section_id: int,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    status: str | None = None,
) -> dict:
    """Return the section board: tasks + previous stage progress."""
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
    )

    if status:
        query = query.where(WorkTask.status == status)
    if date_from:
        query = query.where(WorkTask.created_at >= date_from)
    if date_to:
        query = query.where(WorkTask.created_at <= date_to)

    query = query.order_by(SectionPlanLine.sequence, WorkTask.id)

    rows = (await db.execute(query)).all()

    if not rows:
        return {"section_id": section_id, "tasks": []}

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

        available = _compute_available_from_balances(
            planned_quantity=_to_decimal(task.planned_quantity),
            received_quantity=_to_decimal(task.cached_received_quantity),
            issued_quantity=_to_decimal(task.cached_issued_quantity),
            is_first_stage=bool(line.sequence == 1),
        )

        display_sku = _compute_display_sku(source_sku or "", output_sku or "")
        fingerprint = _compute_fingerprint(
            source_sku, output_sku, effective_op_code, source_payload
        )

        is_paired = source_sku and "+" in source_sku
        effective_display_sku = source_sku if is_paired else (product_sku or "")

        op_icon_info = icon_by_section_op.get((task.section_id, effective_op_code))

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
                "issued_quantity": str(task.cached_issued_quantity),
                "in_work_quantity": str(task.cached_in_work_quantity),
                "completed_quantity": str(task.cached_completed_quantity),
                "transferred_quantity": str(task.cached_transferred_quantity),
                "received_quantity": str(task.cached_received_quantity),
                "rejected_quantity": str(task.cached_rejected_quantity),
                "remaining_quantity": str(task.cached_remaining_quantity),
            },
            "previous_stage": prev_stage_info,
            "next_task_id": next_task_id,
            "next_task_status": next_task_status,
            "next_operation_name": next_operation_name,
            "source_ref": source_ref,
            "source_payload": source_payload or {},
            "source_fingerprint": fingerprint,
            "input_sku": source_sku or "",
            "output_sku": output_sku or "",
            "display_sku": effective_display_sku,
            "route_history": route_history,
            "route_history_after": route_history_after,
            "route_history_full": route_history_full,
            "route_history_after_full": route_history_after_full,
        })

    return {"section_id": section_id, "tasks": tasks_data, "available_operations": available_operations}


async def get_sections_summary(db: AsyncSession) -> dict:
    """Return section counters for quick top-level switching tiles."""
    status_counts = (
        await db.execute(
            select(
                WorkTask.section_id.label("section_id"),
                func.count(WorkTask.id).label("total_tasks"),
                func.sum(case((WorkTask.status == WorkTaskStatus.ready, 1), else_=0)).label("ready_count"),
                func.sum(
                    case(
                        (
                            WorkTask.status.in_([WorkTaskStatus.in_progress, WorkTaskStatus.partially_completed]),
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
            "ready_count": int(row.ready_count or 0),
            "in_progress_count": int(row.in_progress_count or 0),
            "waiting_count": int(row.waiting_count or 0),
            "incoming_transfers_count": 0,
        }

    for row in incoming_counts:
        entry = by_section.setdefault(
            row.section_id,
            {
                "total_tasks": 0,
                "ready_count": 0,
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
                "kind": section.kind,
                "sort_order": section.sort_order,
                "icon": section.icon,
                "icon_color": section.icon_color,
                "total_tasks": by_section.get(section.id, {}).get("total_tasks", 0),
                "ready_count": by_section.get(section.id, {}).get("ready_count", 0),
                "in_progress_count": by_section.get(section.id, {}).get("in_progress_count", 0),
                "waiting_count": by_section.get(section.id, {}).get("waiting_count", 0),
                "incoming_transfers_count": by_section.get(section.id, {}).get("incoming_transfers_count", 0),
            }
            for section in sections
        ]
    }


async def get_section_incoming_transfers(
    db: AsyncSession,
    *,
    section_id: int,
) -> dict:
    """Return incoming open transfers for a section.

    Moved to :mod:`app.transfers.queries`.  Kept here as a thin
    re-export for backward compatibility with the legacy
    ``from app.services.shopfloor.queries_sections import
    get_section_incoming_transfers`` import path.
    """
    from app.transfers.queries import get_section_incoming_transfers as _impl

    return await _impl(db, section_id=section_id)


async def get_section_daily_stats(
    db: AsyncSession,
    *,
    section_id: int,
    date_from: datetime,
    date_to: datetime,
) -> dict:
    """Return daily statistics for a section, aggregated by performed_at date."""
    from sqlalchemy import cast, Date as SQLADate

    # Aggregate by date and movement type
    rows = (
        await db.execute(
            select(
                cast(Movement.performed_at, SQLADate).label("stat_date"),
                Movement.movement_type,
                func.count(Movement.id).label("op_count"),
                func.coalesce(func.sum(Movement.quantity), 0).label("total_qty"),
                func.avg(
                    func.extract("epoch", Movement.accounted_at) - func.extract("epoch", Movement.performed_at)
                ).label("avg_delay_seconds"),
            )
            .where(
                Movement.to_section_id == section_id,
                Movement.performed_at.isnot(None),
                Movement.performed_at >= date_from,
                Movement.performed_at <= date_to,
            )
            .group_by(
                cast(Movement.performed_at, SQLADate),
                Movement.movement_type,
            )
            .order_by(cast(Movement.performed_at, SQLADate))
        )
    ).all()

    daily_map: dict[str, dict] = {}
    for stat_date, mv_type, op_count, total_qty, avg_delay in rows:
        day_key = str(stat_date)
        if day_key not in daily_map:
            daily_map[day_key] = {
                "date": day_key,
                "good_quantity": "0",
                "rejected_quantity": "0",
                "op_count": 0,
                "avg_accounting_delay_seconds": "0",
            }

        type_key = mv_type.value if hasattr(mv_type, "value") else str(mv_type)
        daily_map[day_key]["op_count"] += op_count

        if type_key == MovementType.complete.value:
            daily_map[day_key]["good_quantity"] = str(_to_decimal(total_qty))
        elif type_key in (MovementType.reject.value, MovementType.scrap.value):
            daily_map[day_key]["rejected_quantity"] = str(_to_decimal(total_qty))

        if avg_delay is not None:
            daily_map[day_key]["avg_accounting_delay_seconds"] = str(round(float(avg_delay), 1))

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
) -> dict:
    """Return active warehouse remainders (not fully consumed).

    These are surplus quantities returned to stock after task completion
    where issued > completed. Includes completed stages info for display.
    """
    query = select(
        WarehouseRemainder,
        Product.sku,
        Product.name,
        Section.code.label("section_code"),
        Section.name.label("section_name"),
        RouteStage,
    ).join(
        Product, WarehouseRemainder.product_id == Product.id,
    ).join(
        Section, WarehouseRemainder.section_id == Section.id,
    ).join(
        RouteStage, WarehouseRemainder.route_stage_id == RouteStage.id,
    ).where(
        WarehouseRemainder.consumed_at.is_(None),
        WarehouseRemainder.remainder_quantity > 0,
    )

    if section_id is not None:
        query = query.where(WarehouseRemainder.section_id == section_id)

    query = query.order_by(WarehouseRemainder.created_at.desc())

    rows = (await db.execute(query)).all()

    remainders = []
    for remainder, product_sku, product_name, section_code, section_name, stage in rows:
        op_code = stage.operations[0].operation_code if stage.operations else None
        op_name = ", ".join(op.operation_name for op in stage.operations) if stage.operations else ""
        remainders.append({
            "id": remainder.id,
            "product_id": remainder.product_id,
            "product_sku": product_sku,
            "product_name": product_name,
            "section_id": remainder.section_id,
            "section_code": section_code,
            "section_name": section_name,
            "route_step_id": remainder.route_stage_id,
            "route_step_sequence": stage.sequence,
            "operation_code": op_code,
            "operation_name": op_name,
            "section_plan_line_id": remainder.section_plan_line_id,
            "origin_task_id": remainder.origin_task_id,
            "remainder_quantity": str(remainder.remainder_quantity),
            "original_issued": str(remainder.original_issued),
            "completed_stages": remainder.completed_stages_json,
            "created_at": remainder.created_at.isoformat() if remainder.created_at else None,
        })

    return {"remainders": remainders}
