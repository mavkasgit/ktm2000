"""Синхронизация WorkTask.status с проекцией StockTransaction ledger."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.work_task import WorkTask, WorkTaskStatus
from app.stock.task_cache import resolve_work_task_status


def _status_from_cache(task: WorkTask, cache: dict) -> str | None:
    return resolve_work_task_status(
        current_status=task.status.value,
        planned_quantity=task.planned_quantity,
        remaining_quantity=cache.get("remaining_quantity", Decimal("0")),
        transferred_quantity=cache.get("transferred_quantity", Decimal("0")),
        completed_quantity=cache.get("completed_quantity", Decimal("0")),
        rejected_quantity=cache.get("rejected_quantity", Decimal("0")),
        issued_quantity=cache.get("issued_quantity", Decimal("0")),
        received_quantity=cache.get("received_quantity", Decimal("0")),
    )


async def sync_work_task_status(
    db: AsyncSession,
    task: WorkTask,
    *,
    cache: dict | None = None,
) -> bool:
    """Обновить status задачи по ledger, если он отстаёт от фактов."""
    if cache is None:
        from app.stock.services import StockProjectionManager

        cache = await StockProjectionManager().get_task_cache(db, task.id)

    new_status = _status_from_cache(task, cache)
    if new_status is None or new_status == task.status.value:
        return False

    task.status = WorkTaskStatus(new_status)
    return True


async def sync_work_tasks_status_bulk(
    db: AsyncSession,
    *,
    tasks: list[WorkTask],
    tasks_cache: dict[int, dict],
) -> int:
    """Пакетная синхронизация статусов; возвращает число обновлённых задач."""
    updated = 0
    for task in tasks:
        cache = tasks_cache.get(task.id)
        if cache is None:
            continue
        if await sync_work_task_status(db, task, cache=cache):
            updated += 1
    if updated:
        await db.flush()
    return updated