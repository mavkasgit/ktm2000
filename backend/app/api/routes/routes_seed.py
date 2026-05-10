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


DEFAULT_ROUTE_TEMPLATES = [
    {
        "name": "Типовой: полный (все участки)",
        "description": "WH → DRILL → PRESS → SHOT → ANOD → WIP_WH → SAW → PACK → FG_WH → SHIPMENT → SENT",
        "steps": [
            {"section_code": "WH", "operation_code": "ISSUE_RAW", "operation_name": "Выдача сырья"},
            {"section_code": "DRILL", "operation_code": "DRILL", "operation_name": "Сверловка"},
            {"section_code": "PRESS", "operation_code": "PRESS", "operation_name": "Пресс"},
            {"section_code": "SHOT", "operation_code": "SHOT", "operation_name": "Дробеструй"},
            {"section_code": "ANOD", "operation_code": "ANOD", "operation_name": "Анодирование"},
            {"section_code": "WIP_WH", "operation_code": "MOVE_TO_WIP", "operation_name": "Передача на склад полуфабриката"},
            {"section_code": "SAW", "operation_code": "SAW", "operation_name": "Резка на пиле"},
            {"section_code": "PACK", "operation_code": "PACK", "operation_name": "Упаковка"},
            {"section_code": "FG_WH", "operation_code": "FG_WH", "operation_name": "Склад готовой продукции"},
            {"section_code": "SHIPMENT", "operation_code": "SHIPMENT", "operation_name": "К отгрузке"},
            {"section_code": "SENT", "operation_code": "SENT", "operation_name": "Отправлено", "is_final": True},
        ],
    },
    {
        "name": "Типовой: без сверла",
        "description": "WH → PRESS → SHOT → ANOD → WIP_WH → SAW → PACK → FG_WH",
        "steps": [
            {"section_code": "WH", "operation_code": "ISSUE_RAW", "operation_name": "Выдача сырья"},
            {"section_code": "PRESS", "operation_code": "PRESS", "operation_name": "Пресс"},
            {"section_code": "SHOT", "operation_code": "SHOT", "operation_name": "Дробеструй"},
            {"section_code": "ANOD", "operation_code": "ANOD", "operation_name": "Анодирование"},
            {"section_code": "WIP_WH", "operation_code": "MOVE_TO_WIP", "operation_name": "Передача на склад полуфабриката"},
            {"section_code": "SAW", "operation_code": "SAW", "operation_name": "Резка на пиле"},
            {"section_code": "PACK", "operation_code": "PACK", "operation_name": "Упаковка"},
            {"section_code": "FG_WH", "operation_code": "ACCEPT_FINISHED", "operation_name": "Приемка готовой продукции", "is_final": True},
        ],
    },
    {
        "name": "Типовой: без пресса и сверла",
        "description": "WH → SHOT → ANOD → WIP_WH → SAW → PACK → FG_WH",
        "steps": [
            {"section_code": "WH", "operation_code": "ISSUE_RAW", "operation_name": "Выдача сырья"},
            {"section_code": "SHOT", "operation_code": "SHOT", "operation_name": "Дробеструй"},
            {"section_code": "ANOD", "operation_code": "ANOD", "operation_name": "Анодирование"},
            {"section_code": "WIP_WH", "operation_code": "MOVE_TO_WIP", "operation_name": "Передача на склад полуфабриката"},
            {"section_code": "SAW", "operation_code": "SAW", "operation_name": "Резка на пиле"},
            {"section_code": "PACK", "operation_code": "PACK", "operation_name": "Упаковка"},
            {"section_code": "FG_WH", "operation_code": "ACCEPT_FINISHED", "operation_name": "Приемка готовой продукции", "is_final": True},
        ],
    },
    {
        "name": "Типовой: без пресса, сверла и дробеструя",
        "description": "WH → ANOD → WIP_WH → SAW → PACK → FG_WH",
        "steps": [
            {"section_code": "WH", "operation_code": "ISSUE_RAW", "operation_name": "Выдача сырья"},
            {"section_code": "ANOD", "operation_code": "ANOD", "operation_name": "Анодирование"},
            {"section_code": "WIP_WH", "operation_code": "MOVE_TO_WIP", "operation_name": "Передача на склад полуфабриката"},
            {"section_code": "SAW", "operation_code": "SAW", "operation_name": "Резка на пиле"},
            {"section_code": "PACK", "operation_code": "PACK", "operation_name": "Упаковка"},
            {"section_code": "FG_WH", "operation_code": "ACCEPT_FINISHED", "operation_name": "Приемка готовой продукции", "is_final": True},
        ],
    },
    {
        "name": "Типовой: без сверла, пресса и упаковки",
        "description": "WH → SHOT → ANOD → WIP_WH → SAW → FG_WH",
        "steps": [
            {"section_code": "WH", "operation_code": "ISSUE_RAW", "operation_name": "Выдача сырья"},
            {"section_code": "SHOT", "operation_code": "SHOT", "operation_name": "Дробеструй"},
            {"section_code": "ANOD", "operation_code": "ANOD", "operation_name": "Анодирование"},
            {"section_code": "WIP_WH", "operation_code": "MOVE_TO_WIP", "operation_name": "Передача на склад полуфабриката"},
            {"section_code": "SAW", "operation_code": "SAW", "operation_name": "Резка на пиле"},
            {"section_code": "FG_WH", "operation_code": "ACCEPT_FINISHED", "operation_name": "Приемка готовой продукции", "is_final": True},
        ],
    },
    {
        "name": "Типовой: отгрузочный",
        "description": "FG_WH → SHIPMENT → SENT",
        "steps": [
            {"section_code": "FG_WH", "operation_code": "FG_WH", "operation_name": "Склад готовой продукции"},
            {"section_code": "SHIPMENT", "operation_code": "SHIPMENT", "operation_name": "К отгрузке"},
            {"section_code": "SENT", "operation_code": "SENT", "operation_name": "Отправлено", "is_final": True},
        ],
    },
]


@router.post("", response_model=list[RouteOut], status_code=status.HTTP_201_CREATED)
async def seed_routes(db: AsyncSession = Depends(get_db)) -> list[RouteOut]:
    """Создать или обновить набор типовых маршрутов."""
    sections_result = await db.execute(select(Section).where(Section.is_active == True))
    sections = list(sections_result.scalars().all())
    sections_by_code = {section.code: section for section in sections}

    required_codes = sorted({step["section_code"] for template in DEFAULT_ROUTE_TEMPLATES for step in template["steps"]})
    missing_codes = [code for code in required_codes if code not in sections_by_code]
    if missing_codes:
        raise HTTPException(
            status_code=400,
            detail=f"Не найдены участки для маршрутов: {', '.join(missing_codes)}. Сначала загрузите стандартные участки.",
        )

    result: list[RouteOut] = []
    for template in DEFAULT_ROUTE_TEMPLATES:
        route = await db.scalar(select(ProductionRoute).where(ProductionRoute.name == template["name"]))
        if route is None:
            route = ProductionRoute(name=template["name"], description=template["description"], is_active=True)
            db.add(route)
            await db.flush()
            await db.refresh(route)
        else:
            route.description = template["description"]
            route.is_active = True

        existing_steps = (await db.execute(select(RouteStep).where(RouteStep.route_id == route.id))).scalars().all()
        for existing in existing_steps:
            await db.delete(existing)
        await db.flush()

        steps_out: list[StepOut] = []
        for idx, step_def in enumerate(template["steps"], start=1):
            section = sections_by_code[step_def["section_code"]]
            step = RouteStep(
                route_id=route.id,
                sequence=idx,
                section_id=section.id,
                operation_code=step_def["operation_code"],
                operation_name=step_def["operation_name"],
                is_final=bool(step_def.get("is_final", False)),
                requires_acceptance=True,
                allow_parallel=False,
            )
            db.add(step)
            await db.flush()
            await db.refresh(step)
            steps_out.append(
                StepOut(
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
                )
            )

        result.append(
            RouteOut(
                id=route.id,
                name=route.name,
                description=route.description,
                is_active=route.is_active,
                steps=steps_out,
            )
        )

    return result
