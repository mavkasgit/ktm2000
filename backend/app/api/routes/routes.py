from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.route import ProductionRoute, RouteMatchingRule, RouteStage, RouteOperation, SectionOperation
from app.models.section import Section
from app.models.internal_plan import SectionPlanLine
from app.models.release_batch import ReleaseBatchPosition
from app.models.production_plan import PlanPosition, PlanChangeItem

router = APIRouter(prefix="/routes", tags=["routes"])


# --- Pydantic schemas ---

class RouteCreate(BaseModel):
    name: str
    description: str | None = None
    is_active: bool = True


class RouteUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class StepCreate(BaseModel):
    sequence: int
    section_id: int
    operation_code: str | None = None
    operation_name: str
    norm_time_minutes: int | None = None
    requires_acceptance: bool = True
    allow_parallel: bool = False
    is_final: bool = False



class StepUpdate(BaseModel):
    sequence: int
    section_id: int
    operation_code: str | None = None
    operation_name: str
    norm_time_minutes: int | None = None
    requires_acceptance: bool = True
    allow_parallel: bool = False
    is_final: bool = False



class RuleOut(BaseModel):
    id: int
    route_id: int
    priority: int
    is_active: bool = True


class StepOut(BaseModel):
    id: int
    route_id: int
    sequence: int
    section_id: int
    section_code: str | None = None
    section_name: str | None = None
    operation_code: str | None = None
    operation_name: str
    norm_time_minutes: int | None = None
    is_final: bool


    model_config = {"from_attributes": True}


class RouteOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    is_active: bool

    model_config = {"from_attributes": True}


class RouteDetailOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    is_active: bool
    steps: list[StepOut] = []
    rules: list[RuleOut] = []


class ReorderRoutesIn(BaseModel):
    ids: list[int]


@router.post("/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_routes(payload: ReorderRoutesIn, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import update
    for idx, route_id in enumerate(payload.ids):
        await db.execute(
            update(ProductionRoute).where(ProductionRoute.id == route_id).values(sort_order=idx * 10)
        )
    await db.flush()


# --- Endpoints ---

@router.get("", response_model=list[RouteOut])
async def list_routes(
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[RouteOut]:
    stmt = select(ProductionRoute).order_by(ProductionRoute.sort_order, ProductionRoute.name)
    if q:
        stmt = stmt.where(ProductionRoute.name.ilike(f"%{q}%"))
    rows = (await db.execute(stmt)).scalars().all()
    return [RouteOut.model_validate(r, from_attributes=True) for r in rows]


@router.get("/{route_id}", response_model=RouteDetailOut)
async def get_route(route_id: int, db: AsyncSession = Depends(get_db)) -> RouteDetailOut:
    route = await db.get(ProductionRoute, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")

    # Use raw SQL to bypass ORM caching
    from sqlalchemy import text
    steps_result = await db.execute(text("""
        SELECT rs.id, rs.route_id, rs.sequence, rs.section_id, rs.operation_code,
               rs.operation_name, rs.norm_time_minutes, rs.is_final,
               s.code as section_code, s.name as section_name
        FROM route_steps rs
        LEFT JOIN sections s ON rs.section_id = s.id
        WHERE rs.route_id = :route_id
        ORDER BY rs.sequence
    """), {"route_id": route_id})

    steps = []
    for step in route.steps:
        section = await db.get(Section, step.section_id)
        steps.append(StepOut(
            id=step.id,
            route_id=step.route_id,
            sequence=step.sequence,
            section_id=step.section_id,
            section_code=section.code if section else None,
            section_name=section.name if section else None,
            operation_code=step.operation_code,
            operation_name=step.operation_name,
            norm_time_minutes=step.norm_time_minutes,
            is_final=step.is_final,

        ))

    rules_result = await db.execute(
        select(RouteMatchingRule)
        .where(RouteMatchingRule.route_id == route.id)
        .order_by(RouteMatchingRule.priority.desc(), RouteMatchingRule.id.asc())
    )
    rules = []
    for rule in rules_result.scalars().all():
        rules.append(RuleOut(
            id=rule.id,
            route_id=rule.route_id,
            priority=rule.priority,
            is_active=True,
        ))

    return RouteDetailOut(
        id=route.id,
        name=route.name,
        description=route.description,
        is_active=route.is_active,
        steps=steps,
        rules=rules,
    )


@router.post("", response_model=RouteOut, status_code=status.HTTP_201_CREATED)
async def create_route(payload: RouteCreate, db: AsyncSession = Depends(get_db)) -> RouteOut:
    # Check unique name
    existing = await db.scalar(select(ProductionRoute).where(ProductionRoute.name == payload.name))
    if existing:
        raise HTTPException(status_code=409, detail="Route with this name already exists")
    route = ProductionRoute(name=payload.name, description=payload.description, is_active=payload.is_active)
    db.add(route)
    await db.flush()
    await db.refresh(route)
    return RouteOut.model_validate(route, from_attributes=True)


@router.put("/{route_id}", response_model=RouteOut)
async def update_route(route_id: int, payload: RouteUpdate, db: AsyncSession = Depends(get_db)) -> RouteOut:
    route = await db.get(ProductionRoute, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    if payload.name is not None:
        existing = await db.scalar(select(ProductionRoute).where(ProductionRoute.name == payload.name, ProductionRoute.id != route_id))
        if existing:
            raise HTTPException(status_code=409, detail="Route with this name already exists")
        route.name = payload.name
    if payload.description is not None:
        route.description = payload.description
    if payload.is_active is not None:
        route.is_active = payload.is_active
    await db.flush()
    await db.refresh(route)
    return RouteOut.model_validate(route, from_attributes=True)


@router.get("/{route_id}/delete-check")
async def check_route_delete(route_id: int, db: AsyncSession = Depends(get_db)):
    """Check what will be deleted when removing a route"""
    route = await db.get(ProductionRoute, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")

    steps_count = await db.scalar(select(func.count()).select_from(RouteStage).where(RouteStage.route_id == route_id))
    legacy_rules_count = await db.scalar(select(func.count()).select_from(RouteMatchingRule).where(RouteMatchingRule.route_id == route_id))
    spl_count = await db.scalar(select(func.count()).select_from(SectionPlanLine).where(SectionPlanLine.route_id == route_id))
    rbp_count = await db.scalar(select(func.count()).select_from(ReleaseBatchPosition).where(ReleaseBatchPosition.route_id == route_id))
    plan_positions_count = await db.scalar(select(func.count()).select_from(PlanPosition).where(PlanPosition.route_id == route_id))

    warning_parts = []
    if steps_count:
        warning_parts.append(f"{steps_count} шаг(ов) маршрута")
    if legacy_rules_count:
        warning_parts.append(f"{legacy_rules_count} правило(ок) привязки")
    if spl_count:
        warning_parts.append(f"{spl_count} линия(ий) плана участков")
    if rbp_count:
        warning_parts.append(f"{rbp_count} позиция(ий) выпуска")
    if plan_positions_count:
        warning_parts.append(f"{plan_positions_count} позиция(ий) плана")

    return {
        "has_relations": bool(warning_parts),
        "warning": f"Будут удалены: {', '.join(warning_parts)}." if warning_parts else None,
        "steps_count": steps_count or 0,
        "rules_count": legacy_rules_count or 0,
        "spl_count": spl_count or 0,
        "rbp_count": rbp_count or 0,
        "plan_positions_count": plan_positions_count or 0,
    }


class DeleteRouteWarning(BaseModel):
    warning: str
    steps_count: int
    rules_count: int
    spl_count: int
    rbp_count: int
    plan_positions_count: int


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route(
    route_id: int,
    force: str = "false",
    db: AsyncSession = Depends(get_db)
) -> None:
    force_bool = force.lower() in ("true", "1", "yes")
    
    route = await db.get(ProductionRoute, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")

    # Check for relations
    steps_count = await db.scalar(select(func.count()).select_from(RouteStage).where(RouteStage.route_id == route_id))
    legacy_rules_count = await db.scalar(select(func.count()).select_from(RouteMatchingRule).where(RouteMatchingRule.route_id == route_id))
    spl_count = await db.scalar(select(func.count()).select_from(SectionPlanLine).where(SectionPlanLine.route_id == route_id))
    rbp_count = await db.scalar(select(func.count()).select_from(ReleaseBatchPosition).where(ReleaseBatchPosition.route_id == route_id))
    plan_positions_count = await db.scalar(select(func.count()).select_from(PlanPosition).where(PlanPosition.route_id == route_id))

    # If not force deletion and there are relations, return warning
    if not force_bool and (steps_count or legacy_rules_count or spl_count or rbp_count or plan_positions_count):
        warning_parts = []
        if steps_count:
            warning_parts.append(f"{steps_count} шаг(ов) маршрута")
        if legacy_rules_count:
            warning_parts.append(f"{legacy_rules_count} правило(ок) привязки")
        if spl_count:
            warning_parts.append(f"{spl_count} линия(ий) плана участков")
        if rbp_count:
            warning_parts.append(f"{rbp_count} позиция(ий) выпуска")
        if plan_positions_count:
            warning_parts.append(f"{plan_positions_count} позиция(ий) плана")
        
        warning = f"Будут удалены: {', '.join(warning_parts)}. Продолжить?"
        raise HTTPException(
            status_code=409,
            detail=warning
        )

    # Delete related records in proper order
    if steps_count:
        await db.execute(delete(RouteStage).where(RouteStage.route_id == route_id))
    if legacy_rules_count:
        await db.execute(delete(RouteMatchingRule).where(RouteMatchingRule.route_id == route_id))
    if spl_count:
        await db.execute(delete(SectionPlanLine).where(SectionPlanLine.route_id == route_id))
    if rbp_count:
        await db.execute(delete(ReleaseBatchPosition).where(ReleaseBatchPosition.route_id == route_id))
    
    # Delete plan_positions and all their related items
    if plan_positions_count:
        plan_position_ids = await db.scalars(select(PlanPosition.id).where(PlanPosition.route_id == route_id))
        plan_position_ids = list(plan_position_ids)
        if plan_position_ids:
            await db.execute(delete(PlanChangeItem).where(PlanChangeItem.plan_position_id.in_(plan_position_ids)))
        await db.execute(delete(PlanPosition).where(PlanPosition.route_id == route_id))

    await db.delete(route)
    await db.flush()


@router.post("/{route_id}/steps", response_model=StepOut, status_code=status.HTTP_201_CREATED)
async def create_route_step(route_id: int, payload: StepCreate, db: AsyncSession = Depends(get_db)) -> StepOut:
    route = await db.get(ProductionRoute, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    section = await db.get(Section, payload.section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")
    if not section.is_active:
        raise HTTPException(status_code=400, detail="Inactive section cannot be used in route")
    if payload.sequence <= 0:
        raise HTTPException(status_code=400, detail="Sequence must be > 0")

    # Validate operation_code: NULL allowed (operation from source_payload),
    # or must exist in section_operations
    if payload.operation_code:
        op_exists = await db.scalar(
            select(SectionOperation.id).where(
                SectionOperation.section_id == payload.section_id,
                SectionOperation.operation_code == payload.operation_code,
            )
        )
        if not op_exists:
            raise HTTPException(
                status_code=400,
                detail=f"Operation '{payload.operation_code}' is not registered for section {payload.section_id}",
            )

    if payload.is_final:
        final_exists = await db.scalar(
            select(RouteStage).where(RouteStage.route_id == route_id, RouteStage.is_final.is_(True))
        )
        if final_exists:
            raise HTTPException(status_code=409, detail="Only one final step allowed")

    stage = RouteStage(
        route_id=route_id,
        sequence=payload.sequence,
        section_id=payload.section_id,
        norm_time_minutes=payload.norm_time_minutes,
        requires_acceptance=payload.requires_acceptance,
        allow_parallel=payload.allow_parallel,
        is_final=payload.is_final,
    )
    db.add(stage)
    await db.flush()
    
    op = RouteOperation(
        route_stage_id=stage.id,
        sequence=1,
        operation_code=payload.operation_code,
        operation_name=payload.operation_name,
    )
    db.add(op)
    await db.flush()
    await db.refresh(stage)

    section = await db.get(Section, stage.section_id)
    return StepOut(
        id=stage.id,
        route_id=stage.route_id,
        sequence=stage.sequence,
        section_id=stage.section_id,
        section_code=section.code if section else None,
        section_name=section.name if section else None,
        operation_code=op.operation_code,
        operation_name=op.operation_name,
        norm_time_minutes=stage.norm_time_minutes,
        is_final=stage.is_final,

    )


@router.put("/{route_id}/steps", response_model=list[StepOut])
async def replace_route_steps(route_id: int, payload: list[StepUpdate], db: AsyncSession = Depends(get_db)) -> list[StepOut]:
    route = await db.get(ProductionRoute, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")

    # Delete existing stages
    existing_stages = (await db.execute(select(RouteStage).where(RouteStage.route_id == route_id))).scalars().all()
    for stage in existing_stages:
        await db.delete(stage)
    await db.flush()

    # Create new stages & operations
    result = []
    for item in payload:
        if item.sequence <= 0:
            raise HTTPException(status_code=400, detail="Sequence must be > 0")
        section = await db.get(Section, item.section_id)
        if section is None:
            raise HTTPException(status_code=404, detail=f"Section {item.section_id} not found")
        if not section.is_active:
            raise HTTPException(status_code=400, detail=f"Inactive section {item.section_id}")

        # Validate operation_code: NULL allowed (operation from source_payload),
        # or must exist in section_operations
        if item.operation_code:
            op_exists = await db.scalar(
                select(SectionOperation.id).where(
                    SectionOperation.section_id == item.section_id,
                    SectionOperation.operation_code == item.operation_code,
                )
            )
            if not op_exists:
                raise HTTPException(
                    status_code=400,
                    detail=f"Operation '{item.operation_code}' is not registered for section {item.section_id}",
                )

        stage = RouteStage(
            route_id=route_id,
            sequence=item.sequence,
            section_id=item.section_id,
            norm_time_minutes=item.norm_time_minutes,
            requires_acceptance=item.requires_acceptance,
            allow_parallel=item.allow_parallel,
            is_final=item.is_final,
        )
        db.add(stage)
        await db.flush()

        op = RouteOperation(
            route_stage_id=stage.id,
            sequence=1,
            operation_code=item.operation_code,
            operation_name=item.operation_name,
        )
        db.add(op)
        await db.flush()
        await db.refresh(stage)

        section = await db.get(Section, stage.section_id)
        result.append(StepOut(
            id=stage.id,
            route_id=stage.route_id,
            sequence=stage.sequence,
            section_id=stage.section_id,
            section_code=section.code if section else None,
            section_name=section.name if section else None,
            operation_code=op.operation_code,
            operation_name=op.operation_name,
            norm_time_minutes=stage.norm_time_minutes,
            is_final=stage.is_final,
    
        ))
    return result
