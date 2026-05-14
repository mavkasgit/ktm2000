from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import delete, select

from app.core.database import async_session
from app.models.route import ProductionRoute, RouteSignatureRule, RouteStep
from app.models.routing import RouteOperationFamily, RouteOutputKind
from app.models.section import Section


@dataclass(frozen=True)
class StepDef:
    section_code: str
    operation_code: str
    operation_name: str
    is_final: bool = False


@dataclass(frozen=True)
class RouteTemplate:
    name: str
    description: str
    steps: tuple[StepDef, ...]


@dataclass(frozen=True)
class RuleDef:
    operation_family: RouteOperationFamily
    output_kind: RouteOutputKind
    has_pack_ops: bool | None
    route_name: str
    priority: int


def _templates() -> tuple[RouteTemplate, ...]:
    return (
        RouteTemplate(
            name="Типовой: ГП со сверлом",
            description="WH → DRILL → SHOT → ANOD → WIP_WH → SAW → PACK → FG_WH",
            steps=(
                StepDef("WH", "ISSUE_RAW", "Выдача сырья"),
                StepDef("DRILL", "DRILL", "Сверловка"),
                StepDef("SHOT", "SHOT", "Дробеструй"),
                StepDef("ANOD", "ANOD", "Анодирование"),
                StepDef("WIP_WH", "MOVE_TO_WIP", "Передача на склад полуфабриката"),
                StepDef("SAW", "SAW", "Резка на пиле"),
                StepDef("PACK", "PACK", "Упаковка"),
                StepDef("FG_WH", "ACCEPT_FINISHED", "Приемка готовой продукции", True),
            ),
        ),
        RouteTemplate(
            name="Типовой: ГП с прессом",
            description="WH → PRESS → SHOT → ANOD → WIP_WH → SAW → PACK → FG_WH",
            steps=(
                StepDef("WH", "ISSUE_RAW", "Выдача сырья"),
                StepDef("PRESS", "PRESS", "Пресс"),
                StepDef("SHOT", "SHOT", "Дробеструй"),
                StepDef("ANOD", "ANOD", "Анодирование"),
                StepDef("WIP_WH", "MOVE_TO_WIP", "Передача на склад полуфабриката"),
                StepDef("SAW", "SAW", "Резка на пиле"),
                StepDef("PACK", "PACK", "Упаковка"),
                StepDef("FG_WH", "ACCEPT_FINISHED", "Приемка готовой продукции", True),
            ),
        ),
        RouteTemplate(
            name="Типовой: ГП базовый",
            description="WH → SHOT → ANOD → WIP_WH → SAW → PACK → FG_WH",
            steps=(
                StepDef("WH", "ISSUE_RAW", "Выдача сырья"),
                StepDef("SHOT", "SHOT", "Дробеструй"),
                StepDef("ANOD", "ANOD", "Анодирование"),
                StepDef("WIP_WH", "MOVE_TO_WIP", "Передача на склад полуфабриката"),
                StepDef("SAW", "SAW", "Резка на пиле"),
                StepDef("PACK", "PACK", "Упаковка"),
                StepDef("FG_WH", "ACCEPT_FINISHED", "Приемка готовой продукции", True),
            ),
        ),
        RouteTemplate(
            name="Типовой: П/ф со сверлом",
            description="WH → DRILL → SHOT → ANOD → FG_WH → SHIPMENT → SENT",
            steps=(
                StepDef("WH", "ISSUE_RAW", "Выдача сырья"),
                StepDef("DRILL", "DRILL", "Сверловка"),
                StepDef("SHOT", "SHOT", "Дробеструй"),
                StepDef("ANOD", "ANOD", "Анодирование"),
                StepDef("FG_WH", "ACCEPT_FINISHED", "Приемка готовой продукции"),
                StepDef("SHIPMENT", "SHIPMENT", "К отгрузке"),
                StepDef("SENT", "SENT", "Отправлено", True),
            ),
        ),
        RouteTemplate(
            name="Типовой: П/ф с прессом",
            description="WH → PRESS → SHOT → ANOD → FG_WH → SHIPMENT → SENT",
            steps=(
                StepDef("WH", "ISSUE_RAW", "Выдача сырья"),
                StepDef("PRESS", "PRESS", "Пресс"),
                StepDef("SHOT", "SHOT", "Дробеструй"),
                StepDef("ANOD", "ANOD", "Анодирование"),
                StepDef("FG_WH", "ACCEPT_FINISHED", "Приемка готовой продукции"),
                StepDef("SHIPMENT", "SHIPMENT", "К отгрузке"),
                StepDef("SENT", "SENT", "Отправлено", True),
            ),
        ),
        RouteTemplate(
            name="Типовой: П/ф базовый",
            description="WH → SHOT → ANOD → FG_WH → SHIPMENT → SENT",
            steps=(
                StepDef("WH", "ISSUE_RAW", "Выдача сырья"),
                StepDef("SHOT", "SHOT", "Дробеструй"),
                StepDef("ANOD", "ANOD", "Анодирование"),
                StepDef("FG_WH", "ACCEPT_FINISHED", "Приемка готовой продукции"),
                StepDef("SHIPMENT", "SHIPMENT", "К отгрузке"),
                StepDef("SENT", "SENT", "Отправлено", True),
            ),
        ),
    )


def _rules() -> tuple[RuleDef, ...]:
    return (
        RuleDef(RouteOperationFamily.DRILL, RouteOutputKind.finished_good, False, "Типовой: ГП со сверлом", 100),
        RuleDef(RouteOperationFamily.DRILL, RouteOutputKind.finished_good, True, "Типовой: ГП со сверлом", 100),
        RuleDef(RouteOperationFamily.PRESS, RouteOutputKind.finished_good, False, "Типовой: ГП с прессом", 100),
        RuleDef(RouteOperationFamily.PRESS, RouteOutputKind.finished_good, True, "Типовой: ГП с прессом", 100),
        RuleDef(RouteOperationFamily.NONE, RouteOutputKind.finished_good, False, "Типовой: ГП базовый", 90),
        RuleDef(RouteOperationFamily.NONE, RouteOutputKind.finished_good, True, "Типовой: ГП базовый", 90),
        RuleDef(RouteOperationFamily.PACK, RouteOutputKind.finished_good, False, "Типовой: ГП базовый", 90),
        RuleDef(RouteOperationFamily.PACK, RouteOutputKind.finished_good, True, "Типовой: ГП базовый", 90),
        RuleDef(RouteOperationFamily.DRILL, RouteOutputKind.semi_finished_shipment, None, "Типовой: П/ф со сверлом", 100),
        RuleDef(RouteOperationFamily.PRESS, RouteOutputKind.semi_finished_shipment, False, "Типовой: П/ф с прессом", 100),
        RuleDef(RouteOperationFamily.PRESS, RouteOutputKind.semi_finished_shipment, True, "Типовой: П/ф с прессом", 100),
        RuleDef(RouteOperationFamily.NONE, RouteOutputKind.semi_finished_shipment, None, "Типовой: П/ф базовый", 90),
        RuleDef(RouteOperationFamily.PACK, RouteOutputKind.semi_finished_shipment, None, "Типовой: П/ф базовый", 90),
    )


async def _ensure_route(
    session,
    section_map: dict[str, Section],
    template: RouteTemplate,
) -> ProductionRoute:
    route = await session.scalar(select(ProductionRoute).where(ProductionRoute.name == template.name))
    if route is None:
        route = ProductionRoute(name=template.name, description=template.description, is_active=True)
        session.add(route)
        await session.flush()
    else:
        route.description = template.description
        route.is_active = True
        existing = (await session.execute(select(RouteStep).where(RouteStep.route_id == route.id))).scalars().all()
        for step in existing:
            await session.delete(step)
        await session.flush()

    for index, step in enumerate(template.steps, start=1):
        section = section_map.get(step.section_code)
        if section is None:
            raise RuntimeError(f"Section '{step.section_code}' is missing")
        session.add(
            RouteStep(
                route_id=route.id,
                sequence=index,
                section_id=section.id,
                operation_code=step.operation_code,
                operation_name=step.operation_name,
                is_final=step.is_final,
                requires_acceptance=True,
                allow_parallel=False,
            )
        )
    await session.flush()
    return route


async def seed() -> None:
    async with async_session() as session:
        sections = (await session.execute(select(Section).where(Section.is_active.is_(True)))).scalars().all()
        section_map = {s.code: s for s in sections}

        for template in _templates():
            await _ensure_route(session, section_map, template)

        route_by_name = {
            route.name: route
            for route in (await session.execute(select(ProductionRoute).where(ProductionRoute.is_active.is_(True)))).scalars().all()
        }

        await session.execute(delete(RouteSignatureRule))
        for rule in _rules():
            route = route_by_name.get(rule.route_name)
            if route is None:
                raise RuntimeError(f"Route '{rule.route_name}' is missing")
            session.add(
                RouteSignatureRule(
                    route_id=route.id,
                    operation_family=rule.operation_family,
                    output_kind=rule.output_kind,
                    has_pack_ops=rule.has_pack_ops,
                    priority=rule.priority,
                    is_active=True,
                )
            )

        await session.commit()
        print("Seed complete")
        print(f"Created/updated routes: {len(_templates())}")
        print(f"Inserted route_signature_rules: {len(_rules())}")


if __name__ == "__main__":
    asyncio.run(seed())
