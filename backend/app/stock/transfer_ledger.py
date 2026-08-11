"""Comp-aware ledger-примитив net-агрегации TRANSFER_SEND / TRANSFER_RECEIVE.

Чистый примитив поверх ``StockTransaction``: не знает ни о ``Transfer``,
ни о ``app.transfers`` (никаких циклов). Reason-параметризация ограничена
``TRANSFER_SEND`` и ``TRANSFER_RECEIVE``; прочие причины (COMPLETE, SCRAP,
RETURN_TO_STOCK и т.п.) не поддерживаются.

Все формы (scalar / grouped-by-dimensions / SQL-подзапрос) построены на
одном приватном comp-aware builder'е ``_net_quantity_expr()``:
``case(compensates_tx_id IS NULL → quantity, else_ -quantity)``.

Семантика ``dims``:
- Builder/SQL-форма (``_transfer_net_subquery`` / ``net_*_sq``):
  ``dims=None`` — БЕЗ dimension-фильтра (не wildcard), ``dims=dict`` —
  JSONB-равенство. Обслуживает set-based потребителей (total по ключу).
- Scalar-форма (``net_transferred`` / ``net_received``): ``dims=None`` =
  безразмерная группа (строки без габарита), ``dims=dict`` =
  JSONB-равенство. Такой же сдвиг ожидает тест ``net_*_by_dimensions``.
"""
from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import Select, Subquery, case, cast, func, or_, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.stock.models import Reason, StockTransaction

_NET_LABEL = "net_quantity"


def _dimensions_hash_key(dims: dict | None) -> str | None:
    """Хешируемый ключ grouping для dict-габарита (in-memory агрегации).

    Реплика конвенции ``app.stock.services._dimensions_hash_key``
    (``json.dumps(dims, sort_keys=True, ensure_ascii=False)``) — словарь из
    grouped-форм обязан совпадать с ключами существующих потребителей.
    """
    if dims is None:
        return None
    return json.dumps(dims, sort_keys=True, ensure_ascii=False)


def _dimensions_match_clause(column, dims: dict | None):
    """SQL-условие «габарит равен dims» с учётом NULL (legacy-группа).

    ``None`` матчит и SQL ``NULL``, и JSON ``null`` (asyncpg может сохранить
    ``'null'::jsonb`` вместо SQL NULL) — та же семантика, что у
    ``app.stock.services.dimensions_match_clause``.
    """
    if dims is None:
        return or_(column.is_(None), column == text("'null'::jsonb"))
    return column == cast(dims, JSONB)


def _net_quantity_expr():
    """Net-количество одной строки ledger: компенсация вычитается.

    ``case(compensates_tx_id IS NULL → quantity, else_ -quantity)`` — единая
    нетто-формула TRANSFER_SEND/TRANSFER_RECEIVE (см. transfers/services.py,
    transfers/queries.py, stock/services.py).
    """
    return case(
        (StockTransaction.compensates_tx_id.is_(None), StockTransaction.quantity),
        else_=-StockTransaction.quantity,
    )


def _transfer_net_subquery(
    *,
    reason: Reason,
    key_column,
    dims: dict | None,
) -> Select:
    """Групповой подзапрос ``select(key_column, sum(net)) group by key_column``.

    ``key_column`` — колонка ``StockTransaction.task_id`` или
    ``StockTransaction.section_plan_line_id``. Фильтр по ``reason`` и (при
    ``dims`` задан) JSONB-равенству ``dimensions``; ``dims=None`` — без
    dimension-фильтра.
    """
    stmt = select(
        key_column,
        func.coalesce(func.sum(_net_quantity_expr()), 0).label(_NET_LABEL),
    ).where(StockTransaction.reason == reason)
    if dims is not None:
        stmt = stmt.where(_dimensions_match_clause(StockTransaction.dimensions, dims))
    return stmt.group_by(key_column)


def _resolve_key(task_id, section_plan_line_id):
    """Ровно один из ключей: вернуть ``(key_column, key_value)``."""
    if (task_id is None) == (section_plan_line_id is None):
        raise ValueError(
            "exactly one of task_id / section_plan_line_id must be given"
        )
    if task_id is not None:
        return StockTransaction.task_id, task_id
    return StockTransaction.section_plan_line_id, section_plan_line_id


def _resolve_key_column(*, task_id: bool, section_plan_line_id: bool):
    """Ровно один из ключей: вернуть колонку ``StockTransaction``."""
    if task_id == section_plan_line_id:
        raise ValueError(
            "exactly one of task_id / section_plan_line_id must be True"
        )
    return StockTransaction.task_id if task_id else StockTransaction.section_plan_line_id


def _net_scalar_query(
    *,
    reason: Reason,
    task_id: int | None,
    section_plan_line_id: int | None,
    dims: dict | None,
) -> Select:
    """Scalar-select net по ровно одному ключу (общая логика SEND/RECEIVE).

    ``dims=None`` — безразмерная группа (строки без габарита), ``dims=dict`` —
    JSONB-равенство: та же семантика, что у скалярных форм
    ``net_transferred`` / ``net_received``.
    """
    key_column, key_value = _resolve_key(task_id, section_plan_line_id)
    return select(func.coalesce(func.sum(_net_quantity_expr()), 0)).where(
        StockTransaction.reason == reason,
        _dimensions_match_clause(StockTransaction.dimensions, dims),
        key_column == key_value,
    )


async def net_transferred(
    db: AsyncSession,
    *,
    task_id: int | None = None,
    section_plan_line_id: int | None = None,
    dims: dict | None = None,
) -> Decimal:
    """Скалярный net TRANSFER_SEND по ровно одному ключу.

    ``dims=None`` — безразмерная группа (строки без габарита);
    ``dims=dict`` — только строки этого габарита. Пусто → ``Decimal("0")``.
    """
    stmt = _net_scalar_query(
        reason=Reason.TRANSFER_SEND,
        task_id=task_id,
        section_plan_line_id=section_plan_line_id,
        dims=dims,
    )
    return (await db.scalar(stmt)) or Decimal("0")


async def net_received(
    db: AsyncSession,
    *,
    task_id: int | None = None,
    section_plan_line_id: int | None = None,
    dims: dict | None = None,
) -> Decimal:
    """Скалярный net TRANSFER_RECEIVE — аналогично ``net_transferred``."""
    stmt = _net_scalar_query(
        reason=Reason.TRANSFER_RECEIVE,
        task_id=task_id,
        section_plan_line_id=section_plan_line_id,
        dims=dims,
    )
    return (await db.scalar(stmt)) or Decimal("0")


async def _net_by_dimensions(
    db: AsyncSession,
    *,
    reason: Reason,
    task_id: int | None,
    section_plan_line_id: int | None,
) -> dict[str | None, Decimal]:
    """Grouped net по габаритам задачи/строки (все группы, включая NULL)."""
    key_column, key_value = _resolve_key(task_id, section_plan_line_id)
    rows = await db.execute(
        select(
            StockTransaction.dimensions,
            func.coalesce(func.sum(_net_quantity_expr()), 0).label(_NET_LABEL),
        )
        .where(StockTransaction.reason == reason, key_column == key_value)
        .group_by(StockTransaction.dimensions)
    )
    result: dict[str | None, Decimal] = {}
    for dims, net in rows:
        key = _dimensions_hash_key(dims)
        result[key] = (result.get(key) or Decimal("0")) + (net or Decimal("0"))
    return result


async def net_transferred_by_dimensions(
    db: AsyncSession,
    *,
    task_id: int | None = None,
    section_plan_line_id: int | None = None,
) -> dict[str | None, Decimal]:
    """Grouped net TRANSFER_SEND по габаритам.

    Ключи — ``hash_key`` габарита (``json.dumps sort_keys``); строки без
    габарита — под ключом ``None``.
    """
    return await _net_by_dimensions(
        db, reason=Reason.TRANSFER_SEND,
        task_id=task_id, section_plan_line_id=section_plan_line_id,
    )


async def net_received_by_dimensions(
    db: AsyncSession,
    *,
    task_id: int | None = None,
    section_plan_line_id: int | None = None,
) -> dict[str | None, Decimal]:
    """Grouped net TRANSFER_RECEIVE по габаритам — аналогично SEND."""
    return await _net_by_dimensions(
        db, reason=Reason.TRANSFER_RECEIVE,
        task_id=task_id, section_plan_line_id=section_plan_line_id,
    )


def net_transferred_sq(
    alias: str | None = None,
    *,
    task_id: bool = True,
    section_plan_line_id: bool = False,
    dims: dict | None = None,
) -> Select | Subquery:
    """SQL-форма net TRANSFER_SEND для set-based потребителей.

    Тот же comp-aware builder, что у scalar-формы. Возвращает групповой
    подзапрос ``select(key, net_quantity) group by key`` — пригодный для
    JOIN (по ``key``), WHERE и ORDER BY (по ``net_quantity``); корреляция
    с внешним запросом — по ключевой колонке (``task_id`` по умолчанию).
    ``dims=None`` — без dimension-фильтра (total по ключу).

    ``alias=None`` → сырой select; ``alias="t"`` → ``.subquery("t")``
    (колонки: ``t.c.task_id | t.c.section_plan_line_id``, ``t.c.net_quantity``).
    """
    key_column = _resolve_key_column(
        task_id=task_id, section_plan_line_id=section_plan_line_id
    )
    stmt = _transfer_net_subquery(
        reason=Reason.TRANSFER_SEND, key_column=key_column, dims=dims
    )
    if alias is not None:
        return stmt.subquery(alias)
    return stmt


def net_received_sq(
    alias: str | None = None,
    *,
    task_id: bool = True,
    section_plan_line_id: bool = False,
    dims: dict | None = None,
) -> Select | Subquery:
    """SQL-форма net TRANSFER_RECEIVE — аналогично ``net_transferred_sq``."""
    key_column = _resolve_key_column(
        task_id=task_id, section_plan_line_id=section_plan_line_id
    )
    stmt = _transfer_net_subquery(
        reason=Reason.TRANSFER_RECEIVE, key_column=key_column, dims=dims
    )
    if alias is not None:
        return stmt.subquery(alias)
    return stmt
