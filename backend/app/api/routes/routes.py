from fastapi import APIRouter, Depends, HTTPException, Query, status
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
    stage_kind: str = "production"
    storage_section_id: int | None = None



class StepUpdate(BaseModel):
    sequence: int
    section_id: int
    operation_code: str | None = None
    operation_name: str
    norm_time_minutes: int | None = None
    requires_acceptance: bool = True
    allow_parallel: bool = False
    is_final: bool = False
    stage_kind: str = "production"
    storage_section_id: int | None = None



class RuleOut(BaseModel):
    id: int
    route_id: int
    priority: int
    is_active: bool = True


class StepOut(BaseModel):
    id: int
    route_id: int
    sequence: int
    section_id: int | None
    section_code: str | None = None
    section_name: str | None = None
    operation_code: str | None = None
    operation_name: str
    norm_time_minutes: int | None = None
    is_final: bool
    allow_parallel: bool = False
    stage_kind: str = "production"
    storage_section_id: int | None = None


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


def _resolve_section_for_stage(
    stage: RouteStage,
    sections_cache: dict[int, Section] | None,
) -> Section | None:
    if stage.stage_kind == "transit":
        section_id = stage.storage_section_id
    else:
        section_id = stage.section_id
    if section_id is None:
        return None
    if sections_cache is not None:
        return sections_cache.get(section_id)
    return None


def _build_route_steps(
    route: ProductionRoute,
    sections_cache: dict[int, Section] | None = None,
) -> list[StepOut]:
    steps: list[StepOut] = []
    sorted_stages = sorted(route.stages, key=lambda s: s.sequence)
    for stage in sorted_stages:
        section = _resolve_section_for_stage(stage, sections_cache)
        op_code = None
        op_name = ""
        if stage.operations:
            sorted_ops = sorted(stage.operations, key=lambda o: o.sequence)
            op_code = sorted_ops[0].operation_code
            op_name = sorted_ops[0].operation_name
        if stage.stage_kind == "transit" and section is not None:
            op_name = f"Транзит через {section.name}"

        steps.append(StepOut(
            id=stage.id,
            route_id=stage.route_id,
            sequence=stage.sequence,
            section_id=stage.section_id,
            section_code=section.code if section else None,
            section_name=section.name if section else None,
            operation_code=op_code,
            operation_name=op_name,
            norm_time_minutes=stage.norm_time_minutes,
            is_final=stage.is_final,
            allow_parallel=stage.allow_parallel,
            stage_kind=stage.stage_kind,
            storage_section_id=stage.storage_section_id,
        ))
    return steps


async def _load_route_rules(route_id: int, db: AsyncSession) -> list[RuleOut]:
    rules_result = await db.execute(
        select(RouteMatchingRule)
        .where(RouteMatchingRule.route_id == route_id)
        .order_by(RouteMatchingRule.priority.desc(), RouteMatchingRule.id.asc())
    )
    return [
        RuleOut(
            id=rule.id,
            route_id=rule.route_id,
            priority=rule.priority,
            is_active=True,
        )
        for rule in rules_result.scalars().all()
    ]


async def _build_route_detail(
    route: ProductionRoute,
    db: AsyncSession,
    sections_cache: dict[int, Section] | None = None,
    rules: list[RuleOut] | None = None,
) -> RouteDetailOut:
    steps = _build_route_steps(route, sections_cache)
    if rules is None:
        rules = await _load_route_rules(route.id, db)
    return RouteDetailOut(
        id=route.id,
        name=route.name,
        description=route.description,
        is_active=route.is_active,
        steps=steps,
        rules=rules,
    )


async def _load_sections_cache(
    routes: list[ProductionRoute],
    db: AsyncSession,
) -> dict[int, Section]:
    section_ids: set[int] = set()
    for route in routes:
        for stage in route.stages:
            if stage.stage_kind == "transit" and stage.storage_section_id:
                section_ids.add(stage.storage_section_id)
            elif stage.section_id:
                section_ids.add(stage.section_id)
    if not section_ids:
        return {}
    sections_result = await db.execute(select(Section).where(Section.id.in_(section_ids)))
    return {section.id: section for section in sections_result.scalars().all()}


async def _load_rules_by_route(
    route_ids: list[int],
    db: AsyncSession,
) -> dict[int, list[RuleOut]]:
    rules_by_route: dict[int, list[RuleOut]] = {route_id: [] for route_id in route_ids}
    if not route_ids:
        return rules_by_route
    rules_result = await db.execute(
        select(RouteMatchingRule)
        .where(RouteMatchingRule.route_id.in_(route_ids))
        .order_by(RouteMatchingRule.priority.desc(), RouteMatchingRule.id.asc())
    )
    for rule in rules_result.scalars().all():
        rules_by_route[rule.route_id].append(RuleOut(
            id=rule.id,
            route_id=rule.route_id,
            priority=rule.priority,
            is_active=True,
        ))
    return rules_by_route


@router.post("/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_routes(payload: ReorderRoutesIn, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import update
    for idx, route_id in enumerate(payload.ids):
        await db.execute(
            update(ProductionRoute).where(ProductionRoute.id == route_id).values(sort_order=idx * 10)
        )
    await db.flush()


# --- Endpoints ---

@router.get("")
async def list_routes(
    q: str | None = None,
    include_steps: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> list[RouteOut] | list[RouteDetailOut]:
    stmt = select(ProductionRoute).order_by(ProductionRoute.sort_order, ProductionRoute.name)
    if include_steps:
        stmt = stmt.options(
            selectinload(ProductionRoute.stages).selectinload(RouteStage.operations),
        )
    if q:
        stmt = stmt.where(ProductionRoute.name.ilike(f"%{q}%"))
    rows = (await db.execute(stmt)).scalars().all()
    if not include_steps:
        return [RouteOut.model_validate(r, from_attributes=True) for r in rows]

    sections_cache = await _load_sections_cache(rows, db)
    rules_by_route = await _load_rules_by_route([route.id for route in rows], db)
    return [
        await _build_route_detail(
            route,
            db,
            sections_cache=sections_cache,
            rules=rules_by_route.get(route.id, []),
        )
        for route in rows
    ]


@router.get("/{route_id}", response_model=RouteDetailOut)
async def get_route(route_id: int, db: AsyncSession = Depends(get_db)) -> RouteDetailOut:
    route = await db.get(ProductionRoute, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")

    sections_cache = await _load_sections_cache([route], db)
    return await _build_route_detail(route, db, sections_cache=sections_cache)


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
    from app.services.route_storage_classifier import is_storage_section

    route = await db.get(ProductionRoute, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    if payload.sequence <= 0:
        raise HTTPException(status_code=400, detail="Sequence must be > 0")

    stage_kind = payload.stage_kind or "production"
    if stage_kind not in ("production", "transit"):
        raise HTTPException(status_code=400, detail=f"Unknown stage_kind '{stage_kind}'")

    section: Section | None = None
    storage_section: Section | None = None

    if stage_kind == "transit":
        sid = payload.storage_section_id or payload.section_id
        if sid is None:
            raise HTTPException(
                status_code=400,
                detail="Transit stage requires storage_section_id (or section_id pointing to a storage section)",
            )
        storage_section = await db.get(Section, sid)
        if storage_section is None:
            raise HTTPException(status_code=404, detail=f"Storage section {sid} not found")
        if not storage_section.is_active:
            raise HTTPException(status_code=400, detail="Inactive storage section cannot be used in route")
        if not is_storage_section(storage_section):
            raise HTTPException(
                status_code=400,
                detail=f"Section {sid} (type={storage_section.type}) is not a storage section",
            )
        if payload.is_final:
            raise HTTPException(status_code=400, detail="Transit stage cannot be marked as final")
    else:
        section = await db.get(Section, payload.section_id)
        if section is None:
            raise HTTPException(status_code=404, detail="Section not found")
        if not section.is_active:
            raise HTTPException(status_code=400, detail="Inactive section cannot be used in route")
        if is_storage_section(section):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Section {section.id} ({section.code}) is a storage section. "
                    "To add it as a transit hop set stage_kind='transit'."
                ),
            )

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
        section_id=section.id if section else None,
        stage_kind=stage_kind,
        storage_section_id=storage_section.id if storage_section else None,
        norm_time_minutes=payload.norm_time_minutes,
        requires_acceptance=payload.requires_acceptance,
        allow_parallel=payload.allow_parallel,
        is_final=payload.is_final,
    )
    db.add(stage)
    await db.flush()

    op = None
    if stage_kind == "production":
        op = RouteOperation(
            route_stage_id=stage.id,
            sequence=1,
            operation_code=payload.operation_code,
            operation_name=payload.operation_name,
        )
        db.add(op)
        await db.flush()
    await db.refresh(stage)

    if stage_kind == "transit":
        section_for_response = storage_section
    else:
        section_for_response = section
    return StepOut(
        id=stage.id,
        route_id=stage.route_id,
        sequence=stage.sequence,
        section_id=stage.section_id,
        section_code=section_for_response.code if section_for_response else None,
        section_name=section_for_response.name if section_for_response else None,
        operation_code=op.operation_code if op else None,
        operation_name=op.operation_name if op else f"Транзит через {storage_section.name if storage_section else ''}",
        norm_time_minutes=stage.norm_time_minutes,
        is_final=stage.is_final,
        allow_parallel=stage.allow_parallel,
        stage_kind=stage.stage_kind,
        storage_section_id=stage.storage_section_id,
    )


@router.put("/{route_id}/steps", response_model=list[StepOut])
async def replace_route_steps(route_id: int, payload: list[StepUpdate], db: AsyncSession = Depends(get_db)) -> list[StepOut]:
    from app.services.route_storage_classifier import is_storage_section

    route = await db.get(ProductionRoute, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")

    existing_stages = (await db.execute(select(RouteStage).where(RouteStage.route_id == route_id))).scalars().all()
    for stage in existing_stages:
        await db.delete(stage)
    await db.flush()

    result = []
    for item in payload:
        if item.sequence <= 0:
            raise HTTPException(status_code=400, detail="Sequence must be > 0")
        stage_kind = item.stage_kind or "production"
        if stage_kind not in ("production", "transit"):
            raise HTTPException(status_code=400, detail=f"Unknown stage_kind '{stage_kind}'")

        section: Section | None = None
        storage_section: Section | None = None

        if stage_kind == "transit":
            sid = item.storage_section_id or item.section_id
            if sid is None:
                raise HTTPException(
                    status_code=400,
                    detail="Transit stage requires storage_section_id (or section_id pointing to a storage section)",
                )
            storage_section = await db.get(Section, sid)
            if storage_section is None:
                raise HTTPException(status_code=404, detail=f"Storage section {sid} not found")
            if not storage_section.is_active:
                raise HTTPException(status_code=400, detail="Inactive storage section cannot be used in route")
            if not is_storage_section(storage_section):
                raise HTTPException(
                    status_code=400,
                    detail=f"Section {sid} (type={storage_section.type}) is not a storage section",
                )
            if item.is_final:
                raise HTTPException(status_code=400, detail="Transit stage cannot be marked as final")
        else:
            section = await db.get(Section, item.section_id)
            if section is None:
                raise HTTPException(status_code=404, detail=f"Section {item.section_id} not found")
            if not section.is_active:
                raise HTTPException(status_code=400, detail=f"Inactive section {item.section_id}")
            if is_storage_section(section):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Section {section.id} ({section.code}) is a storage section. "
                        "To add it as a transit hop set stage_kind='transit'."
                    ),
                )

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
            section_id=section.id if section else None,
            stage_kind=stage_kind,
            storage_section_id=storage_section.id if storage_section else None,
            norm_time_minutes=item.norm_time_minutes,
            requires_acceptance=item.requires_acceptance,
            allow_parallel=item.allow_parallel,
            is_final=item.is_final,
        )
        db.add(stage)
        await db.flush()

        op = None
        if stage_kind == "production":
            op = RouteOperation(
                route_stage_id=stage.id,
                sequence=1,
                operation_code=item.operation_code,
                operation_name=item.operation_name,
            )
            db.add(op)
            await db.flush()
        await db.refresh(stage)

        if stage_kind == "transit":
            section_for_response = storage_section
        else:
            section_for_response = section
        result.append(StepOut(
            id=stage.id,
            route_id=stage.route_id,
            sequence=stage.sequence,
            section_id=stage.section_id,
            section_code=section_for_response.code if section_for_response else None,
            section_name=section_for_response.name if section_for_response else None,
            operation_code=op.operation_code if op else None,
            operation_name=op.operation_name if op else f"Транзит через {storage_section.name if storage_section else ''}",
            norm_time_minutes=stage.norm_time_minutes,
            is_final=stage.is_final,
            allow_parallel=stage.allow_parallel,
            stage_kind=stage.stage_kind,
            storage_section_id=stage.storage_section_id,
        ))
    return result
