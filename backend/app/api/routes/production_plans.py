from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.production_plan import PlanChangeSet, PlanPosition
from app.models.release_batch import ReleaseBatchType
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
from app.services.plan_generation import create_release_batch
from app.services.production_plan_service import apply_change_set, approve_plan_position, get_plan_preview, rollback_change_set
from app.services.route_resolution import resolve_route_signature
from app.services.route_validation import validate_route_match

router = APIRouter(prefix="/production-plans", tags=["production-plans"])


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


@router.post("/{production_plan_id}/positions/{position_id}/approve")
async def approve_position(
    production_plan_id: int,
    position_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        position = await approve_plan_position(db, production_plan_id, position_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": position.id,
        "production_plan_id": position.production_plan_id,
        "status": position.status.value,
        "validation_status": position.validation_status.value,
        "validation_errors": position.validation_errors,
    }


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
    if position.product_id:
        route = await db.scalar(
            select(ProductionRoute).where(
                ProductionRoute.product_id == position.product_id,
                ProductionRoute.is_active.is_(True),
            )
        )
        if route:
            steps_result = await db.execute(
                select(RouteStep, Section)
                .join(Section, RouteStep.section_id == Section.id)
                .where(RouteStep.route_id == route.id)
                .order_by(RouteStep.sequence)
            )
            active_route_snapshot = {
                "route_id": route.id,
                "route_name": route.name,
                "route_version": route.version,
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
        route = await db.scalar(
            select(ProductionRoute).where(
                ProductionRoute.product_id == position.product_id,
                ProductionRoute.is_active.is_(True),
            )
        )
        if route is None:
            continue

        steps = (
            await db.execute(
                select(RouteStep, Section)
                .join(Section, RouteStep.section_id == Section.id)
                .where(RouteStep.route_id == route.id)
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
