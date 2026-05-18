from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_plan import SectionPlanLine
from app.models.movement import Movement, MovementType
from app.models.production_plan import PlanPosition, PlanPositionStatus
from app.models.route import RouteStep
from app.models.section import Section
from app.models.transfer import Transfer
from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.route_matcher import ResolvedRouteInfo, resolve_position_route


def _to_float(value: Decimal | int | float | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _clamp_percent(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    value = (numerator / denominator) * 100.0
    return round(max(0.0, min(100.0, value)), 1)


def _summarize_task_status(statuses: list[str]) -> str:
    if not statuses:
        return "not_started"
    status_set = set(statuses)
    if status_set == {"completed"}:
        return "completed"
    if "in_progress" in status_set:
        return "in_progress"
    if "ready" in status_set:
        return "ready"
    if "waiting_previous" in status_set:
        return "waiting_previous"
    if status_set == {"cancelled"}:
        return "cancelled"
    return statuses[0]


def _resolved_route_error(route_info: ResolvedRouteInfo) -> str | None:
    if route_info.error:
        return route_info.error
    if route_info.route_id is None:
        return "route_not_found"
    return None


def _event_at_iso(*, performed_at, accounted_at, created_at) -> str | None:
    event_at = performed_at or accounted_at or created_at
    return event_at.isoformat() if event_at else None


async def list_production_planning_rows(db: AsyncSession) -> list[dict]:
    positions = (
        await db.execute(
            select(PlanPosition)
            .where(PlanPosition.status.in_([PlanPositionStatus.approved, PlanPositionStatus.released]))
            .where(PlanPosition.deleted_at.is_(None))
            .order_by(PlanPosition.production_plan_id.desc(), PlanPosition.source_row_number, PlanPosition.id)
        )
    ).scalars().all()
    if not positions:
        return []

    position_ids = [pos.id for pos in positions]
    has_tasks_rows = (
        await db.execute(
            select(SectionPlanLine.plan_position_id)
            .where(SectionPlanLine.plan_position_id.in_(position_ids))
            .group_by(SectionPlanLine.plan_position_id)
        )
    ).all()
    has_tasks_set = {row[0] for row in has_tasks_rows}

    # Fetch current stage info: first in_progress or ready task per position
    current_stage_rows = (
        await db.execute(
            select(
                SectionPlanLine.plan_position_id,
                RouteStep.section_id,
                RouteStep.sequence,
                RouteStep.operation_name,
                Section.code.label("section_code"),
                Section.name.label("section_name"),
                WorkTask.status.label("task_status"),
            )
            .join(RouteStep, RouteStep.id == SectionPlanLine.route_step_id)
            .join(Section, Section.id == RouteStep.section_id)
            .join(WorkTask, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id.in_(position_ids))
            .where(WorkTask.status.in_([WorkTaskStatus.in_progress, WorkTaskStatus.ready]))
            .order_by(
                SectionPlanLine.plan_position_id,
                WorkTask.status.desc(),  # in_progress before ready
                RouteStep.sequence,
            )
        )
    ).all()

    # Fallback: get first task stage for positions without in_progress/ready
    positions_without_active = [pid for pid in position_ids if pid not in {r.plan_position_id for r in current_stage_rows}]
    fallback_rows = []
    if positions_without_active:
        fallback_rows = (
            await db.execute(
                select(
                    SectionPlanLine.plan_position_id,
                    RouteStep.section_id,
                    RouteStep.sequence,
                    RouteStep.operation_name,
                    Section.code.label("section_code"),
                    Section.name.label("section_name"),
                    WorkTask.status.label("task_status"),
                )
                .join(RouteStep, RouteStep.id == SectionPlanLine.route_step_id)
                .join(Section, Section.id == RouteStep.section_id)
                .join(WorkTask, WorkTask.section_plan_line_id == SectionPlanLine.id)
                .where(SectionPlanLine.plan_position_id.in_(positions_without_active))
                .order_by(
                    SectionPlanLine.plan_position_id,
                    RouteStep.sequence,
                )
            )
        ).all()

    current_stage_by_position: dict[int, dict] = {}
    for row in current_stage_rows:
        if row.plan_position_id not in current_stage_by_position:
            current_stage_by_position[row.plan_position_id] = {
                "current_stage_section_id": row.section_id,
                "current_stage_sequence": row.sequence,
                "current_stage_operation": row.operation_name,
                "current_stage_section_code": row.section_code,
                "current_stage_section_name": row.section_name,
                "current_stage_task_status": row.task_status.value if hasattr(row.task_status, "value") else str(row.task_status),
            }
    for row in fallback_rows:
        if row.plan_position_id not in current_stage_by_position:
            current_stage_by_position[row.plan_position_id] = {
                "current_stage_section_id": row.section_id,
                "current_stage_sequence": row.sequence,
                "current_stage_operation": row.operation_name,
                "current_stage_section_code": row.section_code,
                "current_stage_section_name": row.section_name,
                "current_stage_task_status": row.task_status.value if hasattr(row.task_status, "value") else str(row.task_status),
            }

    route_cache: dict[int, ResolvedRouteInfo] = {}

    result: list[dict] = []
    for pos in positions:
        if pos.id not in route_cache:
            route_cache[pos.id] = await resolve_position_route(db, pos)
        route_info = route_cache[pos.id]

        has_tasks = pos.id in has_tasks_set
        stage_info = current_stage_by_position.get(pos.id, {})
        result.append(
            {
                "plan_position_id": pos.id,
                "production_plan_id": pos.production_plan_id,
                "source_row_number": pos.source_row_number,
                "source_sku": pos.source_sku,
                "source_name": pos.source_name,
                "quantity": _to_float(pos.quantity),
                "position_status": pos.status.value if hasattr(pos.status, "value") else str(pos.status),
                "validation_status": pos.validation_status.value
                if hasattr(pos.validation_status, "value")
                else str(pos.validation_status),
                "route_id": route_info.route_id,
                "route_name": route_info.route_name,
                "route_source": route_info.source,
                "route_origin": route_info.route_origin,
                "route_match_quality": route_info.route_match_quality,
                "route_match_reason": route_info.route_match_reason,
                "route_assigned_at": route_info.route_assigned_at.isoformat() if route_info.route_assigned_at else None,
                "route_manual_confirmed_at": (
                    route_info.route_manual_confirmed_at.isoformat() if route_info.route_manual_confirmed_at else None
                ),
                "route_error": _resolved_route_error(route_info),
                "is_released": bool(has_tasks or pos.status == PlanPositionStatus.released),
                "has_tasks": has_tasks,
                "current_stage_section_id": stage_info.get("current_stage_section_id"),
                "current_stage_sequence": stage_info.get("current_stage_sequence"),
                "current_stage_operation": stage_info.get("current_stage_operation"),
                "current_stage_section_code": stage_info.get("current_stage_section_code"),
                "current_stage_section_name": stage_info.get("current_stage_section_name"),
                "current_stage_task_status": stage_info.get("current_stage_task_status"),
            }
        )

    return result


async def get_production_planning_row_detail(db: AsyncSession, position_id: int) -> dict | None:
    pos = await db.get(PlanPosition, position_id)
    if pos is None or pos.deleted_at is not None:
        return None

    route_info = await resolve_position_route(db, pos)

    has_tasks = bool(
        await db.scalar(select(func.count(SectionPlanLine.id)).where(SectionPlanLine.plan_position_id == pos.id))
    )

    steps_data: list[dict] = []
    route_snapshot: dict | None = None

    if route_info.route_id is not None:
        steps = (
            await db.execute(
                select(RouteStep, Section)
                .join(Section, RouteStep.section_id == Section.id)
                .where(RouteStep.route_id == route_info.route_id)
                .order_by(RouteStep.sequence)
            )
        ).all()

        planned_by_step = {
            row.route_step_id: _to_float(row.planned_quantity)
            for row in (
                await db.execute(
                    select(
                        SectionPlanLine.route_step_id.label("route_step_id"),
                        func.coalesce(func.sum(SectionPlanLine.planned_quantity), 0).label("planned_quantity"),
                    )
                    .where(SectionPlanLine.plan_position_id == pos.id)
                    .group_by(SectionPlanLine.route_step_id)
                )
            ).all()
        }

        task_aggregates_by_step: dict[int, dict[str, float]] = {}
        task_statuses_by_step: dict[int, list[str]] = {}
        task_aggregates = (
            await db.execute(
                select(
                    SectionPlanLine.route_step_id.label("route_step_id"),
                    func.coalesce(func.sum(WorkTask.cached_completed_quantity), 0).label("completed_quantity"),
                    func.coalesce(func.sum(WorkTask.cached_transferred_quantity), 0).label("transferred_quantity"),
                    func.coalesce(func.sum(WorkTask.cached_rejected_quantity), 0).label("rejected_quantity"),
                    WorkTask.status.label("task_status"),
                )
                .join(SectionPlanLine, SectionPlanLine.id == WorkTask.section_plan_line_id)
                .where(SectionPlanLine.plan_position_id == pos.id)
                .group_by(SectionPlanLine.route_step_id, WorkTask.status)
            )
        ).all()

        for row in task_aggregates:
            step_id = row.route_step_id
            step_totals = task_aggregates_by_step.setdefault(
                step_id,
                {"completed_quantity": 0.0, "transferred_quantity": 0.0, "rejected_quantity": 0.0},
            )
            step_totals["completed_quantity"] += _to_float(row.completed_quantity)
            step_totals["transferred_quantity"] += _to_float(row.transferred_quantity)
            step_totals["rejected_quantity"] += _to_float(row.rejected_quantity)
            task_statuses_by_step.setdefault(step_id, []).append(
                row.task_status.value if hasattr(row.task_status, "value") else str(row.task_status)
            )

        flow_by_step: dict[int, dict] = {}
        movement_rows = (
            await db.execute(
                select(
                    SectionPlanLine.route_step_id.label("route_step_id"),
                    Movement.id.label("movement_id"),
                    Movement.task_id.label("task_id"),
                    Movement.transfer_id.label("transfer_id"),
                    Movement.movement_type.label("movement_type"),
                    Movement.quantity.label("quantity"),
                    Movement.performed_at.label("performed_at"),
                    Movement.accounted_at.label("accounted_at"),
                    Movement.created_at.label("created_at"),
                )
                .join(SectionPlanLine, SectionPlanLine.id == Movement.section_plan_line_id)
                .where(SectionPlanLine.plan_position_id == pos.id)
                .order_by(Movement.created_at, Movement.id)
            )
        ).all()

        for row in movement_rows:
            step_id = row.route_step_id
            movement_type = row.movement_type
            movement_type_value = movement_type.value if hasattr(movement_type, "value") else str(movement_type)
            quantity = _to_float(row.quantity)
            event_sort_dt = row.performed_at or row.accounted_at or row.created_at
            event_at_iso = _event_at_iso(
                performed_at=row.performed_at,
                accounted_at=row.accounted_at,
                created_at=row.created_at,
            )
            entry = flow_by_step.setdefault(
                step_id,
                {
                    "issued_qty": 0.0,
                    "issued_last_at": None,
                    "issued_last_dt": None,
                    "accounted_good_qty": 0.0,
                    "accounted_reject_qty": 0.0,
                    "accounted_total_qty": 0.0,
                    "accounted_last_at": None,
                    "accounted_last_dt": None,
                    "sent_qty": 0.0,
                    "sent_last_at": None,
                    "sent_last_dt": None,
                    "accepted_by_next_qty": 0.0,
                    "accepted_by_next_last_at": None,
                    "accepted_by_next_last_dt": None,
                    "flow_events": [],
                },
            )

            if movement_type_value == MovementType.issue_to_work.value:
                entry["issued_qty"] += quantity
                if entry["issued_last_dt"] is None or (event_sort_dt and event_sort_dt >= entry["issued_last_dt"]):
                    entry["issued_last_dt"] = event_sort_dt
                    entry["issued_last_at"] = event_at_iso
                entry["flow_events"].append(
                    {
                        "step": "issue",
                        "label": "Выдано в работу",
                        "quantity": round(quantity, 3),
                        "event_at": event_at_iso,
                        "task_id": row.task_id,
                        "transfer_id": row.transfer_id,
                        "_sort_dt": event_sort_dt,
                        "_sort_id": row.movement_id,
                    }
                )
            elif movement_type_value == MovementType.complete.value:
                entry["accounted_good_qty"] += quantity
                entry["accounted_total_qty"] += quantity
                if entry["accounted_last_dt"] is None or (event_sort_dt and event_sort_dt >= entry["accounted_last_dt"]):
                    entry["accounted_last_dt"] = event_sort_dt
                    entry["accounted_last_at"] = event_at_iso
                entry["flow_events"].append(
                    {
                        "step": "account",
                        "label": "Учтено (годное)",
                        "quantity": round(quantity, 3),
                        "event_at": event_at_iso,
                        "task_id": row.task_id,
                        "transfer_id": row.transfer_id,
                        "_sort_dt": event_sort_dt,
                        "_sort_id": row.movement_id,
                    }
                )
            elif movement_type_value == MovementType.reject.value:
                entry["accounted_reject_qty"] += quantity
                entry["accounted_total_qty"] += quantity
                if entry["accounted_last_dt"] is None or (event_sort_dt and event_sort_dt >= entry["accounted_last_dt"]):
                    entry["accounted_last_dt"] = event_sort_dt
                    entry["accounted_last_at"] = event_at_iso
                entry["flow_events"].append(
                    {
                        "step": "account",
                        "label": "Учтено (брак)",
                        "quantity": round(quantity, 3),
                        "event_at": event_at_iso,
                        "task_id": row.task_id,
                        "transfer_id": row.transfer_id,
                        "_sort_dt": event_sort_dt,
                        "_sort_id": row.movement_id,
                    }
                )
            elif movement_type_value == MovementType.transfer_send.value:
                entry["sent_qty"] += quantity
                if entry["sent_last_dt"] is None or (event_sort_dt and event_sort_dt >= entry["sent_last_dt"]):
                    entry["sent_last_dt"] = event_sort_dt
                    entry["sent_last_at"] = event_at_iso
                entry["flow_events"].append(
                    {
                        "step": "send",
                        "label": "Передано",
                        "quantity": round(quantity, 3),
                        "event_at": event_at_iso,
                        "task_id": row.task_id,
                        "transfer_id": row.transfer_id,
                        "_sort_dt": event_sort_dt,
                        "_sort_id": row.movement_id,
                    }
                )

        transfer_accept_rows = (
            await db.execute(
                select(
                    SectionPlanLine.route_step_id.label("route_step_id"),
                    Transfer.id.label("transfer_id"),
                    Transfer.from_task_id.label("from_task_id"),
                    Transfer.accepted_quantity.label("accepted_quantity"),
                    Transfer.accepted_at.label("accepted_at"),
                    Transfer.created_at.label("created_at"),
                )
                .join(WorkTask, WorkTask.id == Transfer.from_task_id)
                .join(SectionPlanLine, SectionPlanLine.id == WorkTask.section_plan_line_id)
                .where(SectionPlanLine.plan_position_id == pos.id)
                .order_by(Transfer.created_at, Transfer.id)
            )
        ).all()

        for row in transfer_accept_rows:
            step_id = row.route_step_id
            accepted_qty = _to_float(row.accepted_quantity)
            if accepted_qty <= 0:
                continue
            event_at = row.accepted_at or row.created_at
            event_at_iso = event_at.isoformat() if event_at else None
            entry = flow_by_step.setdefault(
                step_id,
                {
                    "issued_qty": 0.0,
                    "issued_last_at": None,
                    "issued_last_dt": None,
                    "accounted_good_qty": 0.0,
                    "accounted_reject_qty": 0.0,
                    "accounted_total_qty": 0.0,
                    "accounted_last_at": None,
                    "accounted_last_dt": None,
                    "sent_qty": 0.0,
                    "sent_last_at": None,
                    "sent_last_dt": None,
                    "accepted_by_next_qty": 0.0,
                    "accepted_by_next_last_at": None,
                    "accepted_by_next_last_dt": None,
                    "flow_events": [],
                },
            )
            entry["accepted_by_next_qty"] += accepted_qty
            if entry["accepted_by_next_last_dt"] is None or (event_at and event_at >= entry["accepted_by_next_last_dt"]):
                entry["accepted_by_next_last_dt"] = event_at
                entry["accepted_by_next_last_at"] = event_at_iso
            entry["flow_events"].append(
                {
                    "step": "accept",
                    "label": "Принято след. этапом",
                    "quantity": round(accepted_qty, 3),
                    "event_at": event_at_iso,
                    "task_id": row.from_task_id,
                    "transfer_id": row.transfer_id,
                    "_sort_dt": event_at or row.created_at,
                    "_sort_id": row.transfer_id,
                }
            )

        route_snapshot = {
            "route_id": route_info.route_id,
            "route_name": route_info.route_name,
            "route_source": route_info.source,
            "route_origin": route_info.route_origin,
            "route_match_quality": route_info.route_match_quality,
            "route_match_reason": route_info.route_match_reason,
            "route_assigned_at": route_info.route_assigned_at.isoformat() if route_info.route_assigned_at else None,
            "route_manual_confirmed_at": (
                route_info.route_manual_confirmed_at.isoformat() if route_info.route_manual_confirmed_at else None
            ),
            "steps": [
                {
                    "route_step_id": step.id,
                    "sequence": step.sequence,
                    "section_id": section.id,
                    "section_code": section.code,
                    "section_name": section.name,
                    "section_kind": section.kind,
                    "section_icon": section.icon,
                    "section_icon_color": section.icon_color,
                    "operation_code": step.operation_code,
                    "operation_name": step.operation_name,
                }
                for step, section in steps
            ],
        }

        for step, section in steps:
            fallback_planned = _to_float(pos.quantity) if not has_tasks else 0.0
            planned_quantity = planned_by_step.get(step.id, fallback_planned)
            totals = task_aggregates_by_step.get(
                step.id,
                {"completed_quantity": 0.0, "transferred_quantity": 0.0, "rejected_quantity": 0.0},
            )
            flow = flow_by_step.get(step.id, {})
            completed_quantity = totals["completed_quantity"]
            transferred_quantity = totals["transferred_quantity"]
            rejected_quantity = totals["rejected_quantity"]
            task_status = _summarize_task_status(task_statuses_by_step.get(step.id, []))
            flow_events = flow.get("flow_events", [])
            flow_events.sort(
                key=lambda item: (
                    item.get("_sort_dt") is None,
                    item.get("_sort_dt"),
                    item.get("_sort_id") or 0,
                )
            )

            steps_data.append(
                {
                    "route_step_id": step.id,
                    "section_id": section.id,
                    "section_code": section.code,
                    "section_name": section.name,
                    "section_icon": section.icon,
                    "section_icon_color": section.icon_color,
                    "sequence": step.sequence,
                    "operation_code": step.operation_code,
                    "operation_name": step.operation_name,
                    "planned_quantity": round(planned_quantity, 3),
                    "completed_quantity": round(completed_quantity, 3),
                    "transferred_quantity": round(transferred_quantity, 3),
                    "rejected_quantity": round(rejected_quantity, 3),
                    "execution_percent": _clamp_percent(completed_quantity, planned_quantity),
                    "transfer_percent": _clamp_percent(transferred_quantity, planned_quantity),
                    "reject_percent": _clamp_percent(rejected_quantity, planned_quantity),
                    "task_status": task_status,
                    "not_started": not has_tasks,
                    "issued_qty": round(_to_float(flow.get("issued_qty")), 3),
                    "issued_last_at": flow.get("issued_last_at"),
                    "accounted_good_qty": round(_to_float(flow.get("accounted_good_qty")), 3),
                    "accounted_reject_qty": round(_to_float(flow.get("accounted_reject_qty")), 3),
                    "accounted_total_qty": round(_to_float(flow.get("accounted_total_qty")), 3),
                    "accounted_last_at": flow.get("accounted_last_at"),
                    "sent_qty": round(_to_float(flow.get("sent_qty")), 3),
                    "sent_last_at": flow.get("sent_last_at"),
                    "accepted_by_next_qty": round(_to_float(flow.get("accepted_by_next_qty")), 3),
                    "accepted_by_next_last_at": flow.get("accepted_by_next_last_at"),
                    "flow_events": [
                        {
                            "step": event["step"],
                            "label": event["label"],
                            "quantity": event["quantity"],
                            "event_at": event["event_at"],
                            "task_id": event["task_id"],
                            "transfer_id": event["transfer_id"],
                        }
                        for event in flow_events
                    ],
                }
            )

    # Determine current active stage
    current_stage_info: dict | None = None
    if has_tasks:
        # First try to find in_progress or ready tasks
        current_stage_row = (
            await db.execute(
                select(
                    RouteStep.section_id,
                    RouteStep.sequence,
                    RouteStep.operation_name,
                    Section.code.label("section_code"),
                    Section.name.label("section_name"),
                    WorkTask.status.label("task_status"),
                )
                .join(SectionPlanLine, SectionPlanLine.route_step_id == RouteStep.id)
                .join(Section, Section.id == RouteStep.section_id)
                .join(WorkTask, WorkTask.section_plan_line_id == SectionPlanLine.id)
                .where(SectionPlanLine.plan_position_id == pos.id)
                .where(WorkTask.status.in_([WorkTaskStatus.in_progress, WorkTaskStatus.ready]))
                .order_by(
                    WorkTask.status.desc(),
                    RouteStep.sequence,
                )
                .limit(1)
            )
        ).first()
        
        # Fallback: if no in_progress/ready, get the first stage with any task
        if not current_stage_row:
            current_stage_row = (
                await db.execute(
                    select(
                        RouteStep.section_id,
                        RouteStep.sequence,
                        RouteStep.operation_name,
                        Section.code.label("section_code"),
                        Section.name.label("section_name"),
                        WorkTask.status.label("task_status"),
                    )
                    .join(SectionPlanLine, SectionPlanLine.route_step_id == RouteStep.id)
                    .join(Section, Section.id == RouteStep.section_id)
                    .join(WorkTask, WorkTask.section_plan_line_id == SectionPlanLine.id)
                    .where(SectionPlanLine.plan_position_id == pos.id)
                    .order_by(RouteStep.sequence)
                    .limit(1)
                )
            ).first()
        
        if current_stage_row:
            current_stage_info = {
                "current_stage_section_id": current_stage_row.section_id,
                "current_stage_sequence": current_stage_row.sequence,
                "current_stage_operation": current_stage_row.operation_name,
                "current_stage_section_code": current_stage_row.section_code,
                "current_stage_section_name": current_stage_row.section_name,
                "current_stage_task_status": (
                    current_stage_row.task_status.value 
                    if hasattr(current_stage_row.task_status, "value") 
                    else str(current_stage_row.task_status)
                ),
            }

    return {
        "plan_position_id": pos.id,
        "production_plan_id": pos.production_plan_id,
        "source_row_number": pos.source_row_number,
        "source_sku": pos.source_sku,
        "source_name": pos.source_name,
        "quantity": _to_float(pos.quantity),
        "position_status": pos.status.value if hasattr(pos.status, "value") else str(pos.status),
        "validation_status": pos.validation_status.value if hasattr(pos.validation_status, "value") else str(pos.validation_status),
        "route_id": route_info.route_id,
        "route_name": route_info.route_name,
        "route_source": route_info.source,
        "route_origin": route_info.route_origin,
        "route_match_quality": route_info.route_match_quality,
        "route_match_reason": route_info.route_match_reason,
        "route_assigned_at": route_info.route_assigned_at.isoformat() if route_info.route_assigned_at else None,
        "route_manual_confirmed_at": (
            route_info.route_manual_confirmed_at.isoformat() if route_info.route_manual_confirmed_at else None
        ),
        "route_error": _resolved_route_error(route_info),
        "is_released": bool(has_tasks or pos.status == PlanPositionStatus.released),
        "has_tasks": has_tasks,
        "not_started": not has_tasks,
        "route_snapshot": route_snapshot,
        "stages": steps_data,
        "current_stage_section_id": current_stage_info.get("current_stage_section_id") if current_stage_info else None,
        "current_stage_sequence": current_stage_info.get("current_stage_sequence") if current_stage_info else None,
        "current_stage_operation": current_stage_info.get("current_stage_operation") if current_stage_info else None,
        "current_stage_section_code": current_stage_info.get("current_stage_section_code") if current_stage_info else None,
        "current_stage_section_name": current_stage_info.get("current_stage_section_name") if current_stage_info else None,
        "current_stage_task_status": current_stage_info.get("current_stage_task_status") if current_stage_info else None,
        "raw_excel_row": (pos.source_payload or {}).get("raw_excel_row"),
        "payload": pos.source_payload,
    }
