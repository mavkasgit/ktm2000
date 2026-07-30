"""Завершение задания на трансформирующем этапе (ADR-0002, тикет #8).

Порция факта атомарно двигает ledger в одной транзакции БД:

- списание входа: ``good`` шт × входной габарит (``Reason.TRANSFORM_CONSUME``);
- приход ВСЕХ выходов спецификации пропорционально доле входа
  (``Reason.COMPLETE`` с габаритом выхода) — годный остаток приходуется
  автоматически как обычный выход, понятия «отход» нет, пропил игнорируется;
- брак заготовок пишет вызывающий код (``SCRAP`` с габаритом входа).

Ядро factory-agnostic: трансформация определяется маркером
``RouteStage.transforms_dimensions`` и спецификацией задания
(``input_quantity``/``input_dimensions``/``outputs``), никогда — кодом секции.

Пропорция считается по кумулятивной цели: ``target_i = total_i ×
consumed_after / input_quantity`` (квантование 0.001), порция —
разница с уже оприходованным. Суммы сходятся точно к спецификации
без накопления хвостов округления.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dimensions import canonicalize_dimensions
from app.models.route import RouteStage
from app.models.work_task import WorkTask
from app.stock import QualityState, Reason, StockCommand, StockCommandService
from app.stock.models import StockBalance, StockTransaction
from app.stock.services import _dimensions_hash_key, dimensions_match_clause

# Шаг квантования количеств — совпадает с Numeric(14, 3) в моделях.
_QTY_STEP = Decimal("0.001")


@dataclass(frozen=True)
class OutputGroup:
    """Группа выходов спецификации с одинаковым габаритом."""

    dimensions: dict | None  # каноническая форма
    total_quantity: Decimal  # полное количество группы по спецификации


@dataclass(frozen=True)
class TransformSpec:
    """Спецификация трансформации задания: вход и группы выходов."""

    input_quantity: Decimal
    input_dimensions: dict | None  # каноническая форма
    output_groups: tuple[OutputGroup, ...]


@dataclass(frozen=True)
class TransformProgress:
    """Прогресс трансформации из ledger (суммы по task_id)."""

    consumed_quantity: Decimal  # SUM(TRANSFORM_CONSUME) — годные заготовки
    scrapped_quantity: Decimal  # SUM(SCRAP) — брак заготовок
    produced_by_group: dict[str | None, Decimal]  # SUM(COMPLETE) по габариту


def resolve_transform_spec(task: WorkTask, stage: RouteStage | None) -> TransformSpec | None:
    """Спецификация трансформации задания или None для обычного этапа.

    Трансформация активна только когда этап помечен маркером И задание
    несёт вход с выходами (edge case ADR-0003: позиция без операции —
    задание без dimensions, обычное завершение).
    """
    if stage is None or not stage.transforms_dimensions:
        return None
    if task.input_quantity is None or not (task.outputs or []):
        return None
    input_quantity = Decimal(str(task.input_quantity))
    if input_quantity <= 0:
        return None

    # Группировка выходов по каноническому габариту с сохранением порядка.
    order: list[str | None] = []
    totals: dict[str | None, Decimal] = {}
    dims_by_key: dict[str | None, dict | None] = {}
    for entry in task.outputs:
        raw_qty = entry.get("quantity")
        if raw_qty is None:
            continue
        quantity = Decimal(str(raw_qty))
        if quantity <= 0:
            continue
        dims = canonicalize_dimensions(entry.get("dimensions"))
        key = _dimensions_hash_key(dims)
        if key not in totals:
            order.append(key)
            totals[key] = Decimal("0")
            dims_by_key[key] = dims
        totals[key] += quantity
    if not order:
        return None

    return TransformSpec(
        input_quantity=input_quantity,
        input_dimensions=canonicalize_dimensions(task.input_dimensions),
        output_groups=tuple(
            OutputGroup(dimensions=dims_by_key[key], total_quantity=totals[key])
            for key in order
        ),
    )


async def get_transform_progress_bulk(
    db: AsyncSession, task_ids: list[int],
) -> dict[int, TransformProgress]:
    """Суммы трансформации по списку заданий — один GROUP BY запрос
    (для доски участка). Задания без движений отсутствуют в результате."""
    if not task_ids:
        return {}
    rows = await db.execute(
        select(
            StockTransaction.task_id,
            StockTransaction.reason,
            StockTransaction.dimensions,
            func.sum(StockTransaction.quantity).label("qty"),
        )
        .where(
            StockTransaction.task_id.in_(task_ids),
            StockTransaction.reason.in_(
                [Reason.TRANSFORM_CONSUME, Reason.COMPLETE, Reason.SCRAP]
            ),
        )
        .group_by(
            StockTransaction.task_id,
            StockTransaction.reason,
            StockTransaction.dimensions,
        )
    )
    consumed: dict[int, Decimal] = {}
    scrapped: dict[int, Decimal] = {}
    produced: dict[int, dict[str | None, Decimal]] = {}
    for task_id, reason_val, dims, qty in rows:
        qty = qty or Decimal("0")
        if reason_val == Reason.TRANSFORM_CONSUME.value:
            consumed[task_id] = (consumed.get(task_id) or Decimal("0")) + qty
        elif reason_val == Reason.SCRAP.value:
            scrapped[task_id] = (scrapped.get(task_id) or Decimal("0")) + qty
        else:
            key = _dimensions_hash_key(dims)
            per_task = produced.setdefault(task_id, {})
            per_task[key] = (per_task.get(key) or Decimal("0")) + qty
    return {
        task_id: TransformProgress(
            consumed_quantity=consumed.get(task_id) or Decimal("0"),
            scrapped_quantity=scrapped.get(task_id) or Decimal("0"),
            produced_by_group=produced.get(task_id) or {},
        )
        for task_id in {*consumed, *scrapped, *produced}
    }


async def get_transform_progress(db: AsyncSession, task_id: int) -> TransformProgress:
    """Суммы трансформации по заданию из StockTransaction ledger."""
    progress = (await get_transform_progress_bulk(db, [task_id])).get(task_id)
    if progress is None:
        return TransformProgress(
            consumed_quantity=Decimal("0"),
            scrapped_quantity=Decimal("0"),
            produced_by_group={},
        )
    return progress


async def resolve_consume_dimensions(
    db: AsyncSession,
    *,
    product_id: int,
    location_id: int,
    dimensions: dict | None,
    required: Decimal,
) -> dict | None:
    """Габаритная группа, из которой списывается вход порции.

    Обычно — входной габарит задания. Legacy-fallback: если материал
    пришёл на участок без габарита (перемещения до сквозной поддержки
    dimensions) и его хватает в NULL-группе — списываем из неё явно и
    детерминированно. Недостача не маскируется: возвращаем входной
    габарит, StockCommandService даст атомарный отказ.
    """
    dims = canonicalize_dimensions(dimensions)
    if dims is None:
        return None
    if await _group_balance(db, product_id, location_id, dims) >= required:
        return dims
    if await _group_balance(db, product_id, location_id, None) >= required:
        return None
    return dims


async def record_transform_portion(
    db: AsyncSession,
    *,
    svc: StockCommandService,
    task: WorkTask,
    spec: TransformSpec,
    progress: TransformProgress,
    good_quantity: Decimal,
    consume_dims: dict | None,
    actor_id: int,
    executor_user_id: int | None,
    comment: str | None,
    source_ref: str | None,
    idempotency_key: str | None,
    performed_at: datetime | None,
    accounted_at: datetime | None,
) -> list[int]:
    """Записать порцию трансформации в ledger: списание входа + все выходы.

    Все команды идут через StockCommandService в текущей транзакции БД —
    отказ любой из них (например, недостача входа) не оставляет частичных
    записей. Возвращает ids созданных транзакций.
    """
    tx_ids: list[int] = []

    # 1. Списание входа: good шт × входной габарит.
    tx_consume = await svc.record(db, StockCommand(
        product_id=task.product_id,
        from_location_id=task.section_id,
        to_location_id=None,
        quantity=good_quantity,
        reason=Reason.TRANSFORM_CONSUME,
        dimensions=consume_dims,
        quality_state=QualityState.GOOD,
        task_id=task.id,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        comment=comment,
        created_by=actor_id,
        executor_user_id=executor_user_id,
        performed_at=performed_at,
        accounted_at=accounted_at,
    ))
    tx_ids.append(tx_consume.id)

    # 2. Приход всех выходов пропорционально кумулятивной доле входа.
    consumed_after = progress.consumed_quantity + good_quantity
    for index, group in enumerate(spec.output_groups):
        target = (
            group.total_quantity * consumed_after / spec.input_quantity
        ).quantize(_QTY_STEP, rounding=ROUND_HALF_UP)
        produced_before = progress.produced_by_group.get(
            _dimensions_hash_key(group.dimensions)
        ) or Decimal("0")
        portion = target - produced_before
        if portion <= 0:
            continue
        tx_out = await svc.record(db, StockCommand(
            product_id=task.product_id,
            from_location_id=None,
            to_location_id=task.section_id,
            quantity=portion,
            reason=Reason.COMPLETE,
            dimensions=group.dimensions,
            quality_state=QualityState.GOOD,
            task_id=task.id,
            source_ref=source_ref,
            idempotency_key=f"{idempotency_key}:out{index}" if idempotency_key else None,
            comment=comment,
            created_by=actor_id,
            executor_user_id=executor_user_id,
            performed_at=performed_at,
            accounted_at=accounted_at,
        ))
        tx_ids.append(tx_out.id)

    return tx_ids


def build_outputs_progress(
    outputs: list[dict],
    produced_by_group: dict[str | None, Decimal],
) -> list[dict]:
    """Прогресс по каждой строке выходов для UI (доска пилы).

    Оприходованное количество группы распределяется по строкам с тем же
    габаритом последовательно (первая строка заполняется первой).
    Возвращает список ``{row_number, dimensions, quantity, produced_quantity}``
    с Decimal-количествами — форматирование на стороне query-слоя.
    """
    remaining = dict(produced_by_group)
    result: list[dict] = []
    for entry in outputs or []:
        raw_qty = entry.get("quantity")
        total = Decimal(str(raw_qty)) if raw_qty is not None else Decimal("0")
        dims = canonicalize_dimensions(entry.get("dimensions"))
        key = _dimensions_hash_key(dims)
        available = remaining.get(key) or Decimal("0")
        produced = min(total, available) if total > 0 else Decimal("0")
        remaining[key] = available - produced
        result.append({
            "row_number": entry.get("row_number"),
            "dimensions": dims,
            "quantity": total,
            "produced_quantity": produced,
        })
    return result


async def _group_balance(
    db: AsyncSession,
    product_id: int,
    location_id: int,
    dims: dict | None,
) -> Decimal:
    """Годный остаток габаритной группы на локации (0, если строки нет)."""
    balance = await db.scalar(
        select(StockBalance.balance_qty).where(
            StockBalance.product_id == product_id,
            StockBalance.location_id == location_id,
            StockBalance.quality_state == QualityState.GOOD,
            dimensions_match_clause(StockBalance.dimensions, dims),
        )
    )
    return balance or Decimal("0")
