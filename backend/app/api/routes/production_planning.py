from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WRITER_ROLES, get_current_user, require_role
from app.core.database import get_db
from app.models.internal_plan import SectionPlanLine
from app.models.production_plan import PlanPosition, PlanPositionStatus, ProductionPlan, ProductionPlanStatus
from app.models.transfer import Transfer
from app.models.work_task import WorkTask, WorkTaskStatus
from app.models.route import ProductionRoute, RouteStage, SectionOperation
from app.models.section import Section
from app.models.user import User
from app.models.product import Product
from app.models.spg import SpgSection, StorageProductionGroup
from app.seeds.canon.dependencies import get_plant_config
from app.seeds.canon.models import PlantConfig
from app.services.production_planning_rows import (
    PlanningRowsQueryParams,
    get_production_planning_row_detail,
    list_production_planning_rows,
)
from app.domain.dimensions import DIMENSIONLESS_LABEL, canonicalize_dimensions, format_dimensions
from app.services.production_plan_service import _refresh_plan_status, restore_plan_position, soft_delete_cancelled_position
from app.services.plan_generation import create_release_batch, release_batch
from app.services.plan_position_hanger import task_dimensions_for_plan_line
from app.services.route_matcher import resolve_position_route, make_position_route_cache_key
from app.services.route_storage_classifier import STOCK_TYPES
from app.services.shopfloor_service import complete_task, final_release, transfer_send

router = APIRouter(prefix="/production-planning", tags=["execution-control"])
MANUAL_ROUTE_PASS_PREFIX = "manual_route_pass:"


class RemainderAllocationItem(BaseModel):
    remainder_id: int
    quantity: Decimal


class TakeToWorkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position_ids: list[int]
    remainder_allocation: list[RemainderAllocationItem] | None = None
    release_quantity: Decimal | None = None



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
    section_type: str
    positions_count: int
    ready_count: int
    in_progress_count: int
    completed_count: int
    positions: list[PositionOut]


class ProductionPlanningOverview(BaseModel):
    sections: list[SectionOut]


class PlanningRowsListResponse(BaseModel):
    rows: list["PlanningRowOut"]
    total: int
    limit: int
    offset: int


class PlanningRowOut(BaseModel):
    plan_position_id: int
    production_plan_id: int
    source_row_number: int | None
    source_sku: str
    source_name: str | None
    quantity: float
    dimensions: dict | None = None
    dimensions_label: str | None = None
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
    available_remainder_quantity: float | None = None


class PlanningRouteSnapshotStepOut(BaseModel):
    route_stage_id: int
    sequence: int
    section_id: int
    section_code: str
    section_name: str
    section_type: str | None
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
        from_section_name: str | None = None
        to_section_name: str | None = None
        manual_route_pass: bool = False

    route_stage_id: int
    section_id: int
    section_code: str
    section_name: str
    section_type: str | None = None
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


class PositionStatusHistoryOut(BaseModel):
    id: int
    from_status: str
    to_status: str
    changed_by: int | None = None
    changed_at: str
    reason: str | None = None


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
    status_history: list[PositionStatusHistoryOut] = Field(default_factory=list)
    raw_excel_row: dict | None = None
    payload: dict | None = None
    available_remainder_quantity: float | None = None


@router.get("/rows", response_model=PlanningRowsListResponse)
async def list_rows(
    section_id: int | None = Query(default=None),
    search: str | None = Query(default=None),
    sort_by: str | None = Query(default=None),
    sort_order: str = Query(default="desc"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    plan_position_id: str | None = Query(default=None, description="Column filter: position id"),
    source_row_number: str | None = Query(default=None, description="Column filter: source row number"),
    production_plan_id: str | None = Query(default=None, description="Column filter: production plan id"),
    product_sku: str | None = Query(default=None, description="Column filter: product/source sku"),
    source_sku: str | None = Query(default=None, description="Alias for product_sku column filter"),
    source_name: str | None = Query(default=None, description="Column filter: source name"),
    quantity: str | None = Query(default=None, description="Column filter: planned quantity"),
    route_name: str | None = Query(default=None, description="Column filter: route name"),
    status: str | None = Query(default=None, description="Column filter: position status or completed"),
    current_stage_section_name: str | None = Query(
        default=None,
        description="Column filter: current stage section name",
    ),
    dimensions: str | None = Query(
        default=None,
        description='Column filter: exact JSON match on position task dimensions, e.g. {"length_mm":2700} or null',
    ),
    db: AsyncSession = Depends(get_db),
):
    from app.domain.dimensions import DimensionsValidationError, parse_dimensions_filter

    try:
        parse_dimensions_filter(dimensions)
    except DimensionsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    params = PlanningRowsQueryParams(
        section_id=section_id,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
        plan_position_id=plan_position_id,
        source_row_number=source_row_number,
        production_plan_id=production_plan_id,
        product_sku=product_sku,
        source_sku=source_sku,
        source_name=source_name,
        quantity=quantity,
        route_name=route_name,
        status=status,
        current_stage_section_name=current_stage_section_name,
        dimensions=dimensions,
    )
    return await list_production_planning_rows(db, params=params)


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
                    from app.stock.services import StockProjectionManager
                    pm = StockProjectionManager()
                    wt_cache = await pm.get_task_cache(db, wt.id)

                    stage = await db.get(RouteStage, wt.route_stage_id)
                    work_tasks_out.append(
                        WorkTaskOut(
                            id=wt.id,
                            route_stage_id=wt.route_stage_id,
                            operation_name=", ".join(op.operation_name for op in stage.operations) if stage and stage.operations else None,
                            operation_code=wt.selected_operation_code or (stage.operations[0].operation_code if stage and stage.operations else None),
                            status=wt.status.value if hasattr(wt.status, 'value') else wt.status,
                            planned_quantity=float(wt.planned_quantity),
                            completed_quantity=float(wt_cache["completed_quantity"]),
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
                section_type=section.type,
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


_STOCK_SECTION_TYPES = STOCK_TYPES


async def _find_preceding_stock_line(
    db: AsyncSession,
    *,
    plan_position_id: int,
    before_sequence: int,
) -> tuple[SectionPlanLine, Section] | None:
    row = (
        await db.execute(
            select(SectionPlanLine, Section)
            .join(Section, Section.id == SectionPlanLine.section_id)
            .where(
                SectionPlanLine.plan_position_id == plan_position_id,
                SectionPlanLine.sequence < before_sequence,
                Section.type.in_(_STOCK_SECTION_TYPES),
            )
            .order_by(SectionPlanLine.sequence.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return row[0], row[1]


async def _get_or_create_stock_fake_task(
    db: AsyncSession,
    *,
    stock_line: SectionPlanLine,
    stock_section: Section,
    product_id: int,
) -> WorkTask:
    fake_task = await db.scalar(
        select(WorkTask)
        .where(
            WorkTask.section_plan_line_id == stock_line.id,
            WorkTask.status != WorkTaskStatus.cancelled,
        )
        .order_by(WorkTask.id.asc())
    )
    if fake_task is None:
        planned_qty = stock_line.planned_quantity or Decimal("0")
        fake_task = WorkTask(
            section_plan_line_id=stock_line.id,
            section_id=stock_section.id,
            product_id=product_id,
            route_stage_id=stock_line.route_stage_id,
            planned_quantity=planned_qty,
            status=WorkTaskStatus.ready,
            due_date=stock_line.due_date,
            dimensions=await task_dimensions_for_plan_line(db, stock_line.plan_position_id),
        )
        db.add(fake_task)
        await db.flush()
    return fake_task


async def _ensure_task_issued_via_transfer(
    db: AsyncSession,
    *,
    task: WorkTask,
    line: SectionPlanLine,
    quantity: Decimal,
    prev_task: WorkTask | None,
    actor_id: int,
    comment: str,
    source_ref: str,
    operation_key: str,
    executor_user_id: int,
    performed_at: datetime,
    accounted_at: datetime,
) -> None:
    """Ensure ``in_work > 0`` via TRANSFER_RECEIVE before ``complete_task``.

    First production stage: transfer from stock fake_task (ready-transfer pattern).
    Later stages: transfer from the previous production task when not yet received.
    """
    from app.stock.services import StockProjectionManager

    await db.refresh(task)
    pm = StockProjectionManager()
    task_cache = await pm.get_task_cache(db, task.id)
    issued_qty = task_cache["issued_quantity"]
    to_issue = quantity - issued_qty
    if to_issue <= 0:
        return

    if prev_task is not None:
        from_task_id = prev_task.id
    else:
        stock_pair = await _find_preceding_stock_line(
            db,
            plan_position_id=line.plan_position_id,
            before_sequence=line.sequence,
        )
        if stock_pair is None:
            raise ValueError(
                "Cannot issue material: no preceding stock section and no previous production task"
            )
        stock_line, stock_section = stock_pair
        fake_task = await _get_or_create_stock_fake_task(
            db,
            stock_line=stock_line,
            stock_section=stock_section,
            product_id=task.product_id,
        )
        from_task_id = fake_task.id

    await transfer_send(
        db,
        from_task_id=from_task_id,
        to_task_id=task.id,
        quantity=to_issue,
        actor_id=actor_id,
        comment=comment,
        source_ref=source_ref,
        idempotency_key=f"{operation_key}:receive",
        executor_user_id=executor_user_id,
        performed_at=performed_at,
        accounted_at=accounted_at,
        allow_over_plan=True,
    )


async def _position_stock_transaction_source_refs(db: AsyncSession, position_id: int) -> list[str | None]:
    """Fetch StockTransaction source_refs for a position (replaces Movement check after Этап 3)."""
    from app.stock.models import StockTransaction
    return [
        row[0]
        for row in (
            await db.execute(
                select(StockTransaction.source_ref)
                .join(WorkTask, WorkTask.id == StockTransaction.task_id)
                .join(SectionPlanLine, SectionPlanLine.id == WorkTask.section_plan_line_id)
                .where(
                    SectionPlanLine.plan_position_id == position_id,
                    StockTransaction.source_ref.isnot(None),
                )
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
    from app.stock.models import StockTransaction
    tx_refs = await _position_stock_transaction_source_refs(db, position_id)
    transfer_keys = await _position_transfer_idempotency_keys(db, position_id)

    # Count ALL StockTransactions (including those without source_ref)
    any_tx_count = await db.scalar(
        select(func.count(StockTransaction.id))
        .join(WorkTask, WorkTask.id == StockTransaction.task_id)
        .join(SectionPlanLine, SectionPlanLine.id == WorkTask.section_plan_line_id)
        .where(SectionPlanLine.plan_position_id == position_id)
    )
    has_any_tx = bool(any_tx_count)
    has_any_transfer = bool(transfer_keys)

    if not has_any_tx and not has_any_transfer:
        return False  # First start, no facts yet

    # All StockTransactions must have matching source_ref for replay
    all_tx_match = tx_refs and all(ref == source_ref for ref in tx_refs) and len(tx_refs) == any_tx_count
    all_transfers_match = all(key is not None and key.startswith(f"{source_ref}:") for key in transfer_keys) if transfer_keys else True

    if all_tx_match and all_transfers_match:
        return True  # Idempotent replay

    raise ValueError("Position already has execution facts; manual route pass is allowed only before execution starts")


async def _manual_pass_counts(
    db: AsyncSession,
    *,
    position_id: int,
    source_ref: str,
) -> tuple[int, int]:
    import logging as _log
    _logger = _log.getLogger(__name__)
    from app.stock.models import StockTransaction
    tx_count = await db.scalar(
        select(func.count(StockTransaction.id))
        .join(WorkTask, WorkTask.id == StockTransaction.task_id)
        .join(SectionPlanLine, SectionPlanLine.id == WorkTask.section_plan_line_id)
        .where(
            SectionPlanLine.plan_position_id == position_id,
            StockTransaction.source_ref == source_ref,
        )
    )
    transfer_keys = await _position_transfer_idempotency_keys(db, position_id)
    transfers_count = sum(1 for key in transfer_keys if key is not None and key.startswith(f"{source_ref}:"))
    _logger.warning("DEBUG _manual_pass_counts: position_id=%s source_ref=%s tx_count=%s transfers_count=%s", position_id, source_ref, tx_count, transfers_count)
    # Debug: print all StockTransaction source_refs for this position
    all_tx = await db.execute(
        select(StockTransaction.id, StockTransaction.source_ref, StockTransaction.reason, StockTransaction.task_id)
        .join(WorkTask, WorkTask.id == StockTransaction.task_id)
        .join(SectionPlanLine, SectionPlanLine.id == WorkTask.section_plan_line_id)
        .where(SectionPlanLine.plan_position_id == position_id)
        .order_by(StockTransaction.id)
    )
    for row in all_tx:
        _logger.warning("DEBUG   TX id=%s source_ref=%s reason=%s task_id=%s", row.id, row.source_ref, row.reason, row.task_id)
    return int(tx_count or 0), transfers_count


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
    plant_config: PlantConfig = Depends(get_plant_config),
) -> ManualPassResponse:
    return await _do_manual_pass(db, position_id, payload, current_user, plant_config=plant_config)


async def _do_manual_pass(
    db: AsyncSession,
    position_id: int,
    payload: ManualPassRequest,
    current_user: User,
    *,
    plant_config: PlantConfig,
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
            task, line, stage = task_rows[idx]
            prev_task = task_rows[idx - 1][0] if idx > 0 else None
            next_task = task_rows[idx + 1][0] if idx < len(task_rows) - 1 else None
            quantity = Decimal(str(task.planned_quantity))
            operation_key = f"{source_ref}:step:{stage.sequence}"

            try:
                await _ensure_task_issued_via_transfer(
                    db,
                    task=task,
                    line=line,
                    quantity=quantity,
                    prev_task=prev_task,
                    actor_id=current_user.id,
                    comment=manual_comment,
                    source_ref=source_ref,
                    operation_key=operation_key,
                    executor_user_id=current_user.id,
                    performed_at=now,
                    accounted_at=now,
                )

                from app.stock.services import StockProjectionManager
                pm = StockProjectionManager()
                task_cache = await pm.get_task_cache(db, task.id)
                completed_qty = task_cache["completed_quantity"] + task_cache["rejected_quantity"]
                to_complete = quantity - completed_qty
                if to_complete > 0:
                    scrap = plant_config.production.scrap_policy
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
                        scrap_section_type=scrap.section_type,
                        scrap_code=scrap.code,
                        scrap_name=scrap.name,
                        scrap_sort_order=scrap.sort_order,
                    )
                if next_task is not None:
                    from app.services.shopfloor.common import sections_share_spg
                    if not await sections_share_spg(db, task.section_id, next_task.section_id):
                        # transfer_send auto-accepts under the new explicit-transfer
                        # model — no separate transfer_receive call is required.
                        await transfer_send(
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
    # mapping sequence → set of allowed operation_codes at that stage
    route_seq_to_op_codes: dict[int, set[str | None]] = {}
    # mapping (section_id, operation_code) → (op_icon, op_icon_color) from SectionOperation
    op_icon_lookup: dict[tuple[int, str], tuple[str | None, str | None]] = {}
    op_keys: set[tuple[int, str]] = set()
    stage_entries: list[tuple[RouteStage, Section, list]] = []
    for stage, section in rows:
        ops = list(stage.operations or [])
        stage_entries.append((stage, section, ops))
        for op in ops:
            if op.operation_code is not None:
                op_keys.add((section.id, op.operation_code))

    if op_keys:
        section_ids = list({sid for sid, _ in op_keys})
        op_codes = list({code for _, code in op_keys})
        op_rows = (await db.execute(
            select(SectionOperation)
            .where(SectionOperation.section_id.in_(section_ids))
            .where(SectionOperation.operation_code.in_(op_codes))
        )).scalars().all()
        for op in op_rows:
            op_icon_lookup[(op.section_id, op.operation_code)] = (op.icon, op.icon_color)

    for stage, section, ops in stage_entries:
        op_name = ", ".join(op.operation_name for op in ops) if ops else "Операция"
        if ops and ops[0].operation_code is not None:
            first_op_icon, first_op_icon_color = op_icon_lookup.get(
                (section.id, ops[0].operation_code), (None, None)
            )
        else:
            first_op_icon, first_op_icon_color = None, None
        route_steps.append({
            "sequence": stage.sequence,
            "section_id": stage.section_id,
            "section_name": section.name,
            "section_code": section.code,
            "section_icon": section.icon,
            "section_icon_color": section.icon_color,
            "op_icon": first_op_icon,
            "op_icon_color": first_op_icon_color,
            "operation_name": op_name,
        })
        route_seq_to_section[stage.sequence] = stage.section_id
        route_seq_to_op_codes[stage.sequence] = {
            op.operation_code for op in ops
        } if ops else set()

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
        from app.stock.models import QualityState, StockBalance
        balances = (await db.execute(
            select(StockBalance)
            .where(
                StockBalance.product_id == effective_product_id,
                StockBalance.balance_qty > 0,
                StockBalance.quality_state == QualityState.GOOD,
            )
            .order_by(StockBalance.refreshed_at)
        )).scalars().all()

        for b in balances:
            section = await db.get(Section, b.location_id)
            section_name = section.name if section else ""
            section_code = section.code if section else ""
            spg_section = await db.scalar(
                select(SpgSection).where(SpgSection.section_id == b.location_id).limit(1)
            )
            spg = await db.get(StorageProductionGroup, spg_section.spg_id) if spg_section else None

            available_remainders.append({
                "id": b.id,
                "remainder_quantity": float(b.balance_qty),
                "original_issued": float(b.balance_qty),
                "created_at": b.refreshed_at.isoformat() if b.refreshed_at else None,
                "created_by_user_name": None,
                "completed_stages_json": [],
                "max_completed_seq": 0,
                "max_completed_stage_name": "",
                "spg_name": spg.name if spg else "",
                "spg_icon": spg.icon if spg else None,
                "spg_icon_color": spg.icon_color if spg else None,
                "stages_with_icons": [],
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

    if payload.release_quantity is not None:
        if len(payload.position_ids) != 1:
            raise HTTPException(
                status_code=422,
                detail="release_quantity поддерживается только для одной позиции",
            )
        if payload.release_quantity <= 0:
            raise HTTPException(status_code=422, detail="release_quantity must be > 0")

    for position_id in payload.position_ids:
        try:
            result = await _process_position_take_to_work(
                db,
                position_id,
                remainder_allocation=allocation_dict if len(payload.position_ids) == 1 else None,
                release_quantity=payload.release_quantity if len(payload.position_ids) == 1 else None,
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
    plant_config: PlantConfig = Depends(get_plant_config),
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
                    plant_config=plant_config,
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
    release_quantity: Decimal | None = None,
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
        qty_to_release = release_quantity if release_quantity is not None else pos.quantity
        batch_summary = await create_release_batch(
            db,
            production_plan_id=pos.production_plan_id,
            positions=[{"plan_position_id": position_id, "release_quantity": str(qty_to_release)}],
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
    dimensions: dict | None = None
    dimensions_label: str = DIMENSIONLESS_LABEL
    quantity: float
    max_completed_seq: int = 0
    stages_with_icons: list[dict] = []

class ProductWipTaskOut(BaseModel):
    section_id: int
    section_code: str
    section_name: str
    operation_name: str
    section_icon: str | None = None
    section_icon_color: str | None = None
    dimensions: dict | None = None
    dimensions_label: str = DIMENSIONLESS_LABEL
    planned_qty: float
    completed_qty: float
    issued_qty: float
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

    # 2. Поиск остатков на складах через StockBalance
    from app.stock.models import QualityState, StockBalance
    from app.stock.services import _dimensions_hash_key
    balances = (await db.execute(
        select(StockBalance, Section)
        .join(Section, Section.id == StockBalance.location_id)
        .where(
            StockBalance.product_id == product.id,
            StockBalance.balance_qty > 0,
            StockBalance.quality_state == QualityState.GOOD,
        )
        .order_by(StockBalance.refreshed_at)
    )).all()

    # Group by location/SPG + dimensions (ADR-0001): разные размеры одного
    # SKU на одной секции — разные строки, в общий «котёл» не сводятся.
    rem_grouped: dict[tuple[int, str, str | None], dict] = {}
    for bal, section in balances:
        spg_section = await db.scalar(
            select(SpgSection).where(SpgSection.section_id == bal.location_id).limit(1)
        )
        spg = await db.get(StorageProductionGroup, spg_section.spg_id) if spg_section else None
        spg_id = spg.id if spg else 0
        spg_code = spg.code if spg else ""
        spg_name = spg.name if spg else section.name
        spg_icon = spg.icon if spg else section.icon
        spg_icon_color = spg.icon_color if spg else section.icon_color

        ops_str = section.name or "Склад"
        dims = canonicalize_dimensions(bal.dimensions)
        dims_key = _dimensions_hash_key(dims)
        key = (spg_id, ops_str, dims_key)
        if key not in rem_grouped:
            rem_grouped[key] = {
                "spg_id": spg_id,
                "spg_code": spg_code,
                "spg_name": spg_name,
                "spg_icon": spg_icon,
                "spg_icon_color": spg_icon_color,
                "completed_ops": ops_str,
                "stages_with_icons": [],
                "max_completed_seq": 0,
                "dimensions": dims,
                "dimensions_label": format_dimensions(dims),
                "quantity": 0.0,
            }
        rem_grouped[key]["quantity"] += float(bal.balance_qty or 0)

    remainders = sorted(
        [
            ProductWipRemainderOut(
                spg_id=val["spg_id"],
                spg_code=val["spg_code"],
                spg_name=val["spg_name"],
                completed_ops=val["completed_ops"],
                spg_icon=val["spg_icon"],
                spg_icon_color=val["spg_icon_color"],
                dimensions=val["dimensions"],
                dimensions_label=val["dimensions_label"],
                stages_with_icons=val["stages_with_icons"],
                max_completed_seq=val["max_completed_seq"],
                quantity=val["quantity"],
            )
            for val in rem_grouped.values()
            if val["quantity"] != 0.0
        ],
        key=lambda r: r.max_completed_seq,
        reverse=True,
    )

    # 3. Поиск активных задач в работе (ready, in_progress)
    from sqlalchemy.orm import selectinload

    work_q = (
        select(WorkTask, Section, RouteStage)
        .join(Section, WorkTask.section_id == Section.id)
        .join(RouteStage, WorkTask.route_stage_id == RouteStage.id)
        .options(selectinload(RouteStage.operations))
        .where(WorkTask.product_id == product.id)
        .where(WorkTask.status.in_([WorkTaskStatus.ready, WorkTaskStatus.in_progress]))
        .order_by(RouteStage.sequence)
    )
    work_rows = (await db.execute(work_q)).all()

    # Группируем задачи по секциям, операциям и размерам в Python-коде
    # (ADR-0001): задания одного артикула разных размеров — разные строки.
    from app.stock.services import StockProjectionManager
    pm = StockProjectionManager()
    all_wt_ids = [wt.id for wt, _, _ in work_rows]
    tasks_cache_bulk = await pm.get_tasks_cache_bulk(db, all_wt_ids)

    grouped: dict[tuple[int, str, str | None], dict] = {}
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

        dims = canonicalize_dimensions(wt.dimensions)
        key = (sec.id, op_name, _dimensions_hash_key(dims))
        if key not in grouped:
            grouped[key] = {
                "section_id": sec.id,
                "section_code": sec.code,
                "section_name": sec.name,
                "section_icon": sec.icon,
                "section_icon_color": sec.icon_color,
                "operation_name": op_name,
                "dimensions": dims,
                "dimensions_label": format_dimensions(dims),
                "planned_qty": 0.0,
                "completed_qty": 0.0,
                "issued_qty": 0.0,
                "active_tasks_count": 0,
            }

        wt_cache = tasks_cache_bulk.get(wt.id, {})
        grouped[key]["planned_qty"] += float(wt.planned_quantity or 0)
        grouped[key]["completed_qty"] += float(wt_cache.get("completed_quantity", 0) or 0)
        grouped[key]["issued_qty"] += float(wt_cache.get("issued_quantity", 0) or 0)
        grouped[key]["active_tasks_count"] += 1

    in_work = [
        ProductWipTaskOut(
            section_id=val["section_id"],
            section_code=val["section_code"],
            section_name=val["section_name"],
            operation_name=val["operation_name"],
            section_icon=val["section_icon"],
            section_icon_color=val["section_icon_color"],
            dimensions=val["dimensions"],
            dimensions_label=val["dimensions_label"],
            planned_qty=val["planned_qty"],
            completed_qty=val["completed_qty"],
            issued_qty=val["issued_qty"],
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
