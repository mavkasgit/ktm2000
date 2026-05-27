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
from app.models.route import RouteStep
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
) -> dict[str, dict]:
    """
    Для всех combined групп в пределах plan_position_id вернуть информацию.
    Returns: {combined_op_group: {"primary_line_id": ..., "secondary_line_ids": [...], "operation_names": [...]}}
    """
    lines_steps = (await db.execute(
        select(SectionPlanLine, RouteStep)
        .join(RouteStep, SectionPlanLine.route_step_id == RouteStep.id)
        .where(
            SectionPlanLine.plan_position_id == plan_position_id,
            RouteStep.combined_op_group.isnot(None),
        )
        .order_by(SectionPlanLine.sequence)
    )).all()

    if not lines_steps:
        return {}

    groups: dict[str, dict] = {}
    for spl_line, route_step in lines_steps:
        cog = route_step.combined_op_group
        if cog not in groups:
            groups[cog] = {
                "primary_line_id": spl_line.id,
                "secondary_line_ids": [],
                "operation_names": [],
            }
        else:
            groups[cog]["secondary_line_ids"].append(spl_line.id)
        groups[cog]["operation_names"].append(route_step.operation_name)

    return groups
