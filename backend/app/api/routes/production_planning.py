from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WRITER_ROLES, get_current_user, require_role
from app.core.database import get_db
from app.models.internal_plan import SectionPlanLine
from app.models.movement import Movement
from app.models.production_plan import PlanPosition, PlanPositionStatus, ProductionPlan, ProductionPlanStatus
from app.models.transfer import Transfer
from app.models.work_task import WorkTask, WorkTaskStatus
from app.models.route import ProductionRoute, RouteStage
from app.models.section import Section
from app.models.user import User
from app.models.product import Product
from app.models.spg import StorageProductionGroup
from app.models.spg_remainder import SpgRemainder
from app.services.production_planning_rows import get_production_planning_row_detail, list_production_planning_rows
from app.services.production_plan_service import _refresh_plan_status, restore_plan_position, soft_delete_cancelled_position
from app.services.plan_generation import create_release_batch, release_batch
from app.services.route_matcher import resolve_position_route, make_position_route_cache_key
from app.services.shopfloor_service import complete_task, final_release, issue_to_work, transfer_receive, transfer_send

router = APIRouter(prefix="/production-planning", tags=["execution-control"])
MANUAL_ROUTE_PASS_PREFIX = "manual_route_pass:"


class RemainderAllocationItem(BaseModel):
    remainder_id: int
    quantity: Decimal


class TakeToWorkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position_ids: list[int]
    remainder_allocation: list[RemainderAllocationItem] | None = None



class StatusActionIn(BaseModel):
    reason: str | None = None


class CancelBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_ids: list[int]
    reason: str | None = None


class RestoreBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_ids: list[int]
    reason: str | None = None


class BatchActionResult(BaseModel):
    position_id: int
    status: Literal["success", "failed", "skipped"]
    reason: str | None = None


class BatchActionResponse(BaseModel):
    results: list[BatchActionResult]


class ManualPassRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_route_stage_id: int | None = None
    complete_route: bool = False
    comment: str | None = None
    idempotency_key: str | None = None


class ManualPassResponse(BaseModel):
    position_id: int
    target_route_stage_id: int
    target_task_id: int
    complete_route: bool = False
    position_completed: bool = False
    tasks_created: int
    movements_created: int
    transfers_created: int
    skipped_stages: int


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
    route_stage_id: int
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
    is_completed: bool
    current_stage_section_id: int | None = None
    current_stage_sequence: int | None = None
    current_stage_operation: str | None = None
    current_stage_section_code: str | None = None
    current_stage_section_name: str | None = None
    current_stage_task_status: str | None = None
    route_steps: list[dict] | None = None


class PlanningRouteSnapshotStepOut(BaseModel):
    route_stage_id: int
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
        manual_route_pass: bool = False

    route_stage_id: int
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
    route_resolve_cache: dict[tuple, object] = {}
    for pos in positions:
        cache_key = make_position_route_cache_key(pos)
        if cache_key in route_resolve_cache:
            route_info = route_resolve_cache[cache_key]
        else:
            route_info = await resolve_position_route(db, pos)
            route_resolve_cache[cache_key] = route_info
        position_route_map[pos.id] = (route_info.route_id, route_info.route_name, route_info.source)

    # Collect all section IDs from resolved routes
    section_ids: set[int] = set()
    route_stages_cache: dict[int, list[RouteStage]] = {}
    for pos in positions:
        route_id = position_route_map[pos.id][0]
        if route_id is not None:
            if route_id not in route_stages_cache:
                stages = (
                    await db.execute(
                        select(RouteStage)
                        .where(RouteStage.route_id == route_id)
                        .join(Section, RouteStage.section_id == Section.id)
                        .where(Section.is_active == True)
                        .order_by(RouteStage.sequence)
                    )
                ).scalars().all()
                route_stages_cache[route_id] = stages
            for stage in route_stages_cache[route_id]:
                section_ids.add(stage.section_id)

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

                    # Get operation info from route stage
                    stage = await db.get(RouteStage, wt.route_stage_id)
                    work_tasks_out.append(
                        WorkTaskOut(
                            id=wt.id,
                            route_stage_id=wt.route_stage_id,
                            operation_name=", ".join(op.operation_name for op in stage.operations) if stage and stage.operations else None,
                            operation_code=wt.selected_operation_code or (stage.operations[0].operation_code if stage and stage.operations else None),
                            status=wt.status.value if hasattr(wt.status, 'value') else wt.status,
                            planned_quantity=float(wt.planned_quantity),
                            completed_quantity=float(wt.cached_completed_quantity),
                            sequence=stage.sequence if stage else 0,
                        )
                    )

            if not work_tasks_out:
                # No work tasks yet — position is in queue for this section
                # Show it if the route includes this section
                if route_id is not None:
                    stages = route_stages_cache.get(route_id, [])
                    for stage in stages:
                        if stage.section_id == section.id:
                            total_steps += 1
                            work_tasks_out.append(
                                WorkTaskOut(
                                    id=0,
                                    route_stage_id=stage.id,
                                    operation_name=", ".join(op.operation_name for op in stage.operations) if stage.operations else "",
                                    operation_code=stage.operations[0].operation_code if stage.operations else None,
                                    status="waiting",
                                    planned_quantity=float(pos.quantity),
                                    completed_quantity=0.0,
                                    sequence=stage.sequence,
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


async def _collect_task_rows_for_position(
    db: AsyncSession,
    position_id: int,
) -> list[tuple[WorkTask, SectionPlanLine, RouteStage]]:
    return (
        await db.execute(
            select(WorkTask, SectionPlanLine, RouteStage)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .join(RouteStage, WorkTask.route_stage_id == RouteStage.id)
            .where(SectionPlanLine.plan_position_id == position_id)
            .order_by(SectionPlanLine.sequence, WorkTask.id)
        )
    ).all()


async def _position_movement_source_refs(db: AsyncSession, position_id: int) -> list[str | None]:
    return [
        row[0]
        for row in (
            await db.execute(
                select(Movement.source_ref)
                .join(SectionPlanLine, SectionPlanLine.id == Movement.section_plan_line_id)
                .where(SectionPlanLine.plan_position_id == position_id)
            )
        ).all()
    ]


async def _position_transfer_idempotency_keys(db: AsyncSession, position_id: int) -> list[str | None]:
    return [
        row[0]
        for row in (
            await db.execute(
                select(Transfer.idempotency_key)
                .join(WorkTask, WorkTask.id == Transfer.from_task_id)
                .join(SectionPlanLine, SectionPlanLine.id == WorkTask.section_plan_line_id)
                .where(SectionPlanLine.plan_position_id == position_id)
            )
        ).all()
    ]


async def _ensure_manual_pass_can_start_or_replay(
    db: AsyncSession,
    *,
    position_id: int,
    source_ref: str,
) -> bool:
    movement_refs = await _position_movement_source_refs(db, position_id)
    transfer_keys = await _position_transfer_idempotency_keys(db, position_id)
    if not movement_refs and not transfer_keys:
        return False

    same_manual_movements = all(ref == source_ref for ref in movement_refs)
    same_manual_transfers = all(key is not None and key.startswith(f"{source_ref}:") for key in transfer_keys)
    if same_manual_movements and same_manual_transfers:
        return True

    raise ValueError("Position already has execution facts; manual route pass is allowed only before execution starts")


async def _manual_pass_counts(
    db: AsyncSession,
    *,
    position_id: int,
    source_ref: str,
) -> tuple[int, int]:
    movements_count = await db.scalar(
        select(func.count(Movement.id))
        .join(SectionPlanLine, SectionPlanLine.id == Movement.section_plan_line_id)
        .where(
            SectionPlanLine.plan_position_id == position_id,
            Movement.source_ref == source_ref,
        )
    )
    transfer_keys = await _position_transfer_idempotency_keys(db, position_id)
    transfers_count = sum(1 for key in transfer_keys if key is not None and key.startswith(f"{source_ref}:"))
    return int(movements_count or 0), transfers_count


@router.post(
    "/rows/{position_id}/manual-pass",
    response_model=ManualPassResponse,
    dependencies=[Depends(require_role(list(WRITER_ROLES)))],
)
async def manual_pass_to_stage(
    position_id: int,
    payload: ManualPassRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ManualPassResponse:
    return await _do_manual_pass(db, position_id, payload, current_user)


async def _do_manual_pass(
    db: AsyncSession,
    position_id: int,
    payload: ManualPassRequest,
    current_user: User,
) -> ManualPassResponse:
    pos = await db.get(PlanPosition, position_id)
    if pos is None or pos.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Position not found")
    if pos.status not in {PlanPositionStatus.approved, PlanPositionStatus.released}:
        raise HTTPException(status_code=400, detail=f"Position status must be approved or released, got '{pos.status.value}'")

    base_key = (payload.idempotency_key or uuid4().hex).strip()
    if not base_key:
        base_key = uuid4().hex
    source_ref = f"{MANUAL_ROUTE_PASS_PREFIX}{base_key}"
    is_replay = False
    try:
        is_replay = await _ensure_manual_pass_can_start_or_replay(db, position_id=position_id, source_ref=source_ref)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing_lines = await db.scalar(
        select(func.count(SectionPlanLine.id)).where(SectionPlanLine.plan_position_id == position_id)
    )
    tasks_created = 0
    if not existing_lines:
        if pos.status not in {PlanPositionStatus.approved, PlanPositionStatus.released}:
            raise HTTPException(status_code=400, detail="Position has no tasks and cannot be released from current status")
        result = await _process_position_take_to_work(db, position_id)
        if result.status != "success":
            raise HTTPException(status_code=400, detail=result.reason or "Unable to create route tasks")
        tasks_created = int(result.tasks_created or 0)

    task_rows = await _collect_task_rows_for_position(db, position_id)
    if not task_rows:
        raise HTTPException(status_code=400, detail="Position has no route tasks")

    complete_route = bool(payload.complete_route)
    if complete_route:
        target_index = len(task_rows) - 1
        target_route_stage_id = task_rows[target_index][2].id
        stages_to_execute = len(task_rows)
    else:
        if payload.target_route_stage_id is None:
            raise HTTPException(status_code=400, detail="target_route_stage_id is required unless complete_route is true")
        target_index: int | None = None
        for idx, (_task, _line, stage) in enumerate(task_rows):
            if stage.id == payload.target_route_stage_id:
                target_index = idx
                break
        if target_index is None:
            raise HTTPException(status_code=400, detail="target_route_stage_id not found in this position route")
        target_route_stage_id = payload.target_route_stage_id
        stages_to_execute = target_index

    target_task = task_rows[target_index][0]
    if not is_replay:
        now = datetime.now(UTC)
        target_stage = task_rows[target_index][2]
        manual_comment = payload.comment or (
            "Ручной сквозной проход: полное завершение"
            if complete_route
            else f"Ручной сквозной проход до этапа #{target_stage.sequence}"
        )

        for idx in range(stages_to_execute):
            task, _line, stage = task_rows[idx]
            next_task = task_rows[idx + 1][0] if idx < len(task_rows) - 1 else None
            quantity = Decimal(str(task.planned_quantity))
            operation_key = f"{source_ref}:step:{stage.sequence}"

            try:
                await db.refresh(task)
                issued_qty = Decimal(str(task.cached_issued_quantity or 0))
                to_issue = quantity - issued_qty
                if to_issue > 0:
                    await issue_to_work(
                        db,
                        task_id=task.id,
                        quantity=to_issue,
                        actor_id=current_user.id,
                        comment=manual_comment,
                        source_ref=source_ref,
                        idempotency_key=f"{operation_key}:issue",
                        executor_user_id=current_user.id,
                        performed_at=now,
                        accounted_at=now,
                    )
                
                completed_qty = Decimal(str(task.cached_completed_quantity or 0)) + Decimal(str(task.cached_rejected_quantity or 0))
                to_complete = quantity - completed_qty
                if to_complete > 0:
                    await complete_task(
                        db,
                        task_id=task.id,
                        good_quantity=to_complete,
                        defect_quantity=Decimal("0"),
                        actor_id=current_user.id,
                        comment=manual_comment,
                        source_ref=source_ref,
                        idempotency_key=f"{operation_key}:complete",
                        executor_user_id=current_user.id,
                        performed_at=now,
                        accounted_at=now,
                    )
                if next_task is not None:
                    from app.services.shopfloor.common import sections_share_spg
                    if not await sections_share_spg(db, task.section_id, next_task.section_id):
                        transfer_result = await transfer_send(
                            db,
                            from_task_id=task.id,
                            to_task_id=next_task.id,
                            quantity=quantity,
                            actor_id=current_user.id,
                            comment=manual_comment,
                            source_ref=source_ref,
                            idempotency_key=f"{operation_key}:transfer",
                            executor_user_id=current_user.id,
                            performed_at=now,
                            accounted_at=now,
                        )
                        await transfer_receive(
                            db,
                            transfer_id=int(transfer_result["transfer_id"]),
                            accepted_quantity=quantity,
                            rejected_quantity=Decimal("0"),
                            actor_id=current_user.id,
                            reason="manual_route_pass",
                            comment=manual_comment,
                            source_ref=source_ref,
                            idempotency_key=f"{operation_key}:receive",
                            executor_user_id=current_user.id,
                            performed_at=now,
                            accounted_at=now,
                        )
                elif stage.is_final:
                    await final_release(
                        db,
                        task_id=task.id,
                        quantity=quantity,
                        actor_id=current_user.id,
                        comment=manual_comment,
                        idempotency_key=f"{operation_key}:final_release",
                        executor_user_id=current_user.id,
                        performed_at=now,
                        accounted_at=now,
                    )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"Manual pass failed at step {stage.sequence}: {exc}") from exc

    movements_created, transfers_created = await _manual_pass_counts(db, position_id=position_id, source_ref=source_ref)
    total_tasks = await db.scalar(
        select(func.count(WorkTask.id))
        .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
        .where(SectionPlanLine.plan_position_id == position_id)
    )
    completed_tasks = await db.scalar(
        select(func.count(WorkTask.id))
        .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
        .where(
            SectionPlanLine.plan_position_id == position_id,
            WorkTask.status == WorkTaskStatus.completed,
        )
    )
    position_completed = bool(total_tasks and completed_tasks == total_tasks)
    return ManualPassResponse(
        position_id=position_id,
        target_route_stage_id=target_route_stage_id,
        target_task_id=target_task.id,
        complete_route=complete_route,
        position_completed=position_completed,
        tasks_created=tasks_created,
        movements_created=movements_created,
        transfers_created=transfers_created,
        skipped_stages=stages_to_execute,
    )


@router.get("/rows/{position_id}/remainders-preview", dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def get_remainders_preview(
    position_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Preview available compatible remainders for a plan position and get default FIFO allocation."""
    pos = await db.get(PlanPosition, position_id)
    if pos is None:
        raise HTTPException(status_code=404, detail="Plan position not found")

    product = None
    if pos.product_id is not None:
        product = await db.get(Product, pos.product_id)

    route_info = await resolve_position_route(db, pos)
    if route_info.route_id is None:
        return {
            "position_id": position_id,
            "product_sku": product.sku if product else None,
            "product_name": product.name if product else None,
            "release_quantity": float(pos.quantity),
            "route_steps": [],
            "available_remainders": [],
            "default_allocation": [],
        }


    rows = (
        await db.execute(
            select(RouteStage, Section)
            .where(RouteStage.route_id == route_info.route_id)
            .join(Section, RouteStage.section_id == Section.id)
            .where(Section.is_active == True)
            .order_by(RouteStage.sequence)
        )
    ).all()

    route_steps = []
    route_seq_to_section = {}
    for stage, section in rows:
        op_name = ", ".join(op.operation_name for op in stage.operations) if stage.operations else "Операция"
        route_steps.append({
            "sequence": stage.sequence,
            "section_id": stage.section_id,
            "section_name": section.name,
            "section_code": section.code,
            "operation_name": op_name,
        })
        route_seq_to_section[stage.sequence] = stage.section_id

    effective_product_id = pos.product_id

    if effective_product_id is None:
        from app.services.plan_generation import _find_paired_techcard, _paired_component_skus
        paired_techcard = await _find_paired_techcard(db, _paired_component_skus(pos))
        if paired_techcard is not None:
            from app.models.techcard import TechcardLine
            first_component = await db.scalar(
                select(TechcardLine.component_product_id)
                .where(TechcardLine.techcard_id == paired_techcard.id)
                .limit(1)
            )
            effective_product_id = first_component

    available_remainders = []
    if effective_product_id is not None:
        from sqlalchemy import or_
        free_remainders = (
            await db.execute(
                select(SpgRemainder, Product.sku, Product.name, StorageProductionGroup.name)
                .join(Product, SpgRemainder.product_id == Product.id)
                .join(StorageProductionGroup, SpgRemainder.spg_id == StorageProductionGroup.id)
                .where(
                    SpgRemainder.product_id == effective_product_id,
                    SpgRemainder.remainder_quantity > 0,
                    SpgRemainder.consumed_at.is_(None),
                    or_(
                        SpgRemainder.reserved_for_plan_position_id.is_(None),
                        SpgRemainder.reserved_for_plan_position_id == position_id,
                    )
                )
                .order_by(SpgRemainder.created_at)
            )
        ).all()

        for rem, prod_sku, prod_name, spg_name in free_remainders:
            stages_json = rem.completed_stages_json or []

            is_prefix = True
            for stage_entry in stages_json:
                seq = stage_entry.get("sequence")
                section_id = stage_entry.get("section_id")
                if seq is None or section_id is None:
                    is_prefix = False
                    break
                expected_section = route_seq_to_section.get(seq)
                if expected_section is None or expected_section != section_id:
                    is_prefix = False
                    break

            if not is_prefix:
                continue

            max_seq = max((s.get("sequence", 0) for s in stages_json), default=0)
            max_completed_stage_name = ""
            for s in stages_json:
                if s.get("sequence") == max_seq:
                    max_completed_stage_name = s.get("operation_name") or s.get("operation_code") or ""

            available_remainders.append({
                "id": rem.id,
                "remainder_quantity": float(rem.remainder_quantity),
                "original_issued": float(rem.original_issued),
                "created_at": rem.created_at.isoformat() if rem.created_at else None,
                "created_by_user_name": rem.created_by_user_name,
                "completed_stages_json": stages_json,
                "max_completed_seq": max_seq,
                "max_completed_stage_name": max_completed_stage_name,
                "spg_name": spg_name,
            })

    default_allocation = []
    remaining_to_cover = pos.quantity
    for rem_info in available_remainders:
        if remaining_to_cover <= 0:
            break
        qty_to_use = min(Decimal(str(rem_info["remainder_quantity"])), remaining_to_cover)
        default_allocation.append({
            "remainder_id": rem_info["id"],
            "allocated_quantity": float(qty_to_use),
        })
        remaining_to_cover -= qty_to_use

    return {
        "position_id": position_id,
        "product_sku": product.sku if product else None,
        "product_name": product.name if product else None,
        "release_quantity": float(pos.quantity),
        "route_steps": route_steps,
        "available_remainders": available_remainders,
        "default_allocation": default_allocation,
    }


@router.post("/rows/take-to-work", response_model=TakeToWorkResponse, dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def take_rows_to_work(
    payload: TakeToWorkRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TakeToWorkResponse:
    """Launch plan positions into production: create work tasks for all route stages."""
    results: list[TakeToWorkResult] = []

    allocation_dict = None
    if payload.remainder_allocation:
        allocation_dict = {item.remainder_id: item.quantity for item in payload.remainder_allocation}

    for position_id in payload.position_ids:
        try:
            result = await _process_position_take_to_work(
                db,
                position_id,
                remainder_allocation=allocation_dict if len(payload.position_ids) == 1 else None,
            )
            results.append(result)
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.exception(f"take-to-work failed for position {position_id}")
            results.append(TakeToWorkResult(
                position_id=position_id,
                status="failed",
                reason=f"Internal error: {str(exc)}",
            ))

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

    # Release SPG remainder reservations for this position
    from app.models.spg_remainder import SpgRemainder
    reserved_remainders = (
        await db.execute(
            select(SpgRemainder).where(SpgRemainder.reserved_for_plan_position_id == position_id)
        )
    ).scalars().all()
    for rem in reserved_remainders:
        rem.reserved_for_plan_position_id = None

    from_status = pos.status.value
    pos.status = PlanPositionStatus.cancelled

    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction, AuditEntityType
    await log_action(
        db,
        status="success",
        title="Отмена позиции",
        message=f"Позиция #{position_id} отменена (предыдущий статус: '{from_status}').",
        user_id=current_user.id,
        action=AuditAction.CANCEL,
        entity_type=AuditEntityType.PLAN_POSITION,
        entity_id=position_id,
        changes={"before": {"status": from_status}, "after": {"status": PlanPositionStatus.cancelled.value}},
        comment=payload.reason if payload else None,
    )

    await _refresh_plan_status(db, pos.production_plan_id)
    await db.commit()

    return {
        "id": pos.id,
        "production_plan_id": pos.production_plan_id,
        "status": pos.status.value,
    }


@router.post(
    "/rows/cancel-batch",
    response_model=BatchActionResponse,
    dependencies=[Depends(require_role(list(WRITER_ROLES)))],
)
async def cancel_positions_batch(
    payload: CancelBatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BatchActionResponse:
    import logging
    logger = logging.getLogger(__name__)

    plan_ids: set[int] = set()
    results: list[BatchActionResult] = []
    for position_id in payload.position_ids:
        try:
            async with db.begin_nested():
                result = await _process_position_cancel(
                    db, position_id, current_user.id, payload.reason
                )
                results.append(result)
                if result.status == "success":
                    pos = await db.get(PlanPosition, position_id)
                    if pos:
                        plan_ids.add(pos.production_plan_id)
        except Exception as exc:
            logger.exception("cancel_positions_batch: unexpected error for id %s", position_id)
            results.append(
                BatchActionResult(
                    position_id=position_id,
                    status="failed",
                    reason="Внутренняя ошибка сервера",
                )
            )
    for plan_id in plan_ids:
        await _refresh_plan_status(db, plan_id)
    return BatchActionResponse(results=results)


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

    # Find last cancellation history record from audit_logs
    from app.models.audit_log import AuditLog, AuditAction, AuditEntityType
    from sqlalchemy import select
    last_cancel = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.entity_type == AuditEntityType.PLAN_POSITION.value,
                AuditLog.entity_id == position_id,
                AuditLog.action == AuditAction.CANCEL.value,
            )
            .order_by(AuditLog.created_at.desc())
        )
    ).scalars().first()

    if last_cancel is None or not last_cancel.changes or "before" not in last_cancel.changes:
        raise HTTPException(status_code=400, detail="Нет истории отмены — восстановление невозможно")

    target_status_value = last_cancel.changes["before"].get("status")
    if target_status_value not in {PlanPositionStatus.approved.value, PlanPositionStatus.released.value}:
        raise HTTPException(status_code=400, detail=f"Недопустимый статус для восстановления: '{target_status_value}'")

    pos.status = PlanPositionStatus(target_status_value)
    
    from app.services.audit_log_service import log_action
    await log_action(
        db,
        status="success",
        title="Восстановление позиции",
        message=f"Позиция #{position_id} восстановлена из отмененных в статус '{target_status_value}'.",
        user_id=current_user.id,
        action=AuditAction.RESTORE,
        entity_type=AuditEntityType.PLAN_POSITION,
        entity_id=position_id,
        changes={"before": {"status": PlanPositionStatus.cancelled.value}, "after": {"status": target_status_value}},
        comment=payload.reason if payload else None,
    )
    
    await _refresh_plan_status(db, pos.production_plan_id)
    await db.commit()

    return {
        "id": pos.id,
        "production_plan_id": pos.production_plan_id,
        "status": pos.status.value,
    }


@router.post(
    "/rows/restore-batch",
    response_model=BatchActionResponse,
    dependencies=[Depends(require_role(list(WRITER_ROLES)))],
)
async def restore_positions_batch(
    payload: RestoreBatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BatchActionResponse:
    import logging
    logger = logging.getLogger(__name__)

    plan_ids: set[int] = set()
    results: list[BatchActionResult] = []
    for position_id in payload.position_ids:
        try:
            async with db.begin_nested():
                result = await _process_position_restore(
                    db, position_id, current_user.id, payload.reason
                )
                results.append(result)
                if result.status == "success":
                    pos = await db.get(PlanPosition, position_id)
                    if pos:
                        plan_ids.add(pos.production_plan_id)
        except Exception as exc:
            logger.exception("restore_positions_batch: unexpected error for id %s", position_id)
            results.append(
                BatchActionResult(
                    position_id=position_id,
                    status="failed",
                    reason="Внутренняя ошибка сервера",
                )
            )
    for plan_id in plan_ids:
        await _refresh_plan_status(db, plan_id)
    return BatchActionResponse(results=results)


# --- New bulk endpoints with savepoint isolation ----------------------------


class SoftDeleteBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_ids: list[int]
    reason: str | None = None


@router.post(
    "/rows/soft-delete-batch",
    response_model=BatchActionResponse,
    dependencies=[Depends(require_role(list(WRITER_ROLES)))],
)
async def soft_delete_positions_batch(
    payload: SoftDeleteBatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BatchActionResponse:
    """Soft-delete multiple cancelled positions in a single request.

    Each position is processed in a savepoint; failures on one row
    never roll back the rest of the batch.
    """
    import logging
    logger = logging.getLogger(__name__)

    results: list[BatchActionResult] = []
    for position_id in payload.position_ids:
        try:
            async with db.begin_nested():
                pos = await db.get(PlanPosition, position_id)
                if pos is None or pos.deleted_at is not None:
                    raise ValueError("Position not found")
                if pos.status != PlanPositionStatus.cancelled:
                    results.append(
                        BatchActionResult(
                            position_id=position_id,
                            status="skipped",
                            reason=f"Статус '{pos.status.value}' — можно удалять только отменённые позиции",
                        )
                    )
                    continue
                await soft_delete_cancelled_position(
                    db,
                    pos.production_plan_id,
                    position_id,
                    changed_by=current_user.id,
                    reason=payload.reason or "Удалена из списка",
                )
                results.append(BatchActionResult(position_id=position_id, status="success"))
        except ValueError as exc:
            results.append(BatchActionResult(position_id=position_id, status="failed", reason=str(exc)))
        except Exception as exc:
            logger.exception("soft_delete_positions_batch: unexpected error for id %s", position_id)
            results.append(
                BatchActionResult(position_id=position_id, status="failed", reason="Внутренняя ошибка сервера")
            )
    return BatchActionResponse(results=results)


class ManualPassBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_ids: list[int]
    target_route_stage_id: int | None = None
    complete_route: bool = False
    comment: str | None = None
    idempotency_key: str | None = None


class ManualPassBatchResult(BaseModel):
    position_id: int
    status: Literal["success", "failed", "skipped"]
    reason: str | None = None
    movements_created: int | None = None
    transfers_created: int | None = None
    tasks_created: int | None = None
    position_completed: bool | None = None


class ManualPassBatchResponse(BaseModel):
    results: list[ManualPassBatchResult]


@router.post(
    "/rows/manual-pass-batch",
    response_model=ManualPassBatchResponse,
    dependencies=[Depends(require_role(list(WRITER_ROLES)))],
)
async def manual_pass_positions_batch(
    payload: ManualPassBatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ManualPassBatchResponse:
    """Run a manual through-pass for many positions in a single request.

    Each position runs in a savepoint so the failure of one position
    does not poison the others.
    """
    import logging
    logger = logging.getLogger(__name__)

    base_key = (payload.idempotency_key or uuid4().hex).strip() or uuid4().hex
    results: list[ManualPassBatchResult] = []

    for index, position_id in enumerate(payload.position_ids):
        per_position_key = f"{base_key}:{index}"
        try:
            async with db.begin_nested():
                result = await _do_manual_pass(
                    db,
                    position_id,
                    ManualPassRequest(
                        target_route_stage_id=payload.target_route_stage_id,
                        complete_route=payload.complete_route,
                        comment=payload.comment,
                        idempotency_key=per_position_key,
                    ),
                    current_user,
                )
                results.append(
                    ManualPassBatchResult(
                        position_id=position_id,
                        status="success",
                        movements_created=result.movements_created,
                        transfers_created=result.transfers_created,
                        tasks_created=result.tasks_created,
                        position_completed=result.position_completed,
                    )
                )
        except HTTPException as exc:
            results.append(
                ManualPassBatchResult(
                    position_id=position_id,
                    status="failed",
                    reason=str(exc.detail),
                )
            )
        except ValueError as exc:
            results.append(ManualPassBatchResult(position_id=position_id, status="failed", reason=str(exc)))
        except Exception as exc:
            logger.exception("manual_pass_positions_batch: unexpected error for id %s", position_id)
            results.append(
                ManualPassBatchResult(position_id=position_id, status="failed", reason="Внутренняя ошибка сервера")
            )
    return ManualPassBatchResponse(results=results)


async def _process_position_cancel(
    db: AsyncSession,
    position_id: int,
    current_user_id: int | None,
    reason: str | None,
) -> BatchActionResult:
    pos = await db.get(PlanPosition, position_id)
    if pos is None or pos.deleted_at is not None:
        return BatchActionResult(position_id=position_id, status="failed", reason="Position not found")
    if pos.status == PlanPositionStatus.cancelled:
        return BatchActionResult(position_id=position_id, status="skipped", reason="Position is already cancelled")
    if pos.status not in {PlanPositionStatus.approved, PlanPositionStatus.released}:
        return BatchActionResult(
            position_id=position_id,
            status="failed",
            reason=f"Нельзя отменить позицию со статусом '{pos.status.value}'",
        )

    # Release SPG remainder reservations for this position
    from app.models.spg_remainder import SpgRemainder
    reserved_remainders = (
        await db.execute(
            select(SpgRemainder).where(SpgRemainder.reserved_for_plan_position_id == position_id)
        )
    ).scalars().all()
    for rem in reserved_remainders:
        rem.reserved_for_plan_position_id = None

    from_status = pos.status.value
    pos.status = PlanPositionStatus.cancelled

    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction, AuditEntityType
    await log_action(
        db,
        status="success",
        title="Отмена позиции",
        message=f"Позиция #{position_id} отменена в пакете (предыдущий статус: '{from_status}').",
        user_id=current_user_id,
        action=AuditAction.CANCEL,
        entity_type=AuditEntityType.PLAN_POSITION,
        entity_id=position_id,
        changes={"before": {"status": from_status}, "after": {"status": PlanPositionStatus.cancelled.value}},
        comment=reason,
    )
    return BatchActionResult(position_id=position_id, status="success")



async def _process_position_restore(
    db: AsyncSession,
    position_id: int,
    current_user_id: int | None,
    reason: str | None,
) -> BatchActionResult:
    pos = await db.get(PlanPosition, position_id)
    if pos is None or pos.deleted_at is not None:
        return BatchActionResult(position_id=position_id, status="failed", reason="Position not found")
    if pos.status in {PlanPositionStatus.approved, PlanPositionStatus.released}:
        return BatchActionResult(position_id=position_id, status="skipped", reason="Position is already active")
    if pos.status != PlanPositionStatus.cancelled:
        return BatchActionResult(
            position_id=position_id,
            status="failed",
            reason=f"Нельзя восстановить позицию со статусом '{pos.status.value}'",
        )

    # Find last cancellation history record from audit_logs
    from app.models.audit_log import AuditLog, AuditAction, AuditEntityType
    last_cancel = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.entity_type == AuditEntityType.PLAN_POSITION.value,
                AuditLog.entity_id == position_id,
                AuditLog.action == AuditAction.CANCEL.value,
            )
            .order_by(AuditLog.created_at.desc())
        )
    ).scalars().first()

    if last_cancel is None or not last_cancel.changes or "before" not in last_cancel.changes:
        return BatchActionResult(position_id=position_id, status="failed", reason="Нет истории отмены — восстановление невозможно")

    target_status_value = last_cancel.changes["before"].get("status")
    if target_status_value not in {PlanPositionStatus.approved.value, PlanPositionStatus.released.value}:
        return BatchActionResult(
            position_id=position_id,
            status="failed",
            reason=f"Недопустимый статус для восстановления: '{target_status_value}'",
        )

    pos.status = PlanPositionStatus(target_status_value)
    
    from app.services.audit_log_service import log_action
    await log_action(
        db,
        status="success",
        title="Восстановление позиции",
        message=f"Позиция #{position_id} восстановлена из отмененных в статус '{target_status_value}' в пакете.",
        user_id=current_user_id,
        action=AuditAction.RESTORE,
        entity_type=AuditEntityType.PLAN_POSITION,
        entity_id=position_id,
        changes={"before": {"status": PlanPositionStatus.cancelled.value}, "after": {"status": target_status_value}},
        comment=reason,
    )
    return BatchActionResult(position_id=position_id, status="success")


async def _process_position_take_to_work(
    db: AsyncSession,
    position_id: int,
    remainder_allocation: dict[int, Decimal] | None = None,
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

    # Check position is approved or released
    if pos.status not in {PlanPositionStatus.approved, PlanPositionStatus.released}:
        return TakeToWorkResult(
            position_id=position_id,
            status="failed",
            reason=f"Position status is '{pos.status.value}', must be 'approved' or 'released'",
        )

    # Check parent production plan is in a launchable state. If the plan status
    # drifted out of sync with its positions (e.g. plan='released' but no
    # positions are released yet), self-heal by re-deriving the status from the
    # positions before failing.
    plan = await db.get(ProductionPlan, pos.production_plan_id)
    if plan is not None and plan.status not in {
        ProductionPlanStatus.approved,
        ProductionPlanStatus.partially_released,
    }:
        await _refresh_plan_status(db, plan.id)
        await db.flush()
        await db.refresh(plan)
        if plan.status not in {
            ProductionPlanStatus.approved,
            ProductionPlanStatus.partially_released,
        }:
            return TakeToWorkResult(
                position_id=position_id,
                status="failed",
                reason=(
                    f"Production plan status is '{plan.status.value}'; "
                    "only 'approved' or 'partially_released' plans can be launched"
                ),
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
    stages = (
        await db.execute(
            select(RouteStage)
            .where(RouteStage.route_id == route_info.route_id)
            .join(Section, RouteStage.section_id == Section.id)
            .where(Section.is_active == True)
            .order_by(RouteStage.sequence)
        )
    ).scalars().all()

    if not stages:
        return TakeToWorkResult(
            position_id=position_id,
            status="failed",
            reason="Route has no active stages",
        )

    # Create and release batch
    try:
        batch_summary = await create_release_batch(
            db,
            production_plan_id=pos.production_plan_id,
            positions=[{"plan_position_id": position_id, "release_quantity": str(pos.quantity)}],
        )
        release_summary = await release_batch(db, batch_summary["id"], remainder_allocation=remainder_allocation)

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
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.exception(f"take-to-work failed for position {position_id}: {exc}")
        return TakeToWorkResult(
            position_id=position_id,
            status="failed",
            reason=f"Internal error: {str(exc)}",
        )


class ProductWipRemainderOut(BaseModel):
    spg_id: int
    spg_code: str
    spg_name: str
    completed_ops: str
    spg_icon: str | None = None
    spg_icon_color: str | None = None
    quantity: float

class ProductWipTaskOut(BaseModel):
    section_id: int
    section_code: str
    section_name: str
    operation_name: str
    section_icon: str | None = None
    section_icon_color: str | None = None
    planned_qty: float
    completed_qty: float
    in_work_qty: float
    active_tasks_count: int

class ProductWipStatsOut(BaseModel):
    sku: str
    product_name: str
    product_id: int | None = None
    remainders: list[ProductWipRemainderOut]
    in_work: list[ProductWipTaskOut]


@router.get("/product-wip-stats/{sku}", response_model=ProductWipStatsOut)
async def get_product_wip_stats(
    sku: str,
    db: AsyncSession = Depends(get_db),
):
    # 1. Поиск продукта по артикулу
    product = (
        await db.execute(select(Product).where(Product.sku == sku))
    ).scalar_one_or_none()
    
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # 2. Поиск остатков на СПГ (ГХП)
    rem_q = (
        select(SpgRemainder, StorageProductionGroup)
        .join(StorageProductionGroup, SpgRemainder.spg_id == StorageProductionGroup.id)
        .where(SpgRemainder.product_id == product.id)
        .where(SpgRemainder.consumed_at.is_(None))
    )
    rem_rows = (await db.execute(rem_q)).all()

    # Группируем остатки по ГХП и пройденным операциям в Python-коде
    rem_grouped: dict[tuple[int, str], dict] = {}
    for rem, spg in rem_rows:
        stages = rem.completed_stages_json or []
        if not stages:
            ops_str = "Без обработки"
        else:
            ops_str = ", ".join(s.get("operation_name") or s.get("operation_code") or "" for s in stages)

        key = (spg.id, ops_str)
        if key not in rem_grouped:
            rem_grouped[key] = {
                "spg_id": spg.id,
                "spg_code": spg.code,
                "spg_name": spg.name,
                "spg_icon": spg.icon,
                "spg_icon_color": spg.icon_color,
                "completed_ops": ops_str,
                "quantity": 0.0,
            }
        rem_grouped[key]["quantity"] += float(rem.remainder_quantity or 0)

    remainders = [
        ProductWipRemainderOut(
            spg_id=val["spg_id"],
            spg_code=val["spg_code"],
            spg_name=val["spg_name"],
            completed_ops=val["completed_ops"],
            spg_icon=val["spg_icon"],
            spg_icon_color=val["spg_icon_color"],
            quantity=val["quantity"],
        )
        for val in rem_grouped.values()
        if val["quantity"] != 0.0
    ]

    # 3. Поиск активных задач в работе (ready, in_progress)
    from sqlalchemy.orm import selectinload

    work_q = (
        select(WorkTask, Section, RouteStage)
        .join(Section, WorkTask.section_id == Section.id)
        .join(RouteStage, WorkTask.route_stage_id == RouteStage.id)
        .options(selectinload(RouteStage.operations))
        .where(WorkTask.product_id == product.id)
        .where(WorkTask.status.in_([WorkTaskStatus.ready, WorkTaskStatus.in_progress]))
    )
    work_rows = (await db.execute(work_q)).all()

    # Группируем задачи по секциям и операциям в Python-коде
    grouped: dict[tuple[int, str], dict] = {}
    for wt, sec, stage in work_rows:
        op_name = "Неизвестная операция"
        if wt.selected_operation_code and stage.operations:
            for op in stage.operations:
                if op.operation_code == wt.selected_operation_code:
                    op_name = op.operation_name
                    break
            else:
                op_name = stage.operations[0].operation_name
        elif stage.operations:
            op_name = stage.operations[0].operation_name

        key = (sec.id, op_name)
        if key not in grouped:
            grouped[key] = {
                "section_id": sec.id,
                "section_code": sec.code,
                "section_name": sec.name,
                "section_icon": sec.icon,
                "section_icon_color": sec.icon_color,
                "operation_name": op_name,
                "planned_qty": 0.0,
                "completed_qty": 0.0,
                "in_work_qty": 0.0,
                "active_tasks_count": 0,
            }

        grouped[key]["planned_qty"] += float(wt.planned_quantity or 0)
        grouped[key]["completed_qty"] += float(wt.cached_completed_quantity or 0)
        grouped[key]["in_work_qty"] += float(wt.cached_in_work_quantity or 0)
        grouped[key]["active_tasks_count"] += 1

    in_work = [
        ProductWipTaskOut(
            section_id=val["section_id"],
            section_code=val["section_code"],
            section_name=val["section_name"],
            operation_name=val["operation_name"],
            section_icon=val["section_icon"],
            section_icon_color=val["section_icon_color"],
            planned_qty=val["planned_qty"],
            completed_qty=val["completed_qty"],
            in_work_qty=val["in_work_qty"],
            active_tasks_count=val["active_tasks_count"],
        )
        for val in grouped.values()
    ]

    return ProductWipStatsOut(
        sku=product.sku,
        product_name=product.name,
        product_id=product.id,
        remainders=remainders,
        in_work=in_work
    )
