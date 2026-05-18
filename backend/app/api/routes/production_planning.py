from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WRITER_ROLES, get_current_user, require_role
from app.core.database import get_db
from app.models.internal_plan import SectionPlanLine
from app.models.production_plan import PlanPosition, PlanPositionStatus, ProductionPlan
from app.models.work_task import WorkTask, WorkTaskStatus
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
from app.models.user import User
from app.services.production_planning_rows import get_production_planning_row_detail, list_production_planning_rows
from app.services.production_plan_service import record_status_change, restore_plan_position
from app.services.plan_generation import create_release_batch, release_batch
from app.services.route_matcher import resolve_position_route

router = APIRouter(prefix="/production-planning", tags=["execution-control"])


class TakeToWorkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position_ids: list[int]


class StatusActionIn(BaseModel):
    reason: str | None = None


class TakeToWorkResult(BaseModel):
    position_id: int
    status: str  # "success" | "already_started" | "failed"
    reason: str | None = None
    release_batch_id: int | None = None
    internal_plan_id: int | None = None
    tasks_created: int | None = None


class TakeToWorkResponse(BaseModel):
    results: list[TakeToWorkResult]


class WorkTaskOut(BaseModel):
    id: int
    route_step_id: int
    operation_name: str | None
    operation_code: str | None
    status: str
    planned_quantity: float
    completed_quantity: float
    sequence: int


class PositionProgressOut(BaseModel):
    total_steps: int
    completed_steps: int
    percent: float


class PositionOut(BaseModel):
    plan_position_id: int
    production_plan_id: int
    source_row_number: int | None
    source_sku: str
    source_name: str | None
    quantity: float
    route_id: int | None
    route_name: str | None
    route_source: str | None
    status: str
    progress: PositionProgressOut
    work_tasks: list[WorkTaskOut]


class SectionOut(BaseModel):
    section_id: int
    section_code: str
    section_name: str
    section_kind: str
    positions_count: int
    ready_count: int
    in_progress_count: int
    completed_count: int
    positions: list[PositionOut]


class ProductionPlanningOverview(BaseModel):
    sections: list[SectionOut]


class PlanningRowOut(BaseModel):
    plan_position_id: int
    production_plan_id: int
    source_row_number: int | None
    source_sku: str
    source_name: str | None
    quantity: float
    position_status: str
    validation_status: str
    route_id: int | None
    route_name: str | None
    route_source: str | None
    route_origin: str | None
    route_match_quality: str | None
    route_match_reason: str | None
    route_assigned_at: str | None
    route_manual_confirmed_at: str | None
    route_error: str | None
    is_released: bool
    has_tasks: bool
    current_stage_section_id: int | None = None
    current_stage_sequence: int | None = None
    current_stage_operation: str | None = None
    current_stage_section_code: str | None = None
    current_stage_section_name: str | None = None
    current_stage_task_status: str | None = None


class PlanningRouteSnapshotStepOut(BaseModel):
    route_step_id: int
    sequence: int
    section_id: int
    section_code: str
    section_name: str
    section_kind: str | None
    section_icon: str | None = None
    section_icon_color: str | None = None
    operation_code: str | None
    operation_name: str


class PlanningRouteSnapshotOut(BaseModel):
    route_id: int
    route_name: str | None
    route_source: str
    route_origin: str | None = None
    route_match_quality: str | None = None
    route_match_reason: str | None = None
    route_assigned_at: str | None = None
    route_manual_confirmed_at: str | None = None
    steps: list[PlanningRouteSnapshotStepOut]


class PlanningStageOut(BaseModel):
    class FlowEventOut(BaseModel):
        step: str
        label: str
        quantity: float
        event_at: str | None = None
        task_id: int | None = None
        transfer_id: int | None = None

    route_step_id: int
    section_id: int
    section_code: str
    section_name: str
    section_icon: str | None = None
    section_icon_color: str | None = None
    sequence: int
    operation_code: str | None
    operation_name: str
    planned_quantity: float
    completed_quantity: float
    transferred_quantity: float
    rejected_quantity: float
    execution_percent: float
    transfer_percent: float
    reject_percent: float
    task_status: str
    not_started: bool
    issued_qty: float
    issued_last_at: str | None = None
    accounted_good_qty: float
    accounted_reject_qty: float
    accounted_total_qty: float
    accounted_last_at: str | None = None
    sent_qty: float
    sent_last_at: str | None = None
    accepted_by_next_qty: float
    accepted_by_next_last_at: str | None = None
    flow_events: list[FlowEventOut] = Field(default_factory=list)


class PlanningRowDetailOut(BaseModel):
    plan_position_id: int
    production_plan_id: int
    source_row_number: int | None
    source_sku: str
    source_name: str | None
    quantity: float
    position_status: str
    validation_status: str
    route_id: int | None
    route_name: str | None
    route_source: str | None
    route_origin: str | None
    route_match_quality: str | None
    route_match_reason: str | None
    route_assigned_at: str | None
    route_manual_confirmed_at: str | None
    route_error: str | None
    is_released: bool
    has_tasks: bool
    not_started: bool
    current_stage_section_id: int | None = None
    current_stage_sequence: int | None = None
    current_stage_operation: str | None = None
    current_stage_section_code: str | None = None
    current_stage_section_name: str | None = None
    current_stage_task_status: str | None = None
    route_snapshot: PlanningRouteSnapshotOut | None
    stages: list[PlanningStageOut]
    raw_excel_row: dict | None = None
    payload: dict | None = None


@router.get("/rows", response_model=list[PlanningRowOut])
async def list_rows(
    db: AsyncSession = Depends(get_db),
):
    return await list_production_planning_rows(db)


@router.get("/rows/{position_id}", response_model=PlanningRowDetailOut)
async def get_row_detail(
    position_id: int,
    db: AsyncSession = Depends(get_db),
):
    detail = await get_production_planning_row_detail(db, position_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Position not found")
    return detail


@router.get("/overview", response_model=ProductionPlanningOverview)
async def get_production_planning_overview(
    db: AsyncSession = Depends(get_db),
):
    """Return all approved plan positions grouped by section with work task progress."""

    # Fetch all approved and released plan positions
    positions = (
        await db.execute(
            select(PlanPosition)
            .where(PlanPosition.status.in_([PlanPositionStatus.approved, PlanPositionStatus.released]))
            .where(PlanPosition.deleted_at.is_(None))
            .order_by(PlanPosition.production_plan_id, PlanPosition.priority, PlanPosition.id)
        )
    ).scalars().all()

    if not positions:
        return ProductionPlanningOverview(sections=[])

    # Resolve routes for all positions
    position_route_map: dict[int, tuple[int | None, str | None, str | None]] = {}
    for pos in positions:
        route_info = await resolve_position_route(db, pos)
        position_route_map[pos.id] = (route_info.route_id, route_info.route_name, route_info.source)

    # Collect all section IDs from resolved routes
    section_ids: set[int] = set()
    route_steps_cache: dict[int, list[RouteStep]] = {}
    for pos in positions:
        route_id = position_route_map[pos.id][0]
        if route_id is not None:
            if route_id not in route_steps_cache:
                steps = (
                    await db.execute(
                        select(RouteStep)
                        .where(RouteStep.route_id == route_id)
                        .join(Section, RouteStep.section_id == Section.id)
                        .where(Section.is_active == True)
                        .order_by(RouteStep.sequence)
                    )
                ).scalars().all()
                route_steps_cache[route_id] = steps
            for step in route_steps_cache[route_id]:
                section_ids.add(step.section_id)

    if not section_ids:
        return ProductionPlanningOverview(sections=[])

    # Fetch sections
    sections = (
        await db.execute(
            select(Section)
            .where(Section.id.in_(section_ids), Section.is_active == True)
            .order_by(Section.sort_order)
        )
    ).scalars().all()

    section_map = {s.id: s for s in sections}

    # Fetch all section plan lines and work tasks for approved positions
    position_ids = [p.id for p in positions]
    section_plan_lines = (
        await db.execute(
            select(SectionPlanLine)
            .where(SectionPlanLine.plan_position_id.in_(position_ids))
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()
    line_ids = [line.id for line in section_plan_lines]
    work_tasks = []
    if line_ids:
        work_tasks = (
            await db.execute(
                select(WorkTask).where(WorkTask.section_plan_line_id.in_(line_ids)).order_by(WorkTask.id)
            )
        ).scalars().all()

    # Group section plan lines by (position_id, section_id)
    pos_section_lines: dict[tuple[int, int], list[SectionPlanLine]] = {}
    for line in section_plan_lines:
        key = (line.plan_position_id, line.section_id)
        pos_section_lines.setdefault(key, []).append(line)
    line_work_tasks: dict[int, list[WorkTask]] = {}
    for wt in work_tasks:
        line_work_tasks.setdefault(wt.section_plan_line_id, []).append(wt)

    # Build result
    result_sections: list[SectionOut] = []

    for section in sections:
        section_positions: list[PositionOut] = []
        ready_count = 0
        in_progress_count = 0
        completed_count = 0

        for pos in positions:
            route_id, route_name, route_source = position_route_map[pos.id]

            # Find work tasks for this position in this section
            lines = pos_section_lines.get((pos.id, section.id), [])
            work_tasks_out: list[WorkTaskOut] = []
            total_steps = 0
            completed_steps = 0

            for line in lines:
                for wt in line_work_tasks.get(line.id, []):
                    total_steps += 1
                    if wt.status == WorkTaskStatus.completed:
                        completed_steps += 1

                    # Get operation info from route step
                    step = await db.get(RouteStep, wt.route_step_id)
                    work_tasks_out.append(
                        WorkTaskOut(
                            id=wt.id,
                            route_step_id=wt.route_step_id,
                            operation_name=step.operation_name if step else None,
                            operation_code=step.operation_code if step else None,
                            status=wt.status.value if hasattr(wt.status, 'value') else wt.status,
                            planned_quantity=float(wt.planned_quantity),
                            completed_quantity=float(wt.cached_completed_quantity),
                            sequence=step.sequence if step else 0,
                        )
                    )

            if not work_tasks_out:
                # No work tasks yet — position is in queue for this section
                # Show it if the route includes this section
                if route_id is not None:
                    steps = route_steps_cache.get(route_id, [])
                    for step in steps:
                        if step.section_id == section.id:
                            total_steps += 1
                            work_tasks_out.append(
                                WorkTaskOut(
                                    id=0,
                                    route_step_id=step.id,
                                    operation_name=step.operation_name,
                                    operation_code=step.operation_code,
                                    status="waiting",
                                    planned_quantity=float(pos.quantity),
                                    completed_quantity=0.0,
                                    sequence=step.sequence,
                                )
                            )

            if total_steps == 0:
                continue  # This position doesn't go through this section

            percent = (completed_steps / total_steps * 100) if total_steps > 0 else 0.0

            # Determine overall status for this position in this section
            if completed_steps == total_steps:
                completed_count += 1
            elif any(wt.status in ("ready", "in_progress") for wt in work_tasks_out):
                in_progress_count += 1
            else:
                ready_count += 1

            section_positions.append(
                PositionOut(
                    plan_position_id=pos.id,
                    production_plan_id=pos.production_plan_id,
                    source_row_number=pos.source_row_number,
                    source_sku=pos.source_sku,
                    source_name=pos.source_name,
                    quantity=float(pos.quantity),
                    route_id=route_id,
                    route_name=route_name,
                    route_source=route_source,
                    status=pos.status.value if hasattr(pos.status, 'value') else pos.status,
                    progress=PositionProgressOut(
                        total_steps=total_steps,
                        completed_steps=completed_steps,
                        percent=round(percent, 1),
                    ),
                    work_tasks=work_tasks_out,
                )
            )

        result_sections.append(
            SectionOut(
                section_id=section.id,
                section_code=section.code,
                section_name=section.name,
                section_kind=section.kind,
                positions_count=len(section_positions),
                ready_count=ready_count,
                in_progress_count=in_progress_count,
                completed_count=completed_count,
                positions=section_positions,
            )
        )

    return ProductionPlanningOverview(sections=result_sections)


@router.post("/rows/take-to-work", response_model=TakeToWorkResponse, dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def take_rows_to_work(
    payload: TakeToWorkRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TakeToWorkResponse:
    """Launch plan positions into production: create work tasks for all route stages."""
    results: list[TakeToWorkResult] = []

    for position_id in payload.position_ids:
        result = await _process_position_take_to_work(db, position_id)
        results.append(result)

    return TakeToWorkResponse(results=results)


@router.post("/rows/{position_id}/cancel", dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def cancel_position(
    position_id: int,
    payload: StatusActionIn | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Cancel an approved or released position. Moves position to cancelled status."""
    pos = await db.get(PlanPosition, position_id)
    if pos is None:
        raise HTTPException(status_code=404, detail="Position not found")

    if pos.status not in {PlanPositionStatus.approved, PlanPositionStatus.released}:
        raise HTTPException(status_code=400, detail=f"Нельзя отменить позицию со статусом '{pos.status.value}'")

    from_status = pos.status.value
    pos.status = PlanPositionStatus.cancelled
    record_status_change(db, position_id, from_status, PlanPositionStatus.cancelled.value, current_user.id, payload.reason if payload else None)
    await db.commit()

    return {
        "id": pos.id,
        "production_plan_id": pos.production_plan_id,
        "status": pos.status.value,
    }


@router.post("/rows/{position_id}/restore", dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def restore_position(
    position_id: int,
    payload: StatusActionIn | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Restore a cancelled position to its previous status based on history."""
    pos = await db.get(PlanPosition, position_id)
    if pos is None:
        raise HTTPException(status_code=404, detail="Position not found")

    if pos.status != PlanPositionStatus.cancelled:
        raise HTTPException(status_code=400, detail=f"Нельзя восстановить позицию со статусом '{pos.status.value}'")

    # Find last cancellation history record
    from app.models.production_plan import PositionStatusHistory
    from sqlalchemy import select
    last_cancel = (
        await db.execute(
            select(PositionStatusHistory)
            .where(
                PositionStatusHistory.plan_position_id == position_id,
                PositionStatusHistory.to_status == PlanPositionStatus.cancelled.value,
            )
            .order_by(PositionStatusHistory.changed_at.desc())
        )
    ).scalar_one_or_none()

    if last_cancel is None:
        raise HTTPException(status_code=400, detail="Нет истории отмены — восстановление невозможно")

    target_status_value = last_cancel.from_status
    if target_status_value not in {PlanPositionStatus.approved.value, PlanPositionStatus.released.value}:
        raise HTTPException(status_code=400, detail=f"Недопустимый статус для восстановления: '{target_status_value}'")

    pos.status = PlanPositionStatus(target_status_value)
    record_status_change(db, position_id, PlanPositionStatus.cancelled.value, target_status_value, current_user.id, payload.reason if payload else None)
    await db.commit()

    return {
        "id": pos.id,
        "production_plan_id": pos.production_plan_id,
        "status": pos.status.value,
    }


async def _process_position_take_to_work(
    db: AsyncSession,
    position_id: int,
) -> TakeToWorkResult:
    """Process a single position: validate and release into production."""
    # Check position exists
    pos = await db.get(PlanPosition, position_id)
    if pos is None:
        return TakeToWorkResult(
            position_id=position_id,
            status="failed",
            reason="Plan position not found",
        )

    # Check if already has tasks (SectionPlanLines)
    existing_lines = await db.scalar(
        select(func.count(SectionPlanLine.id)).where(SectionPlanLine.plan_position_id == position_id)
    )
    if existing_lines and existing_lines > 0:
        return TakeToWorkResult(
            position_id=position_id,
            status="already_started",
            reason="Position already has tasks created",
        )

    # Check position is approved
    if pos.status != PlanPositionStatus.approved:
        return TakeToWorkResult(
            position_id=position_id,
            status="failed",
            reason=f"Position status is '{pos.status.value}', must be 'approved'",
        )

    # Resolve route
    route_info = await resolve_position_route(db, pos)

    if route_info.route_id is None:
        return TakeToWorkResult(
            position_id=position_id,
            status="failed",
            reason=route_info.error or "No route found for this position",
        )

    # Verify route is active
    route = await db.get(ProductionRoute, route_info.route_id)
    if route is None or not route.is_active:
        return TakeToWorkResult(
            position_id=position_id,
            status="failed",
            reason="Route is not active",
        )

    # Verify route has active sections
    steps = (
        await db.execute(
            select(RouteStep)
            .where(RouteStep.route_id == route_info.route_id)
            .join(Section, RouteStep.section_id == Section.id)
            .where(Section.is_active == True)
            .order_by(RouteStep.sequence)
        )
    ).scalars().all()

    if not steps:
        return TakeToWorkResult(
            position_id=position_id,
            status="failed",
            reason="Route has no active steps",
        )

    # Create and release batch
    try:
        batch_summary = await create_release_batch(
            db,
            production_plan_id=pos.production_plan_id,
            positions=[{"plan_position_id": position_id, "release_quantity": str(pos.quantity)}],
        )
        release_summary = await release_batch(db, batch_summary["id"])

        return TakeToWorkResult(
            position_id=position_id,
            status="success",
            release_batch_id=batch_summary["id"],
            internal_plan_id=release_summary.get("internal_plan_id"),
            tasks_created=release_summary.get("tasks_created"),
        )
    except ValueError as exc:
        return TakeToWorkResult(
            position_id=position_id,
            status="failed",
            reason=str(exc),
        )
