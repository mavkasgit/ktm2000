"""Временный эндпоинт для загрузки стандартных маршрутов.
Удалить после того как маршруты будут загружены на всех стендах."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section

router = APIRouter(prefix="/routes-seed", tags=["routes-seed"])


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


class RouteOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    is_active: bool
    steps: list[StepOut] = []


# Один маршрут включающий все участки по порядку (по sort_order)
STEPS = [
    {"operation_name": "Приёмка сырья", "is_final": False},       # WH
    {"operation_name": "Сверловка", "is_final": False},           # DRILL
    {"operation_name": "Прессование", "is_final": False},         # PRESS
    {"operation_name": "Дробеструйная обработка", "is_final": False},  # SHOT
    {"operation_name": "Анодирование", "is_final": False},        # ANOD
    {"operation_name": "Склад полуфабриката", "is_final": False}, # WIP_WH
    {"operation_name": "Резка на пиле", "is_final": False},       # SAW
    {"operation_name": "Упаковка", "is_final": False},            # PACK
    {"operation_name": "Склад готовой продукции", "is_final": True},  # FG_WH
]


@router.post("", response_model=RouteOut, status_code=status.HTTP_201_CREATED)
async def seed_routes(db: AsyncSession = Depends(get_db)) -> RouteOut:
    """Создать маршрут включающий все участки по порядку."""
    # Получим все участки отсортированные по sort_order
    sections_result = await db.execute(select(Section).where(Section.is_active == True).order_by(Section.sort_order))
    sections = list(sections_result.scalars().all())

    if not sections:
        raise HTTPException(status_code=400, detail="Нет загруженных участков. Сначала загрузите участки.")

    if len(sections) != len(STEPS):
        raise HTTPException(status_code=400, detail=f"Ожидается {len(STEPS)} участков, найдено {len(sections)}")

    # Создаём или находим маршрут
    ROUTE_NAME = "Полный производственный маршрут"
    route = await db.scalar(select(ProductionRoute).where(ProductionRoute.name == ROUTE_NAME))
    if route is None:
        route = ProductionRoute(name=ROUTE_NAME, description="Все участки по порядку", is_active=True)
        db.add(route)
        await db.flush()
        await db.refresh(route)

    # Удаляем старые шаги
    existing_steps = (await db.execute(select(RouteStep).where(RouteStep.route_id == route.id))).scalars().all()
    for step in existing_steps:
        await db.delete(step)
    await db.flush()

    # Создаём шаги по порядку
    result_steps = []
    for i, (section, step_def) in enumerate(zip(sections, STEPS), start=1):
        step = RouteStep(
            route_id=route.id,
            sequence=i,
            section_id=section.id,
            operation_name=step_def["operation_name"],
            operation_code=section.code,
            is_final=step_def["is_final"],
            requires_acceptance=True,
            allow_parallel=False,
        )
        db.add(step)
        await db.flush()
        await db.refresh(step)
        result_steps.append(StepOut(
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

    return RouteOut(
        id=route.id,
        name=route.name,
        description=route.description,
        is_active=route.is_active,
        steps=result_steps,
    )
