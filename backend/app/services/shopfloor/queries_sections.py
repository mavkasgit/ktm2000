from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.internal_plan import SectionPlanLine
from app.models.movement import Movement, MovementType
from app.models.product import Product
from app.models.route import RouteStep
from app.models.section import Section
from app.models.transfer import Transfer, TransferStatus
from app.models.work_task import WorkTask, WorkTaskStatus

from .cache import _compute_available_from_balances
from .common import _to_decimal

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
    ).join(
        SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id,
    ).join(
        RouteStep, WorkTask.route_step_id == RouteStep.id,
    ).join(
        Product, WorkTask.product_id == Product.id,
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

    tasks_data = []
    for task, line, step, product_sku in rows:
        # Find previous route step
        prev_step = await db.scalar(
            select(RouteStep).where(
                RouteStep.route_id == line.route_id,
                RouteStep.sequence == step.sequence - 1,
            )
        )

        prev_stage_info = None
        if prev_step:
            prev_line = await db.scalar(
                select(SectionPlanLine).where(
                    SectionPlanLine.plan_position_id == line.plan_position_id,
                    SectionPlanLine.route_step_id == prev_step.id,
                )
            )
            if prev_line:
                prev_stage_info = {
                    "section_plan_line_id": prev_line.id,
                    "completed_quantity": str(prev_line.cached_completed_quantity),
                    "transferred_quantity": str(prev_line.cached_transferred_quantity),
                    "received_quantity": str(prev_line.cached_received_quantity),
                }

        next_task_id: int | None = None
        next_task_status: str | None = None
        next_operation_name: str | None = None
        next_line = await db.scalar(
            select(SectionPlanLine).where(
                SectionPlanLine.plan_position_id == line.plan_position_id,
                SectionPlanLine.sequence == line.sequence + 1,
            )
        )
        if next_line:
            next_task = await db.scalar(
                select(WorkTask)
                .where(WorkTask.section_plan_line_id == next_line.id)
                .order_by(WorkTask.id.desc())
            )
            if next_task:
                next_task_id = next_task.id
                next_task_status = next_task.status.value
            next_step = await db.get(RouteStep, next_line.route_step_id)
            if next_step:
                next_operation_name = next_step.operation_name

        available = _compute_available_from_balances(
            planned_quantity=_to_decimal(task.planned_quantity),
            received_quantity=_to_decimal(task.cached_received_quantity),
            issued_quantity=_to_decimal(task.cached_issued_quantity),
            is_first_stage=bool(line.sequence == 1),
        )

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

