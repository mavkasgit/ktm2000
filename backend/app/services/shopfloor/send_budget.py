"""Бюджет отправки (final release) по (задача, размер) — тикет #128.

Единственный владелец **чтения** «сколько можно отправить» с финального
участка. Раньше write-guard в ``operations_tasks.final_release`` считал
``releasable`` инлайн (сырое вычитание без clamp) — второй владелец формулы
после ``app.transfers.budget``; теперь guard и любые будущие потребители
замыкаются на этот модуль:

- ``released`` — canonical net FINAL_RELEASE через ledger-примитив
  ``app.stock.ledger.net_by_reason`` (ADR-0018), а не локальная gross-сумма;
- ``produced`` — «произведено по размеру» (CONTEXT.md), два adapter'а:
  трансформирующее задание — ``get_transform_progress().produced_by_group``
  (уже закаплено ``min(output_quantity, produced_by_group)``), обычное —
  gross SUM ``Reason.COMPLETE`` по (задача, размер);
- кламп в ноль и сама формула — чистый ярус
  ``app.transfers.budget.remaining_send`` (тикет #106).

Кэш StockProjectionManager — вне среза (третий adapter позже).
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.work_task import WorkTask
from app.stock import Reason
from app.stock.ledger import net_by_reason
from app.stock.models import StockTransaction
from app.stock.services import _dimensions_hash_key, dimensions_match_clause
from app.transfers import budget as transfer_budget

from .common import _get_route_stage
from .operations_transform import get_transform_progress, resolve_transform_spec


async def remaining_send(
    db: AsyncSession, *, task: WorkTask, dims: dict | None
) -> Decimal:
    """Бюджет отправки по (задача, размер): ``max(0, produced − released)``.

    ``dims`` — канонический габарит выпуска (для трансформирующего этапа
    вызывающий валидирует его против выходов спецификации, см.
    ``operations_tasks.final_release``). ``released`` — net FINAL_RELEASE по
    (задача, размер); ``produced`` — фактически произведённое по размеру:
    для трансформации — прогресс выходов (закаплен на уровне
    ``build_outputs_progress``), для обычного задания (габарит по умолчанию —
    ``task.dimensions``) — gross COMPLETE.
    """
    stage = await _get_route_stage(db, task.route_stage_id)
    spec = resolve_transform_spec(task, stage)

    eff_dims = dims
    if spec is not None:
        # Оприходовано выхода этого размера (COMPLETE по (задача, размер)).
        progress = await get_transform_progress(db, task.id)
        produced = progress.produced_by_group.get(
            _dimensions_hash_key(eff_dims)
        ) or Decimal("0")
    else:
        eff_dims = eff_dims if eff_dims is not None else task.dimensions
        produced = (
            await db.scalar(
                select(func.coalesce(func.sum(StockTransaction.quantity), 0))
                .where(
                    StockTransaction.task_id == task.id,
                    StockTransaction.reason == Reason.COMPLETE,
                    dimensions_match_clause(StockTransaction.dimensions, eff_dims),
                )
            )
        ) or Decimal("0")

    # «Уже выпущено» — canonical net FINAL_RELEASE через ledger-примитив
    # (ADR-0018), а не локальная gross-сумма.
    released = await net_by_reason(
        db, reason=Reason.FINAL_RELEASE, task_id=task.id, dims=eff_dims
    )
    return transfer_budget.remaining_send(produced, released)
