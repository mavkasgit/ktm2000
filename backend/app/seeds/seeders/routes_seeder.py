from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import Defect
from app.models.internal_plan import SectionPlanLine
from app.models.movement import Movement
from app.models.rework_task import ReworkTask
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
from app.models.transfer import Transfer
from app.models.work_task import WorkTask

# Operations that affect plan grouping (technological)
SIGNIFICANT_OPS = {
    "DRILL", "SHOT", "PRESS_WINDOW", "PRESS_COMB", "SAW", "PACK",
    "PACK_SPUNBOND", "PACK_STRETCH", "COAT", "WELD", "BEND", "CUT", "POLISH",
}


def _is_significant(operation_code: str | None) -> bool:
    return operation_code in SIGNIFICANT_OPS if operation_code else False


async def seed_routes(
    db: AsyncSession,
    routes_data: list[dict],
    force: bool = False,
) -> dict[str, ProductionRoute]:
    """Upsert all routes by code. Replace steps entirely. Returns {code: route} map."""
    # Load sections
    sections_result = await db.execute(select(Section).where(Section.is_active.is_(True)))
    sections = list(sections_result.scalars().all())
    sections_by_code = {s.code: s for s in sections}

    required_codes = sorted({
        step["section_code"]
        for template in routes_data
        for step in template["steps"]
    })
    missing = [c for c in required_codes if c not in sections_by_code]
    if missing:
        raise RuntimeError(f"Missing sections for routes: {', '.join(missing)}")

    result: dict[str, ProductionRoute] = {}

    for template in routes_data:
        # Upsert by code, fallback to name for legacy
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
        else:
            route.code = template["code"]
            route.name = template["name"]
            route.description = template["description"]
            route.is_active = True
            route.sort_order = template["sort_order"]

        # Replace all steps — clear all dependent data in correct FK order
        existing = (await db.execute(select(RouteStep).where(RouteStep.route_id == route.id))).scalars().all()
        if existing:
            step_ids = [s.id for s in existing]
            # Find section_plan_lines referencing these steps
            spl_rows = (await db.execute(
                select(SectionPlanLine.id).where(SectionPlanLine.route_step_id.in_(step_ids))
            )).scalars().all()
            if spl_rows:
                spl_ids = list(spl_rows)
                # Find work_tasks that reference these section_plan_lines
                task_ids = (await db.execute(
                    select(WorkTask.id).where(WorkTask.section_plan_line_id.in_(spl_ids))
                )).scalars().all()

                if task_ids and not force:
                    raise RuntimeError(
                        f"Route '{template['code']}' has dependent data ({len(task_ids)} tasks with transfers/movements). "
                        "Use force=true to replace routes and cascade-delete dependent data."
                    )

                if task_ids and force:
                    # Delete in FK dependency order before deleting work_tasks.
                    # movements references both work_tasks AND transfers, so delete it first.
                    await db.execute(
                        Movement.__table__.delete().where(
                            Movement.task_id.in_(task_ids)
                        )
                    )
                    # Delete transfer-related data
                    await db.execute(
                        Transfer.__table__.delete().where(
                            Transfer.from_task_id.in_(task_ids) | Transfer.to_task_id.in_(task_ids)
                        )
                    )
                    await db.execute(
                        Defect.__table__.delete().where(
                            Defect.task_id.in_(task_ids)
                        )
                    )
                    await db.execute(
                        ReworkTask.__table__.delete().where(
                            ReworkTask.source_task_id.in_(task_ids)
                        )
                    )

                # Delete work_tasks referencing those section_plan_lines
                await db.execute(
                    WorkTask.__table__.delete().where(
                        WorkTask.section_plan_line_id.in_(spl_ids)
                    )
                )
                # Delete section_plan_lines
                await db.execute(
                    SectionPlanLine.__table__.delete().where(
                        SectionPlanLine.route_step_id.in_(step_ids)
                    )
                )
        for step in existing:
            await db.delete(step)
        await db.flush()

        for idx, step_def in enumerate(template["steps"], start=1):
            section = sections_by_code[step_def["section_code"]]
            cog = step_def.get("combined_op_group")
            # Use explicit is_significant if provided, otherwise auto-detect from operation_code
            step_is_sig = step_def.get("is_significant")
            if step_is_sig is None:
                step_is_sig = _is_significant(step_def["operation_code"])
            # Steps in a combined group (cog) are always significant
            if cog:
                step_is_sig = True
            db.add(
                RouteStep(
                    route_id=route.id,
                    sequence=idx,
                    section_id=section.id,
                    operation_code=step_def["operation_code"],
                    operation_name=step_def["operation_name"],
                    is_significant=step_is_sig,
                    is_final=bool(step_def.get("is_final", False)),
                    requires_acceptance=True,
                    allow_parallel=False,
                    combined_op_group=cog,
                )
            )

        await db.flush()

        result[template["code"]] = route

    return result
