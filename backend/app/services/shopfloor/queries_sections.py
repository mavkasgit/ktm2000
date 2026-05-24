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
from app.models.route import RouteStep, SectionOperation
from app.models.section import Section
from app.models.transfer import Transfer, TransferStatus
from app.models.work_task import WorkTask, WorkTaskStatus

from .cache import _compute_available_from_balances
from .common import _to_decimal


def _compute_display_sku(source_sku: str, output_sku: str) -> str:
    return f"{source_sku} \u2192 {output_sku}" if source_sku != output_sku else output_sku


def _compute_fingerprint(
    source_sku: str | None,
    output_sku: str | None,
    operation_code: str | None,
    output_kind: str | None,
    source_payload: dict | None,
) -> str:
    payload = {
        "input_sku": source_sku or "",
        "output_sku": output_sku or "",
        "operation_code": operation_code or "",
        "output_kind": output_kind or "",
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
        RouteStep,
        Product.sku,
        PlanPosition.source_ref,
        PlanPosition.source_payload,
        PlanPosition.source_fingerprint,
        PlanPosition.source_sku,
        PlanPosition.output_sku,
        PlanPosition.output_kind,
        SectionOperation.is_significant.label("op_is_significant"),
        SectionOperation.operation_name.label("op_operation_name"),
    ).join(
        SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id,
    ).join(
        RouteStep, WorkTask.route_step_id == RouteStep.id,
    ).join(
        Product, WorkTask.product_id == Product.id,
    ).join(
        PlanPosition, SectionPlanLine.plan_position_id == PlanPosition.id,
    ).outerjoin(
        SectionOperation,
        SectionOperation.section_id == WorkTask.section_id,
    ).where(
        WorkTask.section_id == section_id,
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
        step = row[2]  # RouteStep
        route_ids.add(step.route_id)
        plan_position_ids.add(line.plan_position_id)

    # Load all route steps for involved routes
    all_steps = (await db.execute(
        select(RouteStep).where(RouteStep.route_id.in_(route_ids))
    )).scalars().all()
    steps_by_route: dict[int, list[RouteStep]] = {}
    for s in all_steps:
        steps_by_route.setdefault(s.route_id, []).append(s)

    # Load all SectionPlanLine for prev/next lookup
    all_lines = (await db.execute(
        select(SectionPlanLine).where(
            SectionPlanLine.plan_position_id.in_(plan_position_ids)
        )
    )).scalars().all()
    lines_by_pos_seq: dict[tuple[int, int], SectionPlanLine] = {}
    for line in all_lines:
        lines_by_pos_seq[(line.plan_position_id, line.sequence)] = line

    # Load all WorkTask for next task lookup
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

    tasks_data = []
    for task, line, step, product_sku, source_ref, source_payload, source_fingerprint, source_sku, output_sku, output_kind in rows:
        # Prev step — dict lookup
        route_steps = steps_by_route.get(line.route_id, [])
        prev_step = next((s for s in route_steps if s.sequence == step.sequence - 1), None)

        prev_stage_info = None
        if prev_step:
            prev_line = lines_by_pos_seq.get((line.plan_position_id, prev_step.sequence))
            if prev_line:
                prev_stage_info = {
                    "section_plan_line_id": prev_line.id,
                    "completed_quantity": str(prev_line.cached_completed_quantity),
                    "transferred_quantity": str(prev_line.cached_transferred_quantity),
                    "received_quantity": str(prev_line.cached_received_quantity),
                }

        # Next line — dict lookup
        next_line = lines_by_pos_seq.get((line.plan_position_id, step.sequence + 1))
        next_task_id: int | None = None
        next_task_status: str | None = None
        next_operation_name: str | None = None
        if next_line:
            next_task = tasks_by_line.get(next_line.id)
            if next_task:
                next_task_id = next_task.id
                next_task_status = next_task.status.value
            # Next step from already-loaded steps
            next_route_steps = steps_by_route.get(next_line.route_id, [])
            next_step = next((s for s in next_route_steps if s.id == next_line.route_step_id), None)
            if next_step:
                next_operation_name = next_step.operation_name

        available = _compute_available_from_balances(
            planned_quantity=_to_decimal(task.planned_quantity),
            received_quantity=_to_decimal(task.cached_received_quantity),
            issued_quantity=_to_decimal(task.cached_issued_quantity),
            is_first_stage=bool(line.sequence == 1),
        )

        display_sku = _compute_display_sku(source_sku or "", output_sku or "")
        fingerprint = _compute_fingerprint(
            source_sku, output_sku, step.operation_code, output_kind, source_payload
        )
        sig_output_kind_value = output_kind.value if hasattr(output_kind, "value") else output_kind

        tasks_data.append({
            "id": task.id,
            "product_id": task.product_id,
            "product_sku": product_sku,
            "section_plan_line_id": line.id,
            "plan_position_id": line.plan_position_id,
            "route_step_id": step.id,
            "sequence": step.sequence,
            "operation_code": step.operation_code,
            "operation_name": step.operation_name,
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
            # --- новые поля ---
            "input_sku": source_sku or "",
            "output_sku": output_sku or "",
            "display_sku": display_sku,
            "signature": {
                "input_sku": source_sku or "",
                "output_sku": output_sku or "",
                "display_sku": display_sku,
                "operation_code": step.operation_code,
                "operation_name": row.op_operation_name or step.operation_name,
                "is_significant": row.op_is_significant if row.op_is_significant is not None else step.is_significant,
                "output_kind": sig_output_kind_value,
                "source_ref": source_ref,
                "source_payload": source_payload or {},
                "source_fingerprint": fingerprint,
            },
        })

    return {"section_id": section_id, "tasks": tasks_data}


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
    """Return incoming open transfers for a section."""
    from_section = aliased(Section)
    to_section = aliased(Section)
    from_task = aliased(WorkTask)
    to_task = aliased(WorkTask)
    from_step = aliased(RouteStep)
    to_step = aliased(RouteStep)
    from_line = aliased(SectionPlanLine)

    rows = (
        await db.execute(
            select(
                Transfer,
                from_section,
                to_section,
                from_task,
                to_task,
                from_step,
                to_step,
                from_line,
                Product.sku,
            )
            .join(from_section, from_section.id == Transfer.from_section_id)
            .join(to_section, to_section.id == Transfer.to_section_id)
            .join(from_task, from_task.id == Transfer.from_task_id)
            .join(to_task, to_task.id == Transfer.to_task_id)
            .join(from_step, from_step.id == from_task.route_step_id)
            .join(to_step, to_step.id == to_task.route_step_id)
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
    for transfer, from_sec, to_sec, src_task, dst_task, src_step, dst_step, src_line, product_sku in rows:
        sent = _to_decimal(transfer.sent_quantity or 0)
        accepted = _to_decimal(transfer.accepted_quantity or 0)
        rejected = _to_decimal(transfer.rejected_quantity or 0)
        remaining = sent - accepted - rejected
        if remaining < 0:
            remaining = Decimal("0")

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
                "from_operation_name": src_step.operation_name,
                "to_operation_name": dst_step.operation_name,
                "sent_quantity": str(sent),
                "accepted_quantity": str(accepted),
                "rejected_quantity": str(rejected),
                "remaining_quantity": str(remaining),
                "comment": transfer.comment,
                "sent_at": transfer.sent_at.isoformat() if transfer.sent_at else None,
                "created_at": transfer.created_at.isoformat() if transfer.created_at else None,
                "from_task_status": src_task.status.value,
                "to_task_status": dst_task.status.value,
                "product_sku": product_sku,
                "from_line_id": src_line.id,
                "from_line_sequence": src_line.sequence,
                "plan_position_id": src_line.plan_position_id,
            }
        )

    return {
        "section_id": section_id,
        "incoming_transfers": transfers,
    }


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
