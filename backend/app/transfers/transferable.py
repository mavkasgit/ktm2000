"""Сколько можно передать/отправить по (задача, размер) — глубокий модуль (тикет #131).

Один владелец трёхветочного dispatch «со склада / трансформация / обычная
задача». Раньше dispatch существовал дважды — в write-guard
(``transfers/services._get_task_transferable``) и в read-гидраторах ready-page
(``transfers/queries._hydrate_plain_ready_row`` /
``_hydrate_production_ready_row``); связывала их только договорённость
(комментарии «T6»), и расхождение write/read ловилось не тестом, а
прод-балансом. Теперь write и read — два вызывающих одного интерфейса:

- :func:`task_transferable` — write-guard: точечный лимит по (задача, размер).
  Вызывают ``transfer_send``/``correct_transfer``;
- :func:`task_transferable_lines` — read-эквивалент: разворачивание задачи в
  строки бюджета по размерам. Вызывают гидраторы ready-page;
- :func:`completed_qty_sq` — SQL-форма «произведено/завершено» для set-based
  потребителей (ready-запрос, оракул консистентности);
- :func:`compute_stock_section_transferable` — складская ветка (переехала из
  ``transfers/services`` без изменения семантики).

Три ветки живут ТОЛЬКО здесь:

- **stock** — складской участок (``is_stock_section``): нельзя больше
  плана позиции и больше физического остатка;
- **transform** — задание с выходами спецификации (ADR-0002): строка на
  каждый выход; produced закаплен ``min(output_quantity, produced_by_group)``
  на уровне ``build_output_rows`` (инвариант D2);
- **plain** — обычное задание: gross COMPLETE минус net переданное.

Выбор формулы — один раз в :meth:`TransferableLine.budget`, по ветке и
финальности участка: финальный этап — отправка (``budget.remaining_send``,
тикеты #96/#119), остальные — передача (``remaining_transform`` /
``remaining_plain``). Комментарии «T6: сведены договорённостью» заменены
типом: оба вызывающих собирают produced из одних источников, а выбор
формулы живёт в одном месте. Единственный остаточный нюанс: точечный
write-guard в transform/plain-ветках вычитает net переданного конкретного
размера, тогда как read-строки получают свою долю через распределение по
выходам — см. докстринг :func:`transform_point_budget`.

Границы тикета #131:

- формулы НЕ дублируются: чистый ярус живёт в ``app.transfers.budget``
  (#106/#119), SQL-ядро net-арифметики — ``stock.ledger.net_quantity_expr``
  (ADR-0017/0018); этот модуль — компоновщик источников, не владелец формул;
- формулы ``services/shopfloor/send_budget.py`` (#128, бюджет отправки с
  финального участка) не тронуты — они остались самостоятельным владельцем
  своего понятия;
- кэш StockProjectionManager (третий adapter) из бюджетной арифметики
  ИСКЛЮЧЁН, а не отложен: plain-produced читается напрямую из ledger (gross
  COMPLETE тем же примитивом :func:`completed_qty_sq`, что и read-SQL), так
  что у write- и read-путей не остаётся разных источников одного числа.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dimensions import canonicalize_dimensions, dimensions_equal
from app.models.internal_plan import SectionPlanLine
from app.models.route import RouteStage
from app.models.section import Section
from app.models.work_task import WorkTask
from app.services.route_storage_classifier import is_stock_section
from app.services.shopfloor.operations_transform import get_transform_progress
from app.services.shopfloor.output_rows import (
    UsedSource,
    build_output_rows,
    build_task_output_rows,
)
from app.stock import Reason
from app.stock.ledger import net_by_reason_sq, net_transferred
from app.stock.models import StockTransaction
from app.transfers import budget

__all__ = [
    "BudgetKind",
    "TransferableLine",
    "completed_qty_sq",
    "compute_stock_section_transferable",
    "plain_line",
    "plain_produced",
    "resolve_budget_kind",
    "stock_line",
    "task_transferable",
    "task_transferable_lines",
    "transform_lines",
    "transform_point_budget",
]


class BudgetKind(Enum):
    """Ветка dispatch «сколько можно передать по (задача, размер)»."""

    STOCK = "stock"          # складской участок: min(план-остаток, физ. остаток)
    TRANSFORM = "transform"  # задание с выходами спецификации (ADR-0002)
    PLAIN = "plain"          # обычное производственное задание


def _dec(value: Decimal | int | str | None) -> Decimal:
    """Нормализовать количество к Decimal, терпя None (nullable-колонки/скаляры).

    В отличие от ``shopfloor.common._to_decimal``, который требует значения,
    здесь ``None`` осмысленно означает «нет данных» → ``Decimal("0")``.
    """
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


@dataclass(frozen=True)
class TransferableLine:
    """Строка бюджета по одному размеру: план / произведено / использовано.

    ``produced`` — «произведено по размеру» (для stock — физический остаток,
    для plain — gross COMPLETE задачи); ``used`` — уже переданное
    (TRANSFER_SEND) или уже выпущенное (FINAL_RELEASE на финальном участке).
    """

    kind: BudgetKind
    dims: dict | None
    planned: Decimal
    produced: Decimal
    used: Decimal
    is_final: bool = False

    @property
    def budget(self) -> Decimal:
        """Единственное место выбора формулы бюджета по (ветка, финальность).

        Формулы сами по себе — чистый ярус ``app.transfers.budget`` (#106):
        здесь только выбирается, какая из них применяется к строке.
        """
        if self.kind is BudgetKind.STOCK:
            plan_remaining = max(Decimal("0"), self.planned - self.used)
            return budget.remaining_stock(plan_remaining, self.produced)
        if self.is_final:
            return budget.remaining_send(self.produced, self.used)
        if self.kind is BudgetKind.TRANSFORM:
            return budget.remaining_transform(self.produced, self.used)
        return budget.remaining_plain(self.produced, self.used)


# ─── Источники чисел (одни и те же для write- и read-путей) ─────────────────


def completed_qty_sq():
    """Gross COMPLETE по задачам — «произведено/завершено» в SQL-форме.

    Публичный примитив модуля (до #131 — приватный ``queries._completed_qty_subquery``):
    ready-запрос и оракул консистентности подключают его подзапросом вместо
    собственных копий агрегата.
    """
    return (
        select(
            StockTransaction.task_id,
            func.coalesce(func.sum(StockTransaction.quantity), 0).label("completed_qty"),
        )
        .where(StockTransaction.reason == Reason.COMPLETE)
        .group_by(StockTransaction.task_id)
        .subquery("completed_qty_sq")
    )


async def plain_produced(db: AsyncSession, task: WorkTask) -> Decimal:
    """«Произведено» обычной задачи: gross COMPLETE по задаче (всё, без размеров)."""
    sq = completed_qty_sq()
    return _dec(await db.scalar(select(sq.c.completed_qty).where(sq.c.task_id == task.id)))


async def _net_used_total(db: AsyncSession, task_id: int, reason: Reason) -> Decimal:
    """Net использованного по задаче БЕЗ размерного фильтра (total по ключу).

    Тот же ledger-примитив ``net_*_sq``, что подключает read-SQL ready-запроса.
    """
    sq = net_by_reason_sq(reason, alias="transferable_net_used_sq")
    return _dec(await db.scalar(select(sq.c.net_quantity).where(sq.c.task_id == task_id)))


async def resolve_budget_kind(
    db: AsyncSession,
    task: WorkTask,
    *,
    section: Section | None = None,
) -> tuple[BudgetKind, Section | None]:
    """Классифицировать задачу по одной из трёх веток dispatch."""
    sec = section if section is not None else await db.get(Section, task.section_id)
    if is_stock_section(sec):
        return BudgetKind.STOCK, sec
    if task.outputs:
        return BudgetKind.TRANSFORM, sec
    return BudgetKind.PLAIN, sec


# ─── Ветка stock ─────────────────────────────────────────────────────────────


async def compute_stock_section_transferable(
    db: AsyncSession,
    *,
    task: WorkTask,
    section: Section,
    planned_qty: Decimal,
    dimensions: dict | None = None,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Остаток к передаче со склада по паре (строка плана, размер).

    Возвращает ``(transferable, plan_remaining, physical_stock, already_transferred)``.
    Нельзя передать больше плана позиции и больше физического остатка на складе.
    ``already_transferred`` учитывается по размеру (не по строке целиком):
    несколько передач одного размера разрешены, сумма ограничена через
    ``transferable``.
    """
    from app.stock.models import QualityState, StockBalance
    from app.stock.services import dimensions_match_clause

    # Размер группы: если явный не передан — берём из задания (канонический
    # габарит плана). None = безразмерная legacy-группа.
    dims = dimensions if dimensions is not None else task.dimensions

    already_transferred = await net_transferred(
        db,
        section_plan_line_id=task.section_plan_line_id,
        dims=dims,
    )

    plan_remaining = max(Decimal("0"), _dec(planned_qty) - already_transferred)

    physical_stock_q = select(func.coalesce(func.sum(StockBalance.balance_qty), 0)).where(
        StockBalance.location_id == section.id,
        StockBalance.product_id == task.product_id,
        StockBalance.balance_qty > 0,
        StockBalance.quality_state == QualityState.GOOD,
    )
    # Задание несёт габарит (ADR-0001): остаток считается только по строке
    # баланса этой размерности. Без длины — legacy-поведение (все группы).
    if dims is not None:
        physical_stock_q = physical_stock_q.where(
            dimensions_match_clause(StockBalance.dimensions, dims)
        )
    physical_stock = _dec(await db.scalar(physical_stock_q))

    transferable = budget.remaining_stock(plan_remaining, physical_stock)
    return transferable, plan_remaining, physical_stock, already_transferred


async def _stock_planned_qty(db: AsyncSession, task: WorkTask) -> Decimal:
    """План складской задачи: план строки плана, при его отсутствии — план задания."""
    planned_qty = _dec(task.planned_quantity)
    line = await db.get(SectionPlanLine, task.section_plan_line_id)
    if line is not None and line.planned_quantity:
        planned_qty = _dec(line.planned_quantity)
    return planned_qty


async def stock_line(
    db: AsyncSession,
    *,
    task: WorkTask,
    section: Section,
    dims: dict | None = None,
    planned_qty: Decimal | None = None,
) -> TransferableLine:
    """Строка бюджета складской задачи — единственная сборка stock-ветки.

    ``dims`` — явный размер передачи (``None`` → габарит задания);
    ``planned_qty`` — явный план (``None`` → план строки плана, затем
    задания). И write-guard, и ready-страница со склада получают числа
    отсюда — второй сборки нет ни в services, ни в queries.
    """
    if planned_qty is None:
        planned_qty = await _stock_planned_qty(db, task)
    _transferable, _plan_remaining, physical_stock, already_transferred = (
        await compute_stock_section_transferable(
            db,
            task=task,
            section=section,
            planned_qty=planned_qty,
            dimensions=dims,
        )
    )
    return TransferableLine(
        kind=BudgetKind.STOCK,
        dims=dims if dims is not None else task.dimensions,
        planned=planned_qty,
        produced=physical_stock,
        used=already_transferred,
    )


# ─── Ветки transform / plain ────────────────────────────────────────────────


async def transform_lines(
    db: AsyncSession,
    task: WorkTask,
    *,
    used_source: UsedSource,
    is_final: bool = False,
) -> list[TransferableLine]:
    """Строка бюджета на каждый выход спецификации трансформирующей задачи.

    produced закаплен ``min(output, произведено группы)`` внутри
    ``build_output_rows``; распределение used по строкам одного размера —
    там же (последовательное заполнение, инвариант D2).
    """
    rows = await build_task_output_rows(
        db,
        task_id=task.id,
        outputs=task.outputs or [],
        used_source=used_source,
    )
    return [
        TransferableLine(
            kind=BudgetKind.TRANSFORM,
            dims=row.dimensions,
            planned=row.quantity,
            produced=row.produced_quantity,
            used=row.used_quantity,
            is_final=is_final,
        )
        for row in rows
    ]


async def plain_line(db: AsyncSession, task: WorkTask, *, is_final: bool) -> TransferableLine:
    """Строка бюджета обычной задачи: одна, с габаритом задания.

    Финальный участок — «использовано» это выпущенное (FINAL_RELEASE),
    иначе — переданное (TRANSFER_SEND); смысл выбирается здесь же, чтобы
    потребитель не копировал условие.
    """
    reason = Reason.FINAL_RELEASE if is_final else Reason.TRANSFER_SEND
    return TransferableLine(
        kind=BudgetKind.PLAIN,
        dims=task.dimensions,
        planned=_dec(task.planned_quantity),
        produced=await plain_produced(db, task),
        used=await _net_used_total(db, task.id, reason),
        is_final=is_final,
    )


async def transform_point_budget(
    db: AsyncSession,
    task: WorkTask,
    *,
    dims: dict | None,
) -> Decimal:
    """Точечный лимит трансформации по размеру (write-guard).

    «Произведено» — суммарно по строкам выхода этого размера (кап
    ``min(output_quantity, произведено группы)`` внутри ``build_output_rows``,
    тот же, что видит read-path); «уже переданное» — net по конкретному
    размеру БЕЗ последовательного распределения по строкам: точечный вопрос
    «сколько можно ещё ЭТОГО размера». При нескольких выходах одного размера
    ответ может быть строже суммы строковых бюджетов read-path —
    унаследованное поведение guard'а (осознанно сохранено в #131).
    """
    progress = await get_transform_progress(db, task.id)
    rows = build_output_rows(task.outputs or [], progress.produced_by_group, {})
    produced_for_dims = sum(
        (
            row.produced_quantity
            for row in rows
            if dimensions_equal(row.dimensions, dims)
        ),
        Decimal("0"),
    )
    transferred = await net_transferred(db, task_id=task.id, dims=dims)
    return budget.remaining_transform(produced_for_dims, transferred)


# ─── Публичные интерфейсы: read-развёртка и write-guard ─────────────────────


async def task_transferable_lines(
    db: AsyncSession,
    task: WorkTask,
    *,
    section: Section | None = None,
    stage: RouteStage | None = None,
) -> list[TransferableLine]:
    """Все строки бюджета задачи по размерам (read-эквивалент, #131).

    Обычная задача → одна строка (габарит задания); трансформирующая →
    строка на выход спецификации; складская → одна строка (план/остаток).
    ``section``/``stage`` — необязательные подсказки от вызывающего, у которого
    объекты уже загружены (гидраторы ready-page), чтобы не ходить в БД заново.

    Смысл бюджета по финальности участка выбран внутри: финальный этап —
    отправка (FINAL_RELEASE как «использовано», формула ``remaining_send``).
    """
    kind, sec = await resolve_budget_kind(db, task, section=section)

    if kind is BudgetKind.STOCK:
        # Со склада передача всегда «не финальная»: final release со склада
        # не существует, бюджет считается от переданного.
        return [await stock_line(db, task=task, section=sec)]

    stg = stage if stage is not None else await db.get(RouteStage, task.route_stage_id)
    is_final = bool(stg.is_final) if stg is not None else False

    if kind is BudgetKind.TRANSFORM:
        return await transform_lines(
            db,
            task,
            used_source=(
                UsedSource.NET_FINAL_RELEASE if is_final else UsedSource.NET_TRANSFERRED
            ),
            is_final=is_final,
        )

    return [await plain_line(db, task, is_final=is_final)]


async def task_transferable(
    db: AsyncSession,
    task: WorkTask,
    *,
    dimensions: dict | None = None,
) -> Decimal:
    """Точечный лимит передачи по (задача, размер) — write-guard (#131).

    Вызывают ``transfer_send``/``correct_transfer``. Финальность участка здесь
    НЕ выбирается: guard отвечает только за передачу, а с финального участка
    следующего шага нет (``transfer_send`` отклоняет раньше), отправка
    охраняется своим модулем ``shopfloor.send_budget`` (#128).

    Ветки:
    - **stock** — :func:`stock_line` с явным размером передачи;
    - **transform** — :func:`transform_point_budget`: произведено по размеру
      тем же капом строк выхода, что видит read-path; «уже переданное» —
      net по конкретному размеру;
    - **plain** — gross COMPLETE минус net переданного этого размера
      (``received`` в бюджете не участвует — бывший T6, теперь это свойство
      общей реализации: и read, и write читают одно число из одного места).
    """
    kind, sec = await resolve_budget_kind(db, task)

    if kind is BudgetKind.STOCK:
        line = await stock_line(
            db,
            task=task,
            section=sec,
            dims=dimensions,
            planned_qty=await _stock_planned_qty(db, task),
        )
        return line.budget

    if kind is BudgetKind.TRANSFORM:
        return await transform_point_budget(
            db, task, dims=canonicalize_dimensions(dimensions),
        )

    produced = await plain_produced(db, task)
    transferred_by_size = await net_transferred(db, task_id=task.id, dims=dimensions)
    return budget.remaining_plain(produced, transferred_by_size)
