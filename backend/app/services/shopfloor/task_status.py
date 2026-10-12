"""Синхронизация WorkTask.status с проекцией StockTransaction ledger."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.shopfloor.operations_transform import TransformProgress
from app.stock.task_cache import resolve_work_task_status


def _status_from_cache(
    task: WorkTask,
    cache: dict,
    *,
    transform_input_quantity: Decimal | None = None,
    transform_processed_quantity: Decimal | None = None,
) -> str | None:
    return resolve_work_task_status(
        current_status=task.status.value,
        planned_quantity=task.planned_quantity,
        remaining_quantity=cache.get("remaining_quantity", Decimal(0)),
        transferred_quantity=cache.get("transferred_quantity", Decimal(0)),
        completed_quantity=cache.get("completed_quantity", Decimal(0)),
        rejected_quantity=cache.get("rejected_quantity", Decimal(0)),
        issued_quantity=cache.get("issued_quantity", Decimal(0)),
        received_quantity=cache.get("received_quantity", Decimal(0)),
        transform_input_quantity=transform_input_quantity,
        transform_processed_quantity=transform_processed_quantity,
    )


async def sync_work_task_status(
    db: AsyncSession,
    task: WorkTask,
    *,
    cache: dict | None = None,
    transform_progress: TransformProgress | None = None,
) -> bool:
    """Обновить status задачи по ledger, если он отстаёт от фактов.

    ``transform_progress`` — готовый снимок по этому заданию из батча
    (``get_transform_progress_bulk``). Без него трансформирующее задание
    стоит отдельного запроса на задание: на доске это был N+1 (тикет #293).
    """
    if cache is None:
        from app.stock.services import StockProjectionManager

        cache = await StockProjectionManager().get_task_cache(db, task.id)

    transform_input_quantity = None
    transform_processed_quantity = None
    if task.input_quantity is not None and task.outputs:
        from app.services.shopfloor.operations_transform import get_transform_progress

        progress = transform_progress or await get_transform_progress(db, task.id)
        transform_input_quantity = Decimal(str(task.input_quantity))
        transform_processed_quantity = progress.consumed_quantity + progress.scrapped_quantity

    new_status = _status_from_cache(
        task,
        cache,
        transform_input_quantity=transform_input_quantity,
        transform_processed_quantity=transform_processed_quantity,
    )
    if new_status is None or new_status == task.status.value:
        return False

    task.status = WorkTaskStatus(new_status)
    return True