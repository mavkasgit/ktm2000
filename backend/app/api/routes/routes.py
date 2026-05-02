from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.product import Product
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section

router = APIRouter(prefix="/routes", tags=["routes"])


class RouteCreate(BaseModel):
    product_id: int
    name: str
    version: str
    is_active: bool = True


class RoutePatch(BaseModel):
    name: str | None = None
    version: str | None = None
    is_active: bool | None = None


class StepCreate(BaseModel):
    sequence: int
    section_id: int
    operation_name: str
    norm_time_minutes: int | None = None
    requires_acceptance: bool = True
    allow_parallel: bool = False
    is_final: bool = False


class RouteOut(RouteCreate):
    id: int


class StepOut(StepCreate):
    id: int
    route_id: int


@router.post("", response_model=RouteOut, status_code=status.HTTP_201_CREATED)
async def create_route(payload: RouteCreate, db: AsyncSession = Depends(get_db)) -> RouteOut:
    product = await db.get(Product, payload.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    item = ProductionRoute(**payload.model_dump())
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return RouteOut.model_validate(item, from_attributes=True)


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
    return StepOut.model_validate(step, from_attributes=True)


@router.patch("/{route_id}", response_model=RouteOut)
async def patch_route(route_id: int, payload: RoutePatch, db: AsyncSession = Depends(get_db)) -> RouteOut:
    item = await db.get(ProductionRoute, route_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Route not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await db.flush()
    await db.refresh(item)
    return RouteOut.model_validate(item, from_attributes=True)
