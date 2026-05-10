from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.route import ProductionRoute, RouteMatchingRule, RouteRuleCondition, RouteStep
from app.models.section import Section
from app.models.internal_plan import SectionPlanLine
from app.models.release_batch import ReleaseBatchPosition
from app.models.production_plan import PlanPosition, PlanChangeItem

router = APIRouter(prefix="/routes", tags=["routes"])


# --- Pydantic schemas ---

class RouteConditionIn(BaseModel):
    field: str
    operator: str
    value: str


class RouteRuleIn(BaseModel):
    priority: int = 0
    conditions: list[RouteConditionIn] = []


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


class ConditionOut(BaseModel):
    field: str
    operator: str
    value: str

    model_config = {"from_attributes": True}


class RuleOut(BaseModel):
    id: int
    route_id: int
    priority: int
    conditions: list[ConditionOut] = []


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


# --- Endpoints ---

@router.get("", response_model=list[RouteOut])
async def list_routes(
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[RouteOut]:
    stmt = select(ProductionRoute).order_by(ProductionRoute.name)
    if q:
        stmt = stmt.where(ProductionRoute.name.ilike(f"%{q}%"))
    rows = (await db.execute(stmt)).scalars().all()
    return [RouteOut.model_validate(r, from_attributes=True) for r in rows]


@router.get("/{route_id}", response_model=RouteDetailOut)
async def get_route(route_id: int, db: AsyncSession = Depends(get_db)) -> RouteDetailOut:
    route = await db.get(ProductionRoute, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")

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

    rules = []
    for rule in route.rules:
        rules.append(RuleOut(
            id=rule.id,
            route_id=rule.route_id,
            priority=rule.priority,
            conditions=[ConditionOut.model_validate(c, from_attributes=True) for c in rule.conditions],
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

    steps_count = await db.scalar(select(func.count()).select_from(RouteStep).where(RouteStep.route_id == route_id))
    rules_count = await db.scalar(select(func.count()).select_from(RouteMatchingRule).where(RouteMatchingRule.route_id == route_id))
    spl_count = await db.scalar(select(func.count()).select_from(SectionPlanLine).where(SectionPlanLine.route_id == route_id))
    rbp_count = await db.scalar(select(func.count()).select_from(ReleaseBatchPosition).where(ReleaseBatchPosition.route_id == route_id))
    plan_positions_count = await db.scalar(select(func.count()).select_from(PlanPosition).where(PlanPosition.route_id == route_id))

    warning_parts = []
    if steps_count:
        warning_parts.append(f"{steps_count} шаг(ов) маршрута")
    if rules_count:
        warning_parts.append(f"{rules_count} правило(ок) привязки")
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
        "rules_count": rules_count or 0,
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
    steps_count = await db.scalar(select(func.count()).select_from(RouteStep).where(RouteStep.route_id == route_id))
    rules_count = await db.scalar(select(func.count()).select_from(RouteMatchingRule).where(RouteMatchingRule.route_id == route_id))
    spl_count = await db.scalar(select(func.count()).select_from(SectionPlanLine).where(SectionPlanLine.route_id == route_id))
    rbp_count = await db.scalar(select(func.count()).select_from(ReleaseBatchPosition).where(ReleaseBatchPosition.route_id == route_id))
    plan_positions_count = await db.scalar(select(func.count()).select_from(PlanPosition).where(PlanPosition.route_id == route_id))

    # If not force deletion and there are relations, return warning
    if not force_bool and (steps_count or rules_count or spl_count or rbp_count or plan_positions_count):
        warning_parts = []
        if steps_count:
            warning_parts.append(f"{steps_count} шаг(ов) маршрута")
        if rules_count:
            warning_parts.append(f"{rules_count} правило(ок) привязки")
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
        await db.execute(delete(RouteStep).where(RouteStep.route_id == route_id))
    if rules_count:
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

    if payload.is_final:
        final_exists = await db.scalar(
            select(RouteStep).where(RouteStep.route_id == route_id, RouteStep.is_final.is_(True))
        )
        if final_exists:
            raise HTTPException(status_code=409, detail="Only one final step allowed")

    step = RouteStep(route_id=route_id, **payload.model_dump())
    db.add(step)
    await db.flush()
    await db.refresh(step)
    section = await db.get(Section, step.section_id)
    return StepOut(
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
    )


@router.put("/{route_id}/steps", response_model=list[StepOut])
async def replace_route_steps(route_id: int, payload: list[StepUpdate], db: AsyncSession = Depends(get_db)) -> list[StepOut]:
    route = await db.get(ProductionRoute, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")

    # Delete existing steps
    existing_steps = (await db.execute(select(RouteStep).where(RouteStep.route_id == route_id))).scalars().all()
    for step in existing_steps:
        await db.delete(step)
    await db.flush()

    # Create new steps
    result = []
    for item in payload:
        if item.sequence <= 0:
            raise HTTPException(status_code=400, detail="Sequence must be > 0")
        section = await db.get(Section, item.section_id)
        if section is None:
            raise HTTPException(status_code=404, detail=f"Section {item.section_id} not found")
        if not section.is_active:
            raise HTTPException(status_code=400, detail=f"Inactive section {item.section_id}")

        step = RouteStep(
            route_id=route_id,
            sequence=item.sequence,
            section_id=item.section_id,
            operation_code=item.operation_code,
            operation_name=item.operation_name,
            norm_time_minutes=item.norm_time_minutes,
            requires_acceptance=item.requires_acceptance,
            allow_parallel=item.allow_parallel,
            is_final=item.is_final,
        )
        db.add(step)
        await db.flush()
        await db.refresh(step)
        result.append(StepOut(
            id=step.id,
            route_id=step.route_id,
            sequence=step.sequence,
            section_id=step.section_id,
            section_code=section.code,
            section_name=section.name,
            operation_code=step.operation_code,
            operation_name=step.operation_name,
            norm_time_minutes=step.norm_time_minutes,
            is_final=step.is_final,
        ))
    return result


@router.post("/{route_id}/rules", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
async def add_route_rule(route_id: int, payload: RouteRuleIn, db: AsyncSession = Depends(get_db)) -> RuleOut:
    route = await db.get(ProductionRoute, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")

    rule = RouteMatchingRule(route_id=route_id, priority=payload.priority)
    db.add(rule)
    await db.flush()

    for cond in payload.conditions:
        db.add(RouteRuleCondition(rule_id=rule.id, field=cond.field, operator=cond.operator, value=cond.value))
    await db.flush()
    await db.refresh(rule)

    return RuleOut(
        id=rule.id,
        route_id=rule.route_id,
        priority=rule.priority,
        conditions=[ConditionOut.model_validate(c, from_attributes=True) for c in rule.conditions],
    )


@router.delete("/{route_id}/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route_rule(route_id: int, rule_id: int, db: AsyncSession = Depends(get_db)) -> None:
    rule = await db.get(RouteMatchingRule, rule_id)
    if rule is None or rule.route_id != route_id:
        raise HTTPException(status_code=404, detail="Rule not found")
    await db.delete(rule)
    await db.flush()
