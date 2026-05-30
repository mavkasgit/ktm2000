"""
operations_combined.py
======================
Сервис для работы с комбинированными операциями на участке.

Когда несколько шагов маршрута имеют одинаковый combined_op_group,
они выполняются как единая операция через первичную задачу (первую по sequence).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_plan import SectionPlanLine
from app.models.route import RouteStep, SectionOperation
from app.models.section import Section
from app.models.work_task import WorkTask, WorkTaskStatus


@dataclass
class CombinedGroup:
    primary_task: WorkTask
    secondary_tasks: list[WorkTask] = field(default_factory=list)
    all_tasks: list[WorkTask] = field(default_factory=list)
    combined_op_group: str = ""
    operation_names: list[str] = field(default_factory=list)


async def resolve_combined_group(db: AsyncSession, task_id: int) -> CombinedGroup | None:
    """
    Если задача входит в combined группу, вернуть CombinedGroup.
    Если нет — вернуть None.

    Raises ValueError если задача secondary (операции только через primary).
    """
    task = await db.get(WorkTask, task_id)
    if task is None:
        raise ValueError("Task not found")

    line = await db.get(SectionPlanLine, task.section_plan_line_id)
    if line is None:
        return None

    step = await db.get(RouteStep, line.route_step_id)
    if step is None or not step.combined_op_group:
        return None

    combined_op_group = step.combined_op_group

    # Find all section plan lines for this plan position with same combined_op_group
    all_lines = (await db.execute(
        select(SectionPlanLine, RouteStep)
        .join(RouteStep, SectionPlanLine.route_step_id == RouteStep.id)
        .where(
            SectionPlanLine.plan_position_id == line.plan_position_id,
            RouteStep.combined_op_group == combined_op_group,
        )
        .order_by(SectionPlanLine.sequence)
    )).all()

    if len(all_lines) <= 1:
        return None

    # Find all work tasks for these lines
    line_ids = [spl_line.id for spl_line, _ in all_lines]
    all_tasks = (await db.execute(
        select(WorkTask)
        .where(
            WorkTask.section_plan_line_id.in_(line_ids),
            WorkTask.status.notin_([WorkTaskStatus.completed, WorkTaskStatus.cancelled]),
        )
        .order_by(WorkTask.id)
    )).scalars().all()

    if not all_tasks:
        return None

    # Primary = task with lowest sequence
    primary_task = None
    secondary_tasks = []
    operation_names = []

    for spl_line, route_step in all_lines:
        # Find matching task
        matching_task = next((t for t in all_tasks if t.section_plan_line_id == spl_line.id), None)
        if matching_task:
            operation_names.append(route_step.operation_name)
            if primary_task is None:
                primary_task = matching_task
            else:
                secondary_tasks.append(matching_task)

    if primary_task is None:
        return None

    # Check that current task is primary
    if task.id != primary_task.id:
        raise ValueError(
            f"Combined operation must be executed via primary task (id={primary_task.id}). "
            f"Current task (id={task.id}) is a secondary task in group '{combined_op_group}'."
        )

    return CombinedGroup(
        primary_task=primary_task,
        secondary_tasks=secondary_tasks,
        all_tasks=[primary_task] + secondary_tasks,
        combined_op_group=combined_op_group,
        operation_names=operation_names,
    )


async def get_combined_info_for_board(
    db: AsyncSession,
    plan_position_id: int,
    source_payload: dict | None = None,
) -> dict[str, dict]:
    """
    Для всех combined групп в пределах plan_position_id вернуть информацию.
    Returns: {combined_op_group: {"primary_line_id": ..., "secondary_line_ids": [...], "operation_names": [...], "operation_codes": [...]}}
    """
    from app.services.route_resolution import resolve_operation

    # Get route_id from any SectionPlanLine for this position
    first_line = await db.scalar(
        select(SectionPlanLine.route_step_id)
        .where(SectionPlanLine.plan_position_id == plan_position_id)
        .limit(1)
    )
    if not first_line:
        return {}

    # Get route_id from the route_step
    first_step = await db.get(RouteStep, first_line)
    if not first_step:
        return {}
    route_id = first_step.route_id

    # Get ALL RouteSteps for this route that have combined_op_group
    # (not filtered by SectionPlanLine, since secondary steps don't have lines)
    route_steps = (await db.execute(
        select(RouteStep)
        .where(
            RouteStep.route_id == route_id,
            RouteStep.combined_op_group.isnot(None),
        )
        .order_by(RouteStep.sequence)
    )).scalars().all()

    if not route_steps:
        return {}

    # Collect unique section_ids
    section_ids = {step.section_id for step in route_steps}
    section_by_id = {}
    if section_ids:
        sections = (await db.execute(
            select(Section).where(Section.id.in_(section_ids))
        )).scalars().all()
        section_by_id = {s.id: s for s in sections}

    # Build operation name lookup
    op_name_map: dict[tuple[int, str], str] = {}
    if section_ids:
        ops = (await db.execute(
            select(SectionOperation).where(SectionOperation.section_id.in_(section_ids))
        )).scalars().all()
        for op in ops:
            op_name_map[(op.section_id, op.operation_code)] = op.operation_name

    # Build SectionPlanLine lookup: route_step_id -> line_id
    line_ids_by_step = {}
    lines = (await db.execute(
        select(SectionPlanLine.route_step_id, SectionPlanLine.id)
        .where(SectionPlanLine.plan_position_id == plan_position_id)
    )).all()
    for step_id, line_id in lines:
        line_ids_by_step[step_id] = line_id

    # Group by combined_op_group
    groups: dict[str, dict] = {}
    for route_step in route_steps:
        cog = route_step.combined_op_group
        section = section_by_id.get(route_step.section_id)
        section_code = section.code if section else ""

        # Resolve operation code
        resolved_code = route_step.operation_code
        if resolved_code is None and source_payload:
            resolved_code = resolve_operation(section_code, source_payload)

        # Resolve operation name
        resolved_name = route_step.operation_name
        if resolved_code is not None:
            resolved_name = op_name_map.get((route_step.section_id, resolved_code), route_step.operation_name)

        line_id = line_ids_by_step.get(route_step.id)

        if cog not in groups:
            groups[cog] = {
                "primary_line_id": line_id,
                "secondary_line_ids": [],
                "operation_names": [],
                "operation_codes": [],
            }
        else:
            if line_id:
                groups[cog]["secondary_line_ids"].append(line_id)
        groups[cog]["operation_names"].append(resolved_name)
        groups[cog]["operation_codes"].append(resolved_code)

    return groups
