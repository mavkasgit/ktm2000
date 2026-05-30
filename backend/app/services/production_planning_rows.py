from __future__ import annotations

from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_plan import SectionPlanLine
from app.models.movement import Movement, MovementType
from app.models.production_plan import PlanPosition, PlanPositionStatus
from app.models.route import RouteStep, SectionOperation
from app.models.section import Section
from app.models.transfer import Transfer
from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.route_matcher import ResolvedRouteInfo, resolve_position_route

MANUAL_ROUTE_PASS_PREFIX = "manual_route_pass:"


def _resolve_step_operation_code(
    step_operation_code: str | None,
    section_code: str,
    position: PlanPosition,
    *,
    combined_op_group: str | None = None,
) -> str | None:
    """Return operation_code for a route step.

    All route steps now have explicit operation_code from dynamic route building.
    """
    return step_operation_code


async def _resolve_current_stage_operation(
    db: AsyncSession,
    operation_name: str,
    operation_code: str | None,
    section_code: str,
    section_id: int,
    position: PlanPosition,
    operation_names_by_key: dict[tuple[int, str], str],
) -> str:
    """Return operation name for current-stage info."""
    if operation_code is not None:
        return operation_names_by_key.get((section_id, operation_code), operation_name)
    return operation_name


async def _resolve_step_operation_name(
    db: AsyncSession,
    step: RouteStep,
    section: Section,
    position: PlanPosition,
    operation_names_by_key: dict[tuple[int, str], str],
) -> str:
    operation_code = _resolve_step_operation_code(
        step.operation_code, section.code, position,
        combined_op_group=step.combined_op_group,
    )
    if operation_code is not None:
        return operation_names_by_key.get((section.id, operation_code), step.operation_name)
    return step.operation_name


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


def _group_combined_route_steps(steps: list[tuple[RouteStep, Section]]) -> list[list[tuple[RouteStep, Section]]]:
    grouped_steps: list[list[tuple[RouteStep, Section]]] = []
    current_group: list[tuple[RouteStep, Section]] = []
    current_cog: str | None = None
    current_section_id: int | None = None

    for step, section in steps:
        step_cog = step.combined_op_group
        if step_cog is not None and step_cog == current_cog and step.section_id == current_section_id:
            current_group.append((step, section))
            continue

        if current_group:
            grouped_steps.append(current_group)
        current_group = [(step, section)]
        current_cog = step_cog
        current_section_id = step.section_id

    if current_group:
        grouped_steps.append(current_group)

    return grouped_steps


def _resolved_route_error(route_info: ResolvedRouteInfo) -> str | None:
    if route_info.error:
        return route_info.error
    if route_info.route_id is None:
        return "route_not_found"
    return None


def _event_at_iso(*, performed_at, accounted_at, created_at) -> str | None:
    event_at = performed_at or accounted_at or created_at
    return event_at.isoformat() if event_at else None


def _is_manual_route_pass(value: str | None) -> bool:
    return bool(value and value.startswith(MANUAL_ROUTE_PASS_PREFIX))


async def list_production_planning_rows(db: AsyncSession) -> list[dict]:
    positions = (
        await db.execute(
            select(PlanPosition)
            .where(PlanPosition.status.in_([PlanPositionStatus.approved, PlanPositionStatus.released, PlanPositionStatus.cancelled]))
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

    # Count total and completed tasks per position to detect fully completed positions
    task_counts = (
        await db.execute(
            select(
                SectionPlanLine.plan_position_id,
                func.count(WorkTask.id).label("total_tasks"),
                func.sum(
                    case((WorkTask.status == WorkTaskStatus.completed, 1), else_=0)
                ).label("completed_tasks"),
            )
            .join(WorkTask, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id.in_(position_ids))
            .group_by(SectionPlanLine.plan_position_id)
        )
    ).all()
    completed_set = {
        row.plan_position_id
        for row in task_counts
        if row.total_tasks > 0 and row.completed_tasks == row.total_tasks
    }

    # Also treat position as completed when the final route step task is completed.
    # This covers routes where terminal section is SENT (or any custom final section),
    # while previous stages may keep non-terminal statuses.
    final_step_completed_rows = (
        await db.execute(
            select(SectionPlanLine.plan_position_id)
            .join(WorkTask, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .join(RouteStep, RouteStep.id == SectionPlanLine.route_step_id)
            .where(
                SectionPlanLine.plan_position_id.in_(position_ids),
                WorkTask.status == WorkTaskStatus.completed,
                RouteStep.is_final.is_(True),
            )
            .group_by(SectionPlanLine.plan_position_id)
        )
    ).all()
    final_step_completed_set = {row[0] for row in final_step_completed_rows}
    completed_set |= final_step_completed_set

    # Fetch current stage info: first in_progress or ready task per position
    current_stage_rows = (
        await db.execute(
            select(
                SectionPlanLine.plan_position_id,
                RouteStep.section_id,
                RouteStep.sequence,
                RouteStep.operation_name,
                RouteStep.operation_code,
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
                    RouteStep.operation_code,
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
                "current_stage_operation_name": row.operation_name,
                "current_stage_operation_code": row.operation_code,
                "current_stage_section_code": row.section_code,
                "current_stage_section_name": row.section_name,
                "current_stage_task_status": row.task_status.value if hasattr(row.task_status, "value") else str(row.task_status),
            }
    fallback_rows_by_position: dict[int, list] = {}
    for row in fallback_rows:
        fallback_rows_by_position.setdefault(row.plan_position_id, []).append(row)

    for position_id, rows in fallback_rows_by_position.items():
        if position_id in current_stage_by_position:
            continue
        chosen_row = None
        for row in rows:
            status_value = row.task_status.value if hasattr(row.task_status, "value") else str(row.task_status)
            if status_value not in {"completed", "cancelled"}:
                chosen_row = row
                break
        if chosen_row is None and rows:
            # All tasks are terminal for this position; point to the last route step.
            chosen_row = rows[-1]
        if chosen_row is not None:
            current_stage_by_position[position_id] = {
                "current_stage_section_id": chosen_row.section_id,
                "current_stage_sequence": chosen_row.sequence,
                "current_stage_operation_name": chosen_row.operation_name,
                "current_stage_operation_code": chosen_row.operation_code,
                "current_stage_section_code": chosen_row.section_code,
                "current_stage_section_name": chosen_row.section_name,
                "current_stage_task_status": (
                    chosen_row.task_status.value
                    if hasattr(chosen_row.task_status, "value")
                    else str(chosen_row.task_status)
                ),
            }

    route_cache: dict[int, ResolvedRouteInfo] = {}
    route_steps_cache: dict[int, list[dict]] = {}

    result: list[dict] = []
    for pos in positions:
        if pos.id not in route_cache:
            route_info = await resolve_position_route(db, pos)
            route_cache[pos.id] = route_info

            # Cache route steps for this route
            if route_info.route_id is not None and route_info.route_id not in route_steps_cache:
                steps = (
                    await db.execute(
                        select(RouteStep, Section)
                        .join(Section, RouteStep.section_id == Section.id)
                        .where(RouteStep.route_id == route_info.route_id)
                        .where(Section.is_active == True)
                        .order_by(RouteStep.sequence)
                    )
                ).all()
                route_steps_cache[route_info.route_id] = [
                    {
                        "section_id": section.id,
                        "section_icon": section.icon,
                        "section_icon_color": section.icon_color,
                        "sequence": group[0][0].sequence,
                    }
                    for group in _group_combined_route_steps(steps)
                    for _step, section in [group[0]]
                ]

        route_info = route_cache[pos.id]

        has_tasks = pos.id in has_tasks_set
        is_completed = pos.id in completed_set
        raw_stage_info = current_stage_by_position.get(pos.id, {})

        # Resolve operation name for current stage using position-specific payload
        current_stage_operation = None
        if raw_stage_info:
            current_stage_operation = await _resolve_current_stage_operation(
                db,
                operation_name=raw_stage_info.get("current_stage_operation_name", ""),
                operation_code=raw_stage_info.get("current_stage_operation_code"),
                section_code=raw_stage_info.get("current_stage_section_code", ""),
                section_id=raw_stage_info.get("current_stage_section_id", 0),
                position=pos,
                operation_names_by_key={},
            )

        route_steps = route_steps_cache.get(route_info.route_id) if route_info.route_id is not None else None
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
                "is_completed": is_completed,
                "current_stage_section_id": raw_stage_info.get("current_stage_section_id"),
                "current_stage_sequence": raw_stage_info.get("current_stage_sequence"),
                "current_stage_operation": current_stage_operation or None,
                "current_stage_section_code": raw_stage_info.get("current_stage_section_code"),
                "current_stage_section_name": raw_stage_info.get("current_stage_section_name"),
                "current_stage_task_status": raw_stage_info.get("current_stage_task_status"),
                "route_steps": route_steps,
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
        section_ids = {section.id for _step, section in steps}
        operation_names_by_key = {
            (operation.section_id, operation.operation_code): operation.operation_name
            for operation in (
                await db.execute(
                    select(SectionOperation).where(SectionOperation.section_id.in_(section_ids))
                )
            ).scalars().all()
        }

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
                    Movement.source_ref.label("source_ref"),
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
            is_manual_route_pass = _is_manual_route_pass(row.source_ref)
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
                        "label": "Ручной пропуск: выдано" if is_manual_route_pass else "Выдано в работу",
                        "quantity": round(quantity, 3),
                        "event_at": event_at_iso,
                        "task_id": row.task_id,
                        "transfer_id": row.transfer_id,
                        "manual_route_pass": is_manual_route_pass,
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
                        "label": "Ручной пропуск: выполнено" if is_manual_route_pass else "Учтено (годное)",
                        "quantity": round(quantity, 3),
                        "event_at": event_at_iso,
                        "task_id": row.task_id,
                        "transfer_id": row.transfer_id,
                        "manual_route_pass": is_manual_route_pass,
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
                        "label": "Ручной пропуск: брак" if is_manual_route_pass else "Учтено (брак)",
                        "quantity": round(quantity, 3),
                        "event_at": event_at_iso,
                        "task_id": row.task_id,
                        "transfer_id": row.transfer_id,
                        "manual_route_pass": is_manual_route_pass,
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
                        "label": "Ручной пропуск: передано" if is_manual_route_pass else "Передано",
                        "quantity": round(quantity, 3),
                        "event_at": event_at_iso,
                        "task_id": row.task_id,
                        "transfer_id": row.transfer_id,
                        "manual_route_pass": is_manual_route_pass,
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
                    Transfer.idempotency_key.label("idempotency_key"),
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
            is_manual_route_pass = _is_manual_route_pass(row.idempotency_key)
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
                    "label": "Ручной пропуск: принято след. этапом" if is_manual_route_pass else "Принято след. этапом",
                    "quantity": round(accepted_qty, 3),
                    "event_at": event_at_iso,
                    "task_id": row.from_task_id,
                    "transfer_id": row.transfer_id,
                    "manual_route_pass": is_manual_route_pass,
                    "_sort_dt": event_at or row.created_at,
                    "_sort_id": row.transfer_id,
                }
            )

        grouped_steps = _group_combined_route_steps(steps)

        # Build route_snapshot steps with async resolution
        snapshot_steps = []
        for group in grouped_steps:
            _step, section = group[0]
            first_step = group[0][0]
            op_code = _resolve_step_operation_code(
                first_step.operation_code, section.code, pos,
                combined_op_group=first_step.combined_op_group,
            )
            op_names = [
                await _resolve_step_operation_name(db, step, group_section, pos, operation_names_by_key)
                for step, group_section in group
            ]
            snapshot_steps.append({
                "route_step_id": group[0][0].id,
                "sequence": group[0][0].sequence,
                "section_id": section.id,
                "section_code": section.code,
                "section_name": section.name,
                "section_kind": section.kind,
                "section_icon": section.icon,
                "section_icon_color": section.icon_color,
                "operation_code": op_code,
                "operation_name": " / ".join(op_names),
            })

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
            "steps": snapshot_steps,
        }

        for group in grouped_steps:
            step, section = group[0]
            step_ids = [group_step.id for group_step, _section in group]
            fallback_planned = _to_float(pos.quantity) if not has_tasks else 0.0
            planned_values = [planned_by_step[step_id] for step_id in step_ids if step_id in planned_by_step]
            planned_quantity = max(planned_values) if planned_values else fallback_planned
            completed_quantity = sum(task_aggregates_by_step.get(step_id, {}).get("completed_quantity", 0.0) for step_id in step_ids)
            transferred_quantity = sum(task_aggregates_by_step.get(step_id, {}).get("transferred_quantity", 0.0) for step_id in step_ids)
            rejected_quantity = sum(task_aggregates_by_step.get(step_id, {}).get("rejected_quantity", 0.0) for step_id in step_ids)
            task_status = _summarize_task_status([
                status
                for step_id in step_ids
                for status in task_statuses_by_step.get(step_id, [])
            ])
            flows = [flow_by_step.get(step_id, {}) for step_id in step_ids]
            flow_events = [
                event
                for flow in flows
                for event in flow.get("flow_events", [])
            ]
            flow_events.sort(
                key=lambda item: (
                    item.get("_sort_dt") is None,
                    item.get("_sort_dt"),
                    item.get("_sort_id") or 0,
                )
            )

            op_code = _resolve_step_operation_code(
                step.operation_code, section.code, pos,
                combined_op_group=step.combined_op_group,
            )
            op_names = [
                await _resolve_step_operation_name(db, group_step, group_section, pos, operation_names_by_key)
                for group_step, group_section in group
            ]

            steps_data.append(
                {
                    "route_step_id": step.id,
                    "section_id": section.id,
                    "section_code": section.code,
                    "section_name": section.name,
                    "section_icon": section.icon,
                    "section_icon_color": section.icon_color,
                    "sequence": step.sequence,
                    "operation_code": op_code,
                    "operation_name": " / ".join(op_names),
                    "planned_quantity": round(planned_quantity, 3),
                    "completed_quantity": round(completed_quantity, 3),
                    "transferred_quantity": round(transferred_quantity, 3),
                    "rejected_quantity": round(rejected_quantity, 3),
                    "execution_percent": _clamp_percent(completed_quantity, planned_quantity),
                    "transfer_percent": _clamp_percent(transferred_quantity, planned_quantity),
                    "reject_percent": _clamp_percent(rejected_quantity, planned_quantity),
                    "task_status": task_status,
                    "not_started": not has_tasks,
                    "issued_qty": round(sum(_to_float(flow.get("issued_qty")) for flow in flows), 3),
                    "issued_last_at": max((flow.get("issued_last_at") for flow in flows if flow.get("issued_last_at")), default=None),
                    "accounted_good_qty": round(sum(_to_float(flow.get("accounted_good_qty")) for flow in flows), 3),
                    "accounted_reject_qty": round(sum(_to_float(flow.get("accounted_reject_qty")) for flow in flows), 3),
                    "accounted_total_qty": round(sum(_to_float(flow.get("accounted_total_qty")) for flow in flows), 3),
                    "accounted_last_at": max((flow.get("accounted_last_at") for flow in flows if flow.get("accounted_last_at")), default=None),
                    "sent_qty": round(sum(_to_float(flow.get("sent_qty")) for flow in flows), 3),
                    "sent_last_at": max((flow.get("sent_last_at") for flow in flows if flow.get("sent_last_at")), default=None),
                    "accepted_by_next_qty": round(sum(_to_float(flow.get("accepted_by_next_qty")) for flow in flows), 3),
                    "accepted_by_next_last_at": max(
                        (flow.get("accepted_by_next_last_at") for flow in flows if flow.get("accepted_by_next_last_at")),
                        default=None,
                    ),
                    "flow_events": [
                        {
                            "step": event["step"],
                            "label": event["label"],
                            "quantity": event["quantity"],
                            "event_at": event["event_at"],
                            "task_id": event["task_id"],
                            "transfer_id": event["transfer_id"],
                            "manual_route_pass": bool(event.get("manual_route_pass")),
                        }
                        for event in flow_events
                    ],
                }
            )

    # Determine current active stage
    current_stage_info: dict | None = None
    if has_tasks:
        # Load operation_names_by_key if not already loaded (for current_stage resolution)
        if route_info.route_id is not None and "operation_names_by_key" not in locals():
            _steps_for_ops = (
                await db.execute(
                    select(RouteStep, Section)
                    .join(Section, RouteStep.section_id == Section.id)
                    .where(RouteStep.route_id == route_info.route_id)
                    .order_by(RouteStep.sequence)
                )
            ).all()
            _section_ids_for_ops = {s.id for _s, s in _steps_for_ops}
            operation_names_by_key = {
                (op.section_id, op.operation_code): op.operation_name
                for op in (
                    await db.execute(
                        select(SectionOperation).where(SectionOperation.section_id.in_(_section_ids_for_ops))
                    )
                ).scalars().all()
            }

        # First try to find in_progress or ready tasks
        current_stage_row = (
            await db.execute(
                select(
                    RouteStep.section_id,
                    RouteStep.sequence,
                    RouteStep.operation_name,
                    RouteStep.operation_code,
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

        # Fallback: if no in_progress/ready, pick first non-terminal stage; else last stage.
        if not current_stage_row:
            fallback_stage_rows = (
                await db.execute(
                    select(
                        RouteStep.section_id,
                        RouteStep.sequence,
                        RouteStep.operation_name,
                        RouteStep.operation_code,
                        Section.code.label("section_code"),
                        Section.name.label("section_name"),
                        WorkTask.status.label("task_status"),
                    )
                    .join(SectionPlanLine, SectionPlanLine.route_step_id == RouteStep.id)
                    .join(Section, Section.id == RouteStep.section_id)
                    .join(WorkTask, WorkTask.section_plan_line_id == SectionPlanLine.id)
                    .where(SectionPlanLine.plan_position_id == pos.id)
                    .order_by(RouteStep.sequence)
                )
            ).all()
            for row in fallback_stage_rows:
                status_value = row.task_status.value if hasattr(row.task_status, "value") else str(row.task_status)
                if status_value not in {"completed", "cancelled"}:
                    current_stage_row = row
                    break
            if not current_stage_row and fallback_stage_rows:
                current_stage_row = fallback_stage_rows[-1]

        if current_stage_row:
            resolved_op_name = await _resolve_current_stage_operation(
                db,
                operation_name=current_stage_row.operation_name,
                operation_code=current_stage_row.operation_code,
                section_code=current_stage_row.section_code,
                section_id=current_stage_row.section_id,
                position=pos,
                operation_names_by_key=locals().get("operation_names_by_key", {}),
            )
            current_stage_info = {
                "current_stage_section_id": current_stage_row.section_id,
                "current_stage_sequence": current_stage_row.sequence,
                "current_stage_operation": resolved_op_name,
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
