from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func as sa_func

from app.core.database import get_db
from app.models.product import Product
from app.models.production_plan import PlanChangeSet, PlanPosition, PlanPositionStatus, ProductionPlan
from app.models.release_batch import ReleaseBatchType
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
from app.services.plan_generation import create_release_batch
from app.services.production_plan_service import apply_change_set, approve_plan_position, get_plan_preview, rollback_change_set
from app.services.route_matcher import find_route, resolve_position_route, ResolvedRouteInfo
from app.services.route_resolution import resolve_route_signature
from app.services.route_validation import validate_route_match
from app.services.plan_validation import format_validation_error

router = APIRouter(prefix="/production-plans", tags=["production-plans"])


class PlanSummaryOut(BaseModel):
    id: int
    plan_no: str
    name: str
    status: str
    period_start: str | None
    period_end: str | None
    total_positions: int
    draft_positions: int
    approved_positions: int
    released_positions: int
    created_at: str


@router.get("", response_model=list[PlanSummaryOut])
async def list_plans(db: AsyncSession = Depends(get_db)) -> list[PlanSummaryOut]:
    plans = (await db.execute(select(ProductionPlan).order_by(ProductionPlan.created_at.desc()))).scalars().all()
    result = []
    for plan in plans:
        counts = (
            await db.execute(
                select(PlanPosition.status, sa_func.count(PlanPosition.id))
                .where(PlanPosition.production_plan_id == plan.id)
                .group_by(PlanPosition.status)
            )
        ).all()
        status_map = {s.value: c for s, c in counts}
        total = (
            await db.execute(select(sa_func.count(PlanPosition.id)).where(PlanPosition.production_plan_id == plan.id))
        ).scalar() or 0
        result.append(
            PlanSummaryOut(
                id=plan.id,
                plan_no=plan.plan_no,
                name=plan.name,
                status=plan.status.value,
                period_start=plan.period_start.isoformat() if plan.period_start else None,
                period_end=plan.period_end.isoformat() if plan.period_end else None,
                total_positions=total,
                draft_positions=status_map.get("draft", 0),
                approved_positions=status_map.get("approved", 0),
                released_positions=status_map.get("released", 0),
                created_at=plan.created_at.isoformat(),
            )
        )
    return result


class ReleasePositionIn(BaseModel):
    plan_position_id: int
    release_quantity: Decimal | None = None


class ReleaseBatchCreateIn(BaseModel):
    name: str | None = None
    batch_type: ReleaseBatchType = ReleaseBatchType.manual
    positions: list[ReleasePositionIn] | None = None


class RouteCheckOut(BaseModel):
    expected_signature: dict
    active_route_snapshot: dict | None
    match: bool
    issues: list[str]


class SectionTotalsLineOut(BaseModel):
    section_id: int
    section_code: str
    section_name: str
    section_kind: str | None
    positions_count: int
    planned_input_quantity: str
    planned_output_quantity: str


class SectionTotalsOut(BaseModel):
    production_plan_id: int
    totals: list[SectionTotalsLineOut]


@router.get("/{production_plan_id}/preview")
async def preview_production_plan(production_plan_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await get_plan_preview(db, production_plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{production_plan_id}/change-sets/{change_set_id}/apply")
async def apply_plan_change_set(
    production_plan_id: int,
    change_set_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    change_set = await db.get(PlanChangeSet, change_set_id)
    if change_set is None:
        raise HTTPException(status_code=404, detail="Change set not found")
    if change_set.production_plan_id != production_plan_id:
        raise HTTPException(status_code=400, detail="Change set does not belong to production plan")
    try:
        preview = await apply_change_set(db, change_set_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return preview


@router.post("/{production_plan_id}/change-sets/{change_set_id}/rollback")
async def rollback_plan_change_set(
    production_plan_id: int,
    change_set_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    change_set = await db.get(PlanChangeSet, change_set_id)
    if change_set is None:
        raise HTTPException(status_code=404, detail="Change set not found")
    if change_set.production_plan_id != production_plan_id:
        raise HTTPException(status_code=400, detail="Change set does not belong to production plan")
    try:
        return await rollback_change_set(db, change_set_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{production_plan_id}/batches/{batch_id}")
async def delete_import_batch(
    production_plan_id: int,
    batch_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Rollback and delete an import batch along with all its positions and change sets."""
    from app.models.imports import ImportBatch
    from sqlalchemy import delete

    batch = await db.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Import batch not found")

    # Rollback and delete all change sets for this batch
    change_sets = (
        await db.execute(select(PlanChangeSet).where(PlanChangeSet.import_batch_id == batch_id))
    ).scalars().all()

    for cs in change_sets:
        if cs.status.value == "applied":
            try:
                await rollback_change_set(db, cs.id)
            except ValueError:
                pass  # Ignore rollback errors, continue with deletion

        # Delete all change items
        await db.execute(delete(PlanChangeItem).where(PlanChangeItem.change_set_id == cs.id))
        # Delete the change set
        await db.delete(cs)

    # Delete all plan positions created by this batch
    positions = (
        await db.execute(select(PlanPosition).where(PlanPosition.import_batch_id == batch_id))
    ).scalars().all()
    for pos in positions:
        await db.delete(pos)

    # Delete the batch
    await db.delete(batch)
    await db.commit()

    return {"deleted": True, "batch_id": batch_id}


@router.post("/{production_plan_id}/positions/{position_id}/approve")
async def approve_position(
    production_plan_id: int,
    position_id: int,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
) -> dict:
    import logging
    logger = logging.getLogger(__name__)
    try:
        position = await approve_plan_position(db, production_plan_id, position_id, force=force)
    except ValueError as exc:
        logger.error("approve_position failed: %s (plan=%d, pos=%d, force=%s)", exc, production_plan_id, position_id, force)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": position.id,
        "production_plan_id": position.production_plan_id,
        "status": position.status.value,
        "validation_status": position.validation_status.value,
        "validation_errors": position.validation_errors,
    }


@router.delete("/{production_plan_id}/positions/{position_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_position(
    production_plan_id: int,
    position_id: int,
    db: AsyncSession = Depends(get_db),
):
    position = await db.get(PlanPosition, position_id)
    if position is None or position.production_plan_id != production_plan_id:
        raise HTTPException(status_code=404, detail="Position not found")
    if position.status == "released":
        raise HTTPException(status_code=400, detail="Нельзя удалить запущенную позицию")
    await db.delete(position)


@router.post("/{production_plan_id}/release-batches", status_code=status.HTTP_201_CREATED)
async def create_plan_release_batch(
    production_plan_id: int,
    payload: ReleaseBatchCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await create_release_batch(
            db,
            production_plan_id=production_plan_id,
            positions=[item.model_dump() for item in payload.positions] if payload.positions else None,
            batch_type=payload.batch_type,
            name=payload.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{production_plan_id}/positions/{position_id}/route-check")
async def route_check(
    production_plan_id: int,
    position_id: int,
    db: AsyncSession = Depends(get_db),
) -> RouteCheckOut:
    position = await db.get(PlanPosition, position_id)
    if position is None:
        raise HTTPException(status_code=404, detail="Position not found")
    if position.production_plan_id != production_plan_id:
        raise HTTPException(status_code=400, detail="Position does not belong to production plan")

    resolved = resolve_route_signature(position.source_payload or {})
    expected_signature = {
        "steps": [
            {
                "step_id": step.step_id,
                "operation_code": step.operation_code,
                "section_kind": step.section_kind,
                "description": step.description,
            }
            for step in resolved.steps
        ],
        "primary_operation": resolved.primary_operation,
        "output_kind": resolved.output_kind,
        "additional_pack_operations": resolved.additional_pack_operations,
    }

    issues = await validate_route_match(db, position)

    active_route_snapshot = None
    product = await db.get(Product, position.product_id) if position.product_id else None
    route_info = await resolve_position_route(db, position.route_id, product)
    if route_info.route_id:
        steps_result = await db.execute(
            select(RouteStep, Section)
            .join(Section, RouteStep.section_id == Section.id)
            .where(RouteStep.route_id == route_info.route_id)
            .order_by(RouteStep.sequence)
        )
        active_route_snapshot = {
            "route_id": route_info.route_id,
            "route_name": route_info.route_name,
            "route_source": route_info.source,
            "steps": [
                {
                    "sequence": step.sequence,
                    "section_id": step.section_id,
                    "section_code": section.code,
                    "section_name": section.name,
                    "section_kind": section.kind,
                    "operation_name": step.operation_name,
                }
                for step, section in steps_result.all()
            ],
        }

    return RouteCheckOut(
        expected_signature=expected_signature,
        active_route_snapshot=active_route_snapshot,
        match=len(issues) == 0,
        issues=issues,
    )


@router.get("/{production_plan_id}/section-totals")
async def section_totals(
    production_plan_id: int,
    db: AsyncSession = Depends(get_db),
) -> SectionTotalsOut:
    positions = (
        await db.execute(
            select(PlanPosition).where(PlanPosition.production_plan_id == production_plan_id)
        )
    ).scalars().all()

    if not positions:
        return SectionTotalsOut(production_plan_id=production_plan_id, totals=[])

    totals_by_section: dict[int, dict] = {}
    for position in positions:
        if position.product_id is None:
            continue
        product = await db.get(Product, position.product_id)
        route_info = await resolve_position_route(db, position.route_id, product)
        if route_info.route_id is None:
            continue

        steps = (
            await db.execute(
                select(RouteStep, Section)
                .join(Section, RouteStep.section_id == Section.id)
                .where(RouteStep.route_id == route_info.route_id)
                .order_by(RouteStep.sequence)
            )
        ).all()
        for _, section in steps:
            bucket = totals_by_section.setdefault(
                section.id,
                {
                    "section_id": section.id,
                    "section_code": section.code,
                    "section_name": section.name,
                    "section_kind": section.kind,
                    "positions": set(),
                    "input": 0,
                    "output": 0,
                },
            )
            bucket["positions"].add(position.id)
            # MVP assumes 1:1 transformation on route step level.
            bucket["input"] += position.quantity
            bucket["output"] += position.quantity

    totals = [
        SectionTotalsLineOut(
            section_id=b["section_id"],
            section_code=b["section_code"],
            section_name=b["section_name"],
            section_kind=b["section_kind"],
            positions_count=len(b["positions"]),
            planned_input_quantity=str(b["input"]),
            planned_output_quantity=str(b["output"]),
        )
        for b in totals_by_section.values()
    ]
    totals.sort(key=lambda item: item.section_code)
    return SectionTotalsOut(production_plan_id=production_plan_id, totals=totals)


class PlanFileInfo(BaseModel):
    batch_id: int
    file_id: int
    filename: str
    extension: str
    size_bytes: int
    sheet_name: str
    total_rows: int
    parsed_rows: int
    status: str
    created_at: str


@router.get("/{production_plan_id}/files")
async def plan_files(production_plan_id: int, db: AsyncSession = Depends(get_db)) -> list[PlanFileInfo]:
    from app.models.imports import ImportBatch, ImportFile

    batches = (
        await db.execute(
            select(ImportBatch, ImportFile)
            .join(ImportFile, ImportBatch.source_file_id == ImportFile.id)
            .where(ImportBatch.production_plan_id == production_plan_id)
            .order_by(ImportBatch.created_at)
        )
    ).all()
    return [
        PlanFileInfo(
            batch_id=batch.id,
            file_id=file.id,
            filename=file.original_filename,
            extension=file.file_extension,
            size_bytes=file.size_bytes,
            sheet_name=batch.sheet_name,
            total_rows=batch.total_rows,
            parsed_rows=batch.parsed_rows,
            status=batch.status.value,
            created_at=batch.created_at.isoformat(),
        )
        for batch, file in batches
    ]


class PlanPositionOut(BaseModel):
    id: int
    production_plan_id: int
    source_sku: str
    source_name: str | None
    quantity: str
    status: str
    validation_status: str
    errors: list
    warnings: list
    source_row_number: int | None
    change_action: str | None = None
    product_id: int | None = None
    route_id: int | None = None
    route_name: str | None = None
    route_source: str | None = None  # "manual" | "auto" | "missing"
    route_error: str | None = None


@router.get("/all-files", response_model=list[PlanFileInfo])
async def all_plan_files(db: AsyncSession = Depends(get_db)) -> list[PlanFileInfo]:
    """Return files from all production plans."""
    from app.models.imports import ImportBatch, ImportFile

    batches = (
        await db.execute(
            select(ImportBatch, ImportFile)
            .join(ImportFile, ImportBatch.source_file_id == ImportFile.id)
            .order_by(ImportBatch.created_at.desc())
        )
    ).all()
    return [
        PlanFileInfo(
            batch_id=batch.id,
            file_id=file.id,
            filename=file.original_filename,
            extension=file.file_extension,
            size_bytes=file.size_bytes,
            sheet_name=batch.sheet_name,
            total_rows=batch.total_rows,
            parsed_rows=batch.parsed_rows,
            status=batch.status.value,
            created_at=batch.created_at.isoformat(),
        )
        for batch, file in batches
    ]


@router.get("/all-positions", response_model=list[PlanPositionOut])
async def all_plan_positions(db: AsyncSession = Depends(get_db)) -> list[PlanPositionOut]:
    """Return positions from all production plans."""
    from app.models.production_plan import PlanChangeItem

    positions = (
        await db.execute(
            select(PlanPosition)
            .order_by(PlanPosition.source_row_number, PlanPosition.id)
        )
    ).scalars().all()

    change_items = (
        await db.execute(
            select(PlanChangeItem).where(
                PlanChangeItem.plan_position_id.in_([p.id for p in positions])
            )
        )
    ).scalars().all()
    warnings_by_position = {ci.plan_position_id: ci.warnings for ci in change_items if ci.plan_position_id}

    products_cache: dict[int, Product | None] = {}
    route_resolve_cache: dict[int, ResolvedRouteInfo] = {}

    result = []
    for p in positions:
        product = None
        if p.product_id:
            if p.product_id not in products_cache:
                products_cache[p.product_id] = await db.get(Product, p.product_id)
            product = products_cache[p.product_id]

        if p.product_id and p.product_id in route_resolve_cache:
            route_info = route_resolve_cache[p.product_id]
        else:
            route_info = await resolve_position_route(db, p.route_id, product)
            if p.product_id:
                route_resolve_cache[p.product_id] = route_info

        result.append(
            PlanPositionOut(
                id=p.id,
                production_plan_id=p.production_plan_id,
                source_sku=p.source_sku,
                source_name=p.source_name,
                quantity=str(p.quantity),
                status=p.status.value,
                validation_status=p.validation_status.value,
                errors=[format_validation_error(e) for e in (p.validation_errors or [])],
                source_row_number=p.source_row_number,
                warnings=warnings_by_position.get(p.id, []) or [],
                product_id=p.product_id,
                route_id=route_info.route_id,
                route_name=route_info.route_name,
                route_source=route_info.source,
                route_error=route_info.error,
            )
        )

    return result


@router.get("/{production_plan_id}/all-positions")
async def all_positions(production_plan_id: int, db: AsyncSession = Depends(get_db)) -> list[PlanPositionOut]:
    from app.models.production_plan import PlanChangeItem

    positions = (
        await db.execute(
            select(PlanPosition)
            .where(PlanPosition.production_plan_id == production_plan_id)
            .order_by(PlanPosition.source_row_number, PlanPosition.id)
        )
    ).scalars().all()

    # Gather warnings from change items
    change_items = (
        await db.execute(
            select(PlanChangeItem).where(
                PlanChangeItem.plan_position_id.in_([p.id for p in positions])
            )
        )
    ).scalars().all()
    warnings_by_position = {ci.plan_position_id: ci.warnings for ci in change_items if ci.plan_position_id}

    # Cache products and routes
    products_cache: dict[int, Product | None] = {}
    route_resolve_cache: dict[int, ResolvedRouteInfo] = {}

    result = []
    for p in positions:
        product = None
        if p.product_id:
            if p.product_id not in products_cache:
                products_cache[p.product_id] = await db.get(Product, p.product_id)
            product = products_cache[p.product_id]

        if p.product_id and p.product_id in route_resolve_cache:
            route_info = route_resolve_cache[p.product_id]
        else:
            route_info = await resolve_position_route(db, p.route_id, product)
            if p.product_id:
                route_resolve_cache[p.product_id] = route_info

        result.append(
            PlanPositionOut(
                id=p.id,
                production_plan_id=p.production_plan_id,
                source_sku=p.source_sku,
                source_name=p.source_name,
                quantity=str(p.quantity),
                status=p.status.value,
                validation_status=p.validation_status.value,
                errors=[format_validation_error(e) for e in (p.validation_errors or [])],
                source_row_number=p.source_row_number,
                warnings=warnings_by_position.get(p.id, []) or [],
                product_id=p.product_id,
                route_id=route_info.route_id,
                route_name=route_info.route_name,
                route_source=route_info.source,
                route_error=route_info.error,
            )
        )

    return result


class BatchAssignRouteIn(BaseModel):
    position_ids: list[int]
    route_id: int | None


class BatchAssignRouteOut(BaseModel):
    updated_count: int
    route_id: int | None
    route_name: str | None


@router.post("/positions/batch-assign-route", response_model=BatchAssignRouteOut)
async def batch_assign_route_global(
    payload: BatchAssignRouteIn,
    db: AsyncSession = Depends(get_db),
) -> BatchAssignRouteOut:
    """Assign route to positions by their IDs, regardless of which plan they belong to."""
    if not payload.position_ids:
        raise HTTPException(status_code=400, detail="position_ids must not be empty")

    route_name = None
    if payload.route_id is not None:
        route = await db.get(ProductionRoute, payload.route_id)
        if route is None:
            raise HTTPException(status_code=404, detail="Route not found")
        if not route.is_active:
            raise HTTPException(status_code=400, detail="Route is not active")
        route_name = route.name

    positions = (
        await db.execute(
            select(PlanPosition).where(
                PlanPosition.id.in_(payload.position_ids),
            )
        )
    ).scalars().all()

    for pos in positions:
        pos.route_id = payload.route_id

    await db.commit()

    return BatchAssignRouteOut(
        updated_count=len(positions),
        route_id=payload.route_id,
        route_name=route_name,
    )


@router.post("/{production_plan_id}/positions/batch-assign-route", response_model=BatchAssignRouteOut)
async def batch_assign_route(
    production_plan_id: int,
    payload: BatchAssignRouteIn,
    db: AsyncSession = Depends(get_db),
) -> BatchAssignRouteOut:
    print(f"DEBUG batch_assign_route: plan_id={production_plan_id}, position_ids={payload.position_ids}, route_id={payload.route_id}")

    plan = await db.get(ProductionPlan, production_plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Production plan not found")

    if not payload.position_ids:
        raise HTTPException(status_code=400, detail="position_ids must not be empty")

    route_name = None
    if payload.route_id is not None:
        route = await db.get(ProductionRoute, payload.route_id)
        if route is None:
            raise HTTPException(status_code=404, detail="Route not found")
        if not route.is_active:
            raise HTTPException(status_code=400, detail="Route is not active")
        route_name = route.name

    positions = (
        await db.execute(
            select(PlanPosition).where(
                PlanPosition.id.in_(payload.position_ids),
                PlanPosition.production_plan_id == production_plan_id,
            )
        )
    ).scalars().all()

    if len(positions) != len(payload.position_ids):
        raise HTTPException(status_code=400, detail="Some positions not found or belong to a different plan")

    for pos in positions:
        pos.route_id = payload.route_id

    await db.commit()

    return BatchAssignRouteOut(
        updated_count=len(positions),
        route_id=payload.route_id,
        route_name=route_name,
    )


class DuplicateGroup(BaseModel):
    source_sku: str
    due_date: str | None
    positions: list[dict]


@router.get("/{production_plan_id}/duplicates", response_model=list[DuplicateGroup])
async def find_plan_duplicates(production_plan_id: int, db: AsyncSession = Depends(get_db)) -> list[DuplicateGroup]:
    """Find positions with duplicate source_sku + due_date within a production plan."""
    positions = (
        await db.execute(
            select(PlanPosition)
            .where(
                PlanPosition.production_plan_id == production_plan_id,
                PlanPosition.status != PlanPositionStatus.cancelled,
            )
            .order_by(PlanPosition.source_sku, PlanPosition.source_row_number)
        )
    ).scalars().all()

    from collections import defaultdict

    groups: dict[tuple[str, str | None], list[dict]] = defaultdict(list)

    for p in positions:
        due_date = None
        if p.source_payload:
            due_date = p.source_payload.get("due_date")
        key = (p.source_sku.lower().strip(), due_date)
        groups[key].append({
            "id": p.id,
            "source_sku": p.source_sku,
            "source_name": p.source_name,
            "quantity": str(p.quantity),
            "source_row_number": p.source_row_number,
            "status": p.status.value,
            "validation_errors": p.validation_errors or [],
        })

    result = []
    for (sku, due_date), positions_list in groups.items():
        if len(positions_list) > 1:
            result.append(
                DuplicateGroup(
                    source_sku=sku,
                    due_date=due_date,
                    positions=positions_list,
                )
            )

    return result


@router.get("/{production_plan_id}/batches/{batch_id}/preview")
async def batch_preview(production_plan_id: int, batch_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    from app.models.production_plan import PlanChangeItem

    change_set = (
        await db.execute(
            select(PlanChangeSet).where(
                PlanChangeSet.production_plan_id == production_plan_id,
                PlanChangeSet.import_batch_id == batch_id,
            )
        )
    ).scalar_one_or_none()
    if change_set is None:
        raise HTTPException(status_code=404, detail="Change set for batch not found")

    items = (
        await db.execute(
            select(PlanChangeItem).where(PlanChangeItem.change_set_id == change_set.id).order_by(PlanChangeItem.source_row_number)
        )
    ).scalars().all()
    return {
        "batch_id": batch_id,
        "change_set_id": change_set.id,
        "items": [
            {
                "id": item.id,
                "change_action": item.change_action.value,
                "source_sku": (item.after_data or {}).get("source_sku", ""),
                "source_name": (item.after_data or {}).get("source_name", ""),
                "quantity": (item.after_data or {}).get("quantity", ""),
                "status": item.status.value,
                "errors": item.errors or [],
                "warnings": item.warnings or [],
                "source_payload": (item.after_data or {}).get("source_payload"),
                "after_data": item.after_data,
            }
            for item in items
        ],
    }
