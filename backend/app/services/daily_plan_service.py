from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.daily_plan import DailyPlan, DailyPlanItem
from app.models.internal_plan import SectionPlanLine
from app.models.product import Product
from app.models.route import RouteStage
from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.audit_log_service import log_action
from app.models.audit_log import AuditAction, AuditEntityType
from app.stock.services import StockProjectionManager

TERMINAL_TASK_STATUSES = {WorkTaskStatus.completed, WorkTaskStatus.cancelled}


class DailyPlanConflict(Exception):
    """A task is already in another (or this) daily plan."""


class DailyPlanNotFound(Exception):
    """The daily plan or requested membership does not exist."""


async def _task_progress(db: AsyncSession, tasks: list[WorkTask]) -> dict[int, int]:
    if not tasks:
        return {}
    cache = await StockProjectionManager().get_tasks_cache_bulk(db, [task.id for task in tasks])
    result: dict[int, int] = {}
    for task in tasks:
        planned = Decimal(task.planned_quantity or 0)
        completed = Decimal(cache.get(task.id, {}).get("completed_quantity", 0))
        if planned <= 0:
            result[task.id] = 0
        else:
            result[task.id] = max(0, min(100, int(completed / planned * 100)))
    return result


def _task_dict(task: WorkTask, line: SectionPlanLine, stage: RouteStage, product_sku: str, progress: int) -> dict[str, Any]:
    operation = task.selected_operation_code
    operation_name = next(
        (op.operation_name for op in stage.operations if op.operation_code == operation),
        stage.operations[0].operation_name if stage.operations else None,
    )
    return {
        "id": task.id,
        "section_id": task.section_id,
        "product_id": task.product_id,
        "product_sku": product_sku,
        "section_plan_line_id": line.id,
        "plan_position_id": line.plan_position_id,
        "route_step_id": stage.id,
        "sequence": stage.sequence,
        "operation_code": operation or (stage.operations[0].operation_code if stage.operations else None),
        "operation_name": operation_name,
        "planned_quantity": str(task.planned_quantity),
        "status": task.status.value,
        "dimensions": task.dimensions,
        "input_quantity": str(task.input_quantity) if task.input_quantity is not None else None,
        "input_dimensions": task.input_dimensions,
        "outputs": task.outputs or [],
        "progress_percent": progress,
    }


async def _composition(db: AsyncSession, plan: DailyPlan) -> list[dict[str, Any]]:
    task_ids = (await db.execute(
        select(DailyPlanItem.work_task_id)
        .where(DailyPlanItem.daily_plan_id == plan.id)
        .order_by(DailyPlanItem.work_task_id)
    )).scalars().all()
    if not task_ids:
        return []

    from app.services.shopfloor.queries_sections import get_section_board

    board = await get_section_board(
        db,
        section_id=plan.section_id,
        limit=500,
        offset=0,
    )
    tasks_by_id = {task["id"]: task for task in board["tasks"]}
    items: list[dict[str, Any]] = []
    for task_id in task_ids:
        task = tasks_by_id.get(task_id)
        if task is None:
            continue
        planned = Decimal(task.get("planned_quantity", 0))
        completed = Decimal(task.get("cache", {}).get("completed_quantity", 0))
        progress = 0 if planned <= 0 else max(0, min(100, int(completed / planned * 100)))
        items.append({
            "id": f"{plan.id}:{task_id}",
            "daily_plan_id": plan.id,
            "work_task_id": task_id,
            "task": task,
            "progress_percent": progress,
        })
    return items


async def list_candidates(db: AsyncSession, section_id: int) -> list[dict[str, Any]]:
    from app.services.shopfloor.queries_sections import get_section_board

    board = await get_section_board(
        db,
        section_id=section_id,
        limit=500,
        offset=0,
    )
    candidate_ids = set((await db.execute(
        select(WorkTask.id)
        .where(
            WorkTask.section_id == section_id,
            WorkTask.status.notin_(TERMINAL_TASK_STATUSES),
            ~exists(
                select(DailyPlanItem.work_task_id).where(
                    DailyPlanItem.work_task_id == WorkTask.id
                )
            ),
        )
    )).scalars().all())
    return [task for task in board["tasks"] if task["id"] in candidate_ids]


async def list_plans_for_section(db: AsyncSession, section_id: int) -> list[dict[str, Any]]:
    plans = (await db.execute(
        select(DailyPlan).where(DailyPlan.section_id == section_id).order_by(DailyPlan.plan_date.desc(), DailyPlan.created_at.desc())
    )).scalars().all()
    if not plans:
        return []
    rows = (await db.execute(
        select(DailyPlanItem.daily_plan_id, DailyPlanItem.work_task_id, WorkTask)
        .join(DailyPlan, DailyPlanItem.daily_plan_id == DailyPlan.id)
        .join(WorkTask, DailyPlanItem.work_task_id == WorkTask.id)
        .where(DailyPlan.section_id == section_id)
    )).all()
    by_plan: dict[int, list[WorkTask]] = {}
    for plan_id, _, task in rows:
        by_plan.setdefault(plan_id, []).append(task)
    progress: dict[int, int] = {}
    for tasks in by_plan.values():
        progress.update(await _task_progress(db, tasks))
    return [
        {
            "id": plan.id,
            "section_id": plan.section_id,
            "plan_date": plan.plan_date,
            "created_at": plan.created_at,
            "created_by": plan.created_by,
            "item_count": len(by_plan.get(plan.id, [])),
            "progress_percent": round(sum(progress.get(task.id, 0) for task in by_plan.get(plan.id, [])) / len(by_plan[plan.id])) if by_plan.get(plan.id) else 0,
        }
        for plan in plans
    ]


async def create_plan(db: AsyncSession, *, plan_date: date, work_task_ids: list[int], created_by: int) -> dict[str, Any]:
    task_ids = list(dict.fromkeys(work_task_ids))
    if not task_ids:
        raise ValueError("work_task_ids must not be empty")
    tasks = (await db.execute(select(WorkTask).where(WorkTask.id.in_(task_ids)))).scalars().all()
    if len(tasks) != len(task_ids):
        raise ValueError("one or more work tasks do not exist")
    section_ids = {task.section_id for task in tasks}
    if len(section_ids) != 1:
        raise ValueError("all work tasks must belong to one section")
    if any(task.status in TERMINAL_TASK_STATUSES for task in tasks):
        raise ValueError("terminal work tasks cannot be added")
    existing = (await db.execute(select(DailyPlanItem.work_task_id).where(DailyPlanItem.work_task_id.in_(task_ids)))).scalars().all()
    if existing:
        raise DailyPlanConflict("one or more work tasks already belong to a daily plan")
    plan = DailyPlan(section_id=next(iter(section_ids)), plan_date=plan_date, created_by=created_by)
    db.add(plan)
    await db.flush()
    for task_id in task_ids:
        db.add(DailyPlanItem(daily_plan_id=plan.id, work_task_id=task_id))
    await db.flush()
    progress = await _task_progress(db, tasks)
    return {
        "id": plan.id,
        "section_id": plan.section_id,
        "plan_date": plan.plan_date,
        "created_at": plan.created_at,
        "created_by": plan.created_by,
        "item_count": len(tasks),
        "progress_percent": round(sum(progress.values()) / len(tasks)) if tasks else 0,
    }


async def list_items(db: AsyncSession, plan_id: int) -> list[dict[str, Any]]:
    plan = await db.get(DailyPlan, plan_id)
    if plan is None:
        raise DailyPlanNotFound("daily plan not found")
    return await _composition(db, plan)


async def revoke_item(db: AsyncSession, *, plan_id: int, work_task_id: int, user: Any) -> dict[str, int]:
    plan = await db.get(DailyPlan, plan_id)
    task = await db.get(WorkTask, work_task_id)
    item = await db.scalar(select(DailyPlanItem).where(DailyPlanItem.daily_plan_id == plan_id, DailyPlanItem.work_task_id == work_task_id))
    if plan is None or item is None:
        raise DailyPlanNotFound("daily plan item not found")
    if task is not None and task.status in TERMINAL_TASK_STATUSES:
        raise ValueError("completed or cancelled work tasks cannot be revoked from a daily plan")
    await db.delete(item)
    await log_action(
        db, status="success", title="Задание исключено из дневного плана",
        message=f"Задание #{work_task_id} исключено из дневного плана #{plan_id}",
        user=user, section_id=plan.section_id, task_ids=[work_task_id],
        action=AuditAction.DELETE, entity_type=AuditEntityType.DAILY_PLAN, entity_id=plan_id,
        changes={"before": {"daily_plan_id": plan_id, "work_task_id": work_task_id}, "after": {}},
    )
    return {"plan_id": plan_id, "work_task_id": work_task_id}
