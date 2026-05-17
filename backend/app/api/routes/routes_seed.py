"""Seed endpoint for standard routes and route selection rules.
Uses code-based upsert for idempotent seeding."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.route import ProductionRoute, RouteRuleProfile, RouteSelectionRule, RouteStep
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
    code: str | None = None
    name: str
    description: str | None = None
    is_active: bool
    steps: list[StepOut] = []


# 12 seeded routes with stable codes and characteristic names
DEFAULT_ROUTE_TEMPLATES = [
    {
        "code": "fg_drill_shot",
        "name": "ГП • Сверло",
        "description": "WH → DRILL → SHOT → ANOD → WIP_WH → SAW → PACK → FG_WH → SHIPMENT → SENT",
        "sort_order": 10,
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
        "code": "fg_press_shot",
        "name": "ГП • Пресс",
        "description": "WH → PRESS → SHOT → ANOD → WIP_WH → SAW → PACK → FG_WH → SHIPMENT → SENT",
        "sort_order": 20,
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
        "code": "fg_primary_none_shot",
        "name": "ГП",
        "description": "WH → SHOT → ANOD → WIP_WH → SAW → PACK → FG_WH → SHIPMENT → SENT",
        "sort_order": 30,
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
        "code": "fg_drill_no_shot",
        "name": "ГП • Сверло • Без дробеструя",
        "description": "WH → DRILL → ANOD → WIP_WH → SAW → PACK → FG_WH → SHIPMENT → SENT",
        "sort_order": 40,
        "steps": [
            {"section_code": "WH", "operation_code": "ISSUE_RAW", "operation_name": "Выдача сырья"},
            {"section_code": "DRILL", "operation_code": "DRILL", "operation_name": "Сверловка"},
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
        "code": "fg_press_no_shot",
        "name": "ГП • Пресс • Без дробеструя",
        "description": "WH → PRESS → ANOD → WIP_WH → SAW → PACK → FG_WH → SHIPMENT → SENT",
        "sort_order": 50,
        "steps": [
            {"section_code": "WH", "operation_code": "ISSUE_RAW", "operation_name": "Выдача сырья"},
            {"section_code": "PRESS", "operation_code": "PRESS", "operation_name": "Пресс"},
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
        "code": "fg_primary_none_no_shot",
        "name": "ГП • Без первичной • Без дробеструя",
        "description": "WH → ANOD → WIP_WH → SAW → PACK → FG_WH → SHIPMENT → SENT",
        "sort_order": 60,
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
        "code": "sf_drill_shot",
        "name": "П/ф • Сверло",
        "description": "WH → DRILL → SHOT → ANOD → FG_WH → SHIPMENT → SENT",
        "sort_order": 70,
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
        "code": "sf_press_shot",
        "name": "П/ф • Пресс",
        "description": "WH → PRESS → SHOT → ANOD → FG_WH → SHIPMENT → SENT",
        "sort_order": 80,
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
        "code": "sf_primary_none_shot",
        "name": "П/ф",
        "description": "WH → SHOT → ANOD → FG_WH → SHIPMENT → SENT",
        "sort_order": 90,
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
        "code": "sf_drill_no_shot",
        "name": "П/ф • Сверло • Без дробеструя",
        "description": "WH → DRILL → ANOD → FG_WH → SHIPMENT → SENT",
        "sort_order": 100,
        "steps": [
            {"section_code": "WH", "operation_code": "ISSUE_RAW", "operation_name": "Выдача сырья"},
            {"section_code": "DRILL", "operation_code": "DRILL", "operation_name": "Сверловка"},
            {"section_code": "ANOD", "operation_code": "ANOD", "operation_name": "Анодирование"},
            {"section_code": "FG_WH", "operation_code": "FG_WH", "operation_name": "Склад готовой продукции"},
            {"section_code": "SHIPMENT", "operation_code": "SHIPMENT", "operation_name": "К отгрузке"},
            {"section_code": "SENT", "operation_code": "SENT", "operation_name": "Отправлено", "is_final": True},
        ],
    },
    {
        "code": "sf_press_no_shot",
        "name": "П/ф • Пресс • Без дробеструя",
        "description": "WH → PRESS → ANOD → FG_WH → SHIPMENT → SENT",
        "sort_order": 110,
        "steps": [
            {"section_code": "WH", "operation_code": "ISSUE_RAW", "operation_name": "Выдача сырья"},
            {"section_code": "PRESS", "operation_code": "PRESS", "operation_name": "Пресс"},
            {"section_code": "ANOD", "operation_code": "ANOD", "operation_name": "Анодирование"},
            {"section_code": "FG_WH", "operation_code": "FG_WH", "operation_name": "Склад готовой продукции"},
            {"section_code": "SHIPMENT", "operation_code": "SHIPMENT", "operation_name": "К отгрузке"},
            {"section_code": "SENT", "operation_code": "SENT", "operation_name": "Отправлено", "is_final": True},
        ],
    },
    {
        "code": "sf_primary_none_no_shot",
        "name": "П/ф • Без первичной • Без дробеструя",
        "description": "WH → ANOD → FG_WH → SHIPMENT → SENT",
        "sort_order": 120,
        "steps": [
            {"section_code": "WH", "operation_code": "ISSUE_RAW", "operation_name": "Выдача сырья"},
            {"section_code": "ANOD", "operation_code": "ANOD", "operation_name": "Анодирование"},
            {"section_code": "FG_WH", "operation_code": "FG_WH", "operation_name": "Склад готовой продукции"},
            {"section_code": "SHIPMENT", "operation_code": "SHIPMENT", "operation_name": "К отгрузке"},
            {"section_code": "SENT", "operation_code": "SENT", "operation_name": "Отправлено", "is_final": True},
        ],
    },
]


DEFAULT_ROUTE_SELECTION_RULES = [
    {
        "code": "global_core_sections",
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
        "code": "global_drill",
        "name": "Операция сверловки",
        "priority": 900,
        "conditions": [("payload", "operation", "contains", "сверл")],
        "actions": [("require_section", "DRILL"), ("exclude_section", "PRESS")],
    },
    {
        "code": "global_press_window",
        "name": "Операция пресса: окно",
        "priority": 890,
        "conditions": [("payload", "operation", "contains", "окн")],
        "actions": [("require_section", "PRESS"), ("exclude_section", "DRILL")],
    },
    {
        "code": "global_press_comb",
        "name": "Операция пресса: гребенка",
        "priority": 880,
        "conditions": [("payload", "operation", "contains", "греб")],
        "actions": [("require_section", "PRESS"), ("exclude_section", "DRILL")],
    },
    {
        "code": "global_empty_primary",
        "name": "Без первичной операции",
        "priority": 800,
        "conditions": [("payload", "operation", "empty", None)],
        "actions": [("exclude_section", "DRILL"), ("exclude_section", "PRESS")],
    },
    {
        "code": "global_fg_branch",
        "name": "Готовая продукция",
        "priority": 700,
        "conditions": [("payload", "output_kind", "equals", "finished_good")],
        "actions": [("require_section", "WIP_WH"), ("require_section", "SAW"), ("require_section", "PACK")],
    },
    {
        "code": "global_sf_branch",
        "name": "Полуфабрикат к отгрузке",
        "priority": 700,
        "conditions": [("payload", "output_kind", "equals", "semi_finished_shipment")],
        "actions": [("exclude_section", "WIP_WH"), ("exclude_section", "SAW"), ("exclude_section", "PACK")],
    },
    {
        "code": "global_product_skip_shot",
        "name": "Продукт без дробеструя",
        "priority": 600,
        "conditions": [("product", "skip_shot_blast", "equals", True)],
        "actions": [("exclude_section", "SHOT")],
    },
    {
        "code": "global_product_require_shot",
        "name": "Продукт с дробеструем",
        "priority": 590,
        "conditions": [("product", "skip_shot_blast", "not_equals", True)],
        "actions": [("require_section", "SHOT")],
    },
]

DEFAULT_RULE_PROFILE = {
    "code": "packaging_map_rp",
    "name": "Упаковочная карта РП",
    "priority": 1000,
}


@router.post("", response_model=list[RouteOut], status_code=status.HTTP_201_CREATED)
async def seed_routes(db: AsyncSession = Depends(get_db)) -> list[RouteOut]:
    """Create or update the standard set of production routes and selection rules."""
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
        # Upsert by code first, then by name for legacy compatibility
        route = await db.scalar(select(ProductionRoute).where(ProductionRoute.code == template["code"]))
        if route is None:
            route = await db.scalar(select(ProductionRoute).where(ProductionRoute.name == template["name"]))

        if route is None:
            route = ProductionRoute(
                code=template["code"],
                name=template["name"],
                description=template["description"],
                is_active=True,
                sort_order=template["sort_order"],
            )
            db.add(route)
            await db.flush()
            await db.refresh(route)
        else:
            route.code = template["code"]
            route.name = template["name"]
            route.description = template["description"]
            route.is_active = True
            route.sort_order = template["sort_order"]

        # Replace all steps
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
                code=route.code,
                name=route.name,
                description=route.description,
                is_active=route.is_active,
                steps=steps_out,
            )
        )

    await _seed_route_selection_rules(db, sections_by_code)

    return result


async def _seed_route_selection_rules(db: AsyncSession, sections_by_code: dict[str, Section]) -> None:
    """Seed route selection rules under the default profile. Idempotent by code."""
    profile = await db.scalar(select(RouteRuleProfile).where(RouteRuleProfile.code == DEFAULT_RULE_PROFILE["code"]))
    if profile is None:
        profile = RouteRuleProfile(
            code=DEFAULT_RULE_PROFILE["code"],
            name=DEFAULT_RULE_PROFILE["name"],
            is_active=True,
            priority=DEFAULT_RULE_PROFILE["priority"],
        )
        db.add(profile)
        await db.flush()
    else:
        profile.name = DEFAULT_RULE_PROFILE["name"]
        profile.is_active = True
        profile.priority = DEFAULT_RULE_PROFILE["priority"]

    # Move all current global rules into the default profile.
    global_rules = (
        await db.execute(select(RouteSelectionRule).where(RouteSelectionRule.profile_id.is_(None)))
    ).scalars().all()
    for global_rule in global_rules:
        global_rule.profile_id = profile.id

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
        rule = await db.scalar(
            select(RouteSelectionRule).where(RouteSelectionRule.code == rule_def["code"])
        )
        if rule is None:
            rule = RouteSelectionRule(
                code=rule_def["code"],
                profile_id=profile.id,
            )
            db.add(rule)
        else:
            rule.profile_id = profile.id
        rule.name = rule_def["name"]
        rule.priority = rule_def["priority"]
        rule.is_active = True
        rule.conditions = conditions
        rule.actions = actions
    await db.flush()
