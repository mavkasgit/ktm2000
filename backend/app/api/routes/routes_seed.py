"""Временный эндпоинт для загрузки стандартных маршрутов.
Удалить после того как маршруты будут загружены на всех стендах."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.route import ProductionRoute, RouteSelectionRule, RouteStep
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
        "name": "Типовой: сверловка",
        "description": "WH → DRILL → SHOT → ANOD → WIP_WH → SAW → PACK → FG_WH → SHIPMENT → SENT",
        "steps": [
            {"section_code": "WH", "operation_code": "ISSUE_RAW", "operation_name": "Выдача сырья"},
            {"section_code": "DRILL", "operation_code": "DRILL", "operation_name": "Сверловка"},
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
        "description": "WH → PRESS → SHOT → ANOD → WIP_WH → SAW → PACK → FG_WH → SHIPMENT → SENT",
        "steps": [
            {"section_code": "WH", "operation_code": "ISSUE_RAW", "operation_name": "Выдача сырья"},
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
        "name": "Типовой: без пресса и сверла",
        "description": "WH → SHOT → ANOD → WIP_WH → SAW → PACK → FG_WH → SHIPMENT → SENT",
        "steps": [
            {"section_code": "WH", "operation_code": "ISSUE_RAW", "operation_name": "Выдача сырья"},
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
        "name": "Типовой: без пресса, сверла и дробеструя",
        "description": "WH → ANOD → WIP_WH → SAW → PACK → FG_WH → SHIPMENT → SENT",
        "steps": [
            {"section_code": "WH", "operation_code": "ISSUE_RAW", "operation_name": "Выдача сырья"},
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
        "name": "Типовой: без сверла, пресса и упаковки",
        "description": "WH → SHOT → ANOD → WIP_WH → SAW → FG_WH → SHIPMENT → SENT",
        "steps": [
            {"section_code": "WH", "operation_code": "ISSUE_RAW", "operation_name": "Выдача сырья"},
            {"section_code": "SHOT", "operation_code": "SHOT", "operation_name": "Дробеструй"},
            {"section_code": "ANOD", "operation_code": "ANOD", "operation_name": "Анодирование"},
            {"section_code": "WIP_WH", "operation_code": "MOVE_TO_WIP", "operation_name": "Передача на склад полуфабриката"},
            {"section_code": "SAW", "operation_code": "SAW", "operation_name": "Резка на пиле"},
            {"section_code": "FG_WH", "operation_code": "FG_WH", "operation_name": "Склад готовой продукции"},
            {"section_code": "SHIPMENT", "operation_code": "SHIPMENT", "operation_name": "К отгрузке"},
            {"section_code": "SENT", "operation_code": "SENT", "operation_name": "Отправлено", "is_final": True},
        ],
    },
    {
        "name": "Типовой: П/ф со сверловкой",
        "description": "WH → DRILL → SHOT → ANOD → FG_WH → SHIPMENT → SENT",
        "steps": [
            {"section_code": "WH", "operation_code": "ISSUE_RAW", "operation_name": "Выдача сырья"},
            {"section_code": "DRILL", "operation_code": "DRILL", "operation_name": "Сверловка"},
            {"section_code": "SHOT", "operation_code": "SHOT", "operation_name": "Дробеструй"},
            {"section_code": "ANOD", "operation_code": "ANOD", "operation_name": "Анодирование"},
            {"section_code": "FG_WH", "operation_code": "FG_WH", "operation_name": "Склад готовой продукции"},
            {"section_code": "SHIPMENT", "operation_code": "SHIPMENT", "operation_name": "К отгрузке"},
            {"section_code": "SENT", "operation_code": "SENT", "operation_name": "Отправлено", "is_final": True},
        ],
    },
    {
        "name": "Типовой: П/ф с прессом",
        "description": "WH → PRESS → SHOT → ANOD → FG_WH → SHIPMENT → SENT",
        "steps": [
            {"section_code": "WH", "operation_code": "ISSUE_RAW", "operation_name": "Выдача сырья"},
            {"section_code": "PRESS", "operation_code": "PRESS", "operation_name": "Пресс"},
            {"section_code": "SHOT", "operation_code": "SHOT", "operation_name": "Дробеструй"},
            {"section_code": "ANOD", "operation_code": "ANOD", "operation_name": "Анодирование"},
            {"section_code": "FG_WH", "operation_code": "FG_WH", "operation_name": "Склад готовой продукции"},
            {"section_code": "SHIPMENT", "operation_code": "SHIPMENT", "operation_name": "К отгрузке"},
            {"section_code": "SENT", "operation_code": "SENT", "operation_name": "Отправлено", "is_final": True},
        ],
    },
    {
        "name": "Типовой: П/ф без первичной",
        "description": "WH → SHOT → ANOD → FG_WH → SHIPMENT → SENT",
        "steps": [
            {"section_code": "WH", "operation_code": "ISSUE_RAW", "operation_name": "Выдача сырья"},
            {"section_code": "SHOT", "operation_code": "SHOT", "operation_name": "Дробеструй"},
            {"section_code": "ANOD", "operation_code": "ANOD", "operation_name": "Анодирование"},
            {"section_code": "FG_WH", "operation_code": "FG_WH", "operation_name": "Склад готовой продукции"},
            {"section_code": "SHIPMENT", "operation_code": "SHIPMENT", "operation_name": "К отгрузке"},
            {"section_code": "SENT", "operation_code": "SENT", "operation_name": "Отправлено", "is_final": True},
        ],
    },
    {
        "name": "Типовой: П/ф без первичной и дробеструя",
        "description": "WH → ANOD → FG_WH → SHIPMENT → SENT",
        "steps": [
            {"section_code": "WH", "operation_code": "ISSUE_RAW", "operation_name": "Выдача сырья"},
            {"section_code": "ANOD", "operation_code": "ANOD", "operation_name": "Анодирование"},
            {"section_code": "FG_WH", "operation_code": "FG_WH", "operation_name": "Склад готовой продукции"},
            {"section_code": "SHIPMENT", "operation_code": "SHIPMENT", "operation_name": "К отгрузке"},
            {"section_code": "SENT", "operation_code": "SENT", "operation_name": "Отправлено", "is_final": True},
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


DEFAULT_ROUTE_SELECTION_RULES = [
    {
        "code": "standard-core-sections",
        "name": "Базовые участки маршрута",
        "priority": 1000,
        "conditions": [],
        "actions": [
            ("require_section", "WH"),
            ("require_section", "ANOD"),
            ("require_section", "FG_WH"),
            ("require_section", "SHIPMENT"),
            ("require_section", "SENT"),
        ],
    },
    {
        "code": "standard-drill-operation",
        "name": "Операция сверловки",
        "priority": 900,
        "conditions": [("payload", "operation", "contains", "сверл")],
        "actions": [("require_section", "DRILL"), ("exclude_section", "PRESS")],
    },
    {
        "code": "standard-press-window-operation",
        "name": "Операция пресса: окно",
        "priority": 890,
        "conditions": [("payload", "operation", "contains", "окн")],
        "actions": [("require_section", "PRESS"), ("exclude_section", "DRILL")],
    },
    {
        "code": "standard-press-comb-operation",
        "name": "Операция пресса: гребенка",
        "priority": 880,
        "conditions": [("payload", "operation", "contains", "греб")],
        "actions": [("require_section", "PRESS"), ("exclude_section", "DRILL")],
    },
    {
        "code": "standard-empty-primary-operation",
        "name": "Без первичной операции",
        "priority": 800,
        "conditions": [("payload", "operation", "empty", None)],
        "actions": [("exclude_section", "DRILL"), ("exclude_section", "PRESS")],
    },
    {
        "code": "standard-finished-good-branch",
        "name": "Готовая продукция",
        "priority": 700,
        "conditions": [("payload", "output_kind", "equals", "finished_good")],
        "actions": [("require_section", "WIP_WH"), ("require_section", "SAW"), ("require_section", "PACK")],
    },
    {
        "code": "standard-semi-finished-branch",
        "name": "Полуфабрикат к отгрузке",
        "priority": 700,
        "conditions": [("payload", "output_kind", "equals", "semi_finished_shipment")],
        "actions": [("exclude_section", "WIP_WH"), ("exclude_section", "SAW"), ("exclude_section", "PACK")],
    },
    {
        "code": "standard-product-skip-shot",
        "name": "Продукт без дробеструя",
        "priority": 600,
        "conditions": [("product", "skip_shot_blast", "equals", True)],
        "actions": [("exclude_section", "SHOT")],
    },
    {
        "code": "standard-product-require-shot",
        "name": "Продукт с дробеструем",
        "priority": 590,
        "conditions": [("product", "skip_shot_blast", "not_equals", True)],
        "actions": [("require_section", "SHOT")],
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
    for route_order, template in enumerate(DEFAULT_ROUTE_TEMPLATES, start=1):
        route = await db.scalar(select(ProductionRoute).where(ProductionRoute.name == template["name"]))
        if route is None:
            route = ProductionRoute(name=template["name"], description=template["description"], is_active=True, sort_order=route_order * 10)
            db.add(route)
            await db.flush()
            await db.refresh(route)
        else:
            route.description = template["description"]
            route.is_active = True
            route.sort_order = route_order * 10

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

    await _seed_route_selection_rules(db, sections_by_code)

    return result


async def _seed_route_selection_rules(db: AsyncSession, sections_by_code: dict[str, Section]) -> None:
    for rule_def in DEFAULT_ROUTE_SELECTION_RULES:
        conditions = [
            {
                "source": source,
                "field_path": field_path,
                "operator": operator,
                "value": value,
                "case_sensitive": False,
            }
            for source, field_path, operator, value in rule_def["conditions"]
        ]
        actions = [
            {
                "action": action,
                "section_id": sections_by_code[section_code].id,
            }
            for action, section_code in rule_def["actions"]
        ]
        rule = await db.scalar(select(RouteSelectionRule).where(RouteSelectionRule.code == rule_def["code"]))
        if rule is None:
            rule = RouteSelectionRule(code=rule_def["code"])
            db.add(rule)
        rule.name = rule_def["name"]
        rule.priority = rule_def["priority"]
        rule.is_active = True
        rule.conditions = conditions
        rule.actions = actions
    await db.flush()
