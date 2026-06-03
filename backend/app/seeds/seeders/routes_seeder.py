from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import Defect
from app.models.internal_plan import SectionPlanLine
from app.models.movement import Movement
from app.models.rework_task import ReworkTask
from app.models.route import ProductionRoute, RouteRuleProfile, RouteStage, RouteOperation, SectionOperation
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
    """Upsert all routes by code. Replace stages entirely. Returns {code: route} map.

    Note: Old static routes are replaced by dynamic route building.
    If routes_data is empty, return empty dict without errors.
    """
    if not routes_data:
        return {}

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

        # Replace all stages — clear all dependent data in correct FK order
        existing = (await db.execute(select(RouteStage).where(RouteStage.route_id == route.id))).scalars().all()
        if existing:
            stage_ids = [s.id for s in existing]
            # Find section_plan_lines referencing these stages
            spl_rows = (await db.execute(
                select(SectionPlanLine.id).where(SectionPlanLine.route_stage_id.in_(stage_ids))
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
                        SectionPlanLine.route_stage_id.in_(stage_ids)
                    )
                )
        for stage in existing:
            await db.delete(stage)
        await db.flush()

        # Group steps by section_code and combined_op_group
        groups = []
        current = []
        current_cog = None
        current_section_id = None

        for idx, step_def in enumerate(template["steps"], start=1):
            section = sections_by_code[step_def["section_code"]]
            cog = step_def.get("combined_op_group")
            step_is_sig = step_def.get("is_significant")
            if step_is_sig is None:
                step_is_sig = _is_significant(step_def["operation_code"])
            if cog:
                step_is_sig = True

            same_group = (
                cog is not None
                and cog == current_cog
                and section.id == current_section_id
            )

            step_info = (step_def, section, step_is_sig)
            if same_group:
                current.append(step_info)
            else:
                if current:
                    groups.append(current)
                current = [step_info]
                current_cog = cog
                current_section_id = section.id
        if current:
            groups.append(current)

        stage_seq = 1
        for group in groups:
            primary_step_def, primary_section, primary_is_sig = group[0]
            stage = RouteStage(
                route_id=route.id,
                sequence=stage_seq,
                section_id=primary_section.id,
                is_significant=primary_is_sig,
                norm_time_minutes=primary_step_def.get("norm_time_minutes"),
                requires_acceptance=True,
                allow_parallel=False,
                is_final=any(bool(s[0].get("is_final", False)) for s in group),
            )
            db.add(stage)
            await db.flush()

            for op_idx, (step_def, _, _) in enumerate(group, start=1):
                op = RouteOperation(
                    route_stage_id=stage.id,
                    sequence=op_idx,
                    operation_code=step_def["operation_code"],
                    operation_name=step_def["operation_name"],
                )
                db.add(op)
            
            stage_seq += 1

        await db.flush()
        result[template["code"]] = route

    return result


async def seed_production_routes_from_profiles(db: AsyncSession) -> int:
    """Create ProductionRoute for each RouteRuleProfile that has route_sections.

    This ensures the frontend sees routes after seeding.
    Each section gets ONE RouteStep (operation_code=None) - operations resolved at runtime.
    """
    profiles = (await db.execute(
        select(RouteRuleProfile).where(RouteRuleProfile.is_active.is_(True))
    )).scalars().all()

    sections = (await db.execute(
        select(Section).where(Section.is_active.is_(True))
    )).scalars().all()
    sections_by_code = {s.code: s for s in sections}

    created_count = 0

    for profile in profiles:
        route_section_codes = profile.route_sections or []
        if not route_section_codes:
            continue

        route_name = f"Dynamic: {profile.name}"
        route_code = f"dynamic_{profile.code}"

        # Check if route already exists
        route = await db.scalar(
            select(ProductionRoute).where(
                (ProductionRoute.code == route_code) | (ProductionRoute.name == route_name)
            )
        )

        if route is None:
            route = ProductionRoute(
                code=route_code,
                name=route_name,
                description=f"Автоматический маршрут из профиля '{profile.name}'",
                is_active=True,
                sort_order=profile.priority,
            )
            db.add(route)
            await db.flush()

        # Clear existing stages
        existing_stages = (await db.execute(
            select(RouteStage).where(RouteStage.route_id == route.id)
        )).scalars().all()
        for stage in existing_stages:
            await db.delete(stage)
        await db.flush()

        # Build ONE stage per section (operations resolved at runtime)
        sequence = 0
        for section_code in route_section_codes:
            section = sections_by_code.get(section_code)
            if not section:
                continue

            sequence += 1
            stage = RouteStage(
                route_id=route.id,
                sequence=sequence,
                section_id=section.id,
                is_significant=True,
                is_final=(section_code == "SENT"),
                requires_acceptance=True,
                allow_parallel=False,
            )
            db.add(stage)
            await db.flush()

            op = RouteOperation(
                route_stage_id=stage.id,
                sequence=1,
                operation_code=None,  # Resolved dynamically at import time
                operation_name=section.name,
            )
            db.add(op)

        created_count += 1

    await db.flush()
    return created_count
