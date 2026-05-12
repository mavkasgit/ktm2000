from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_plan import SectionPlanLine
from app.models.production_plan import PlanPosition, PlanPositionStatus
from app.models.route import RouteStep
from app.models.section import Section
from app.models.work_task import WorkTask
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

    route_cache: dict[int, ResolvedRouteInfo] = {}

    result: list[dict] = []
    for pos in positions:
        if pos.id not in route_cache:
            route_cache[pos.id] = await resolve_position_route(db, pos)
        route_info = route_cache[pos.id]

        has_tasks = pos.id in has_tasks_set
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
                "route_error": _resolved_route_error(route_info),
                "is_released": bool(has_tasks or pos.status == PlanPositionStatus.released),
                "has_tasks": has_tasks,
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

        route_snapshot = {
            "route_id": route_info.route_id,
            "route_name": route_info.route_name,
            "route_source": route_info.source,
            "steps": [
                {
                    "route_step_id": step.id,
                    "sequence": step.sequence,
                    "section_id": section.id,
                    "section_code": section.code,
                    "section_name": section.name,
                    "section_kind": section.kind,
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
            completed_quantity = totals["completed_quantity"]
            transferred_quantity = totals["transferred_quantity"]
            rejected_quantity = totals["rejected_quantity"]
            task_status = _summarize_task_status(task_statuses_by_step.get(step.id, []))

            steps_data.append(
                {
                    "route_step_id": step.id,
                    "section_id": section.id,
                    "section_code": section.code,
                    "section_name": section.name,
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
                }
            )

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
        "route_error": _resolved_route_error(route_info),
        "is_released": bool(has_tasks or pos.status == PlanPositionStatus.released),
        "has_tasks": has_tasks,
        "not_started": not has_tasks,
        "route_snapshot": route_snapshot,
        "stages": steps_data,
    }
