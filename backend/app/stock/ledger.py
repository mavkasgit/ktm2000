"""Ledger-примитив нетто-агрегации по причине (ADR-0017, срез — ADR-0018).

Чистый примитив поверх ``StockTransaction``: не знает ни о ``Transfer``,
ни о ``app.transfers`` (никаких циклов).

Семантика нетто (contract):
  net(reason) = Σ активных транзакций причины − Σ компенсирующих транзакций.
Компенсация = запись с ``compensates_tx_id`` → исходная; из net ВЫЧИТАЕТСЯ
компенсирующая запись, а не исключается скомпенсированная.

Единственный источник компенсационной арифметики — ``net_quantity_expr()``
(row-level). ``net_by_reason*`` — его публичные query-композиции (scalar /
grouped-by-dimensions / SQL-подзапрос); thin wrappers (``net_transferred`` и
т.п.) — специализированные причины для удобства потребителей. Потребители
строят свои GROUP BY / JOIN над ``net_quantity_expr()`` и не интерпретируют
``compensates_tx_id`` для вычисления net самостоятельно.

Capability и policy разделены (ADR-0017): ledger умеет вычислять net для
ЛЮБОЙ причины; какие причины бизнес-операция вправе компенсировать — решение
операции, не этого модуля. COMPLETE/SCRAP читаются gross не из-за
ограничения ledger, а из-за отсутствия доменного требования компенсационного
поведения (ADR-0018).

Семантика ``dims``:
- Builder/SQL-форма (``_transfer_net_subquery`` / ``net_by_reason_sq``):
  ``dims=None`` — БЕЗ dimension-фильтра (не wildcard), ``dims=dict`` —
  JSONB-равенство. Обслуживает set-based потребителей (total по ключу).
- Scalar-форма (``net_by_reason`` / thin wrappers): ``dims=None`` =
  безразмерная группа (строки без габарита), ``dims=dict`` =
  JSONB-равенство.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Select, Subquery, case, cast, func, or_, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.stock.models import Reason, StockTransaction

_NET_LABEL = "net_quantity"


def _dimensions_match_clause(column, dims: dict | None):
    """SQL-условие «габарит равен dims» с учётом NULL (legacy-группа).

    ``None`` матчит и SQL ``NULL``, и JSON ``null`` (asyncpg может сохранить
    ``'null'::jsonb`` вместо SQL NULL) — та же семантика, что у
    ``app.stock.services.dimensions_match_clause``.
    """
    if dims is None:
        return or_(column.is_(None), column == text("'null'::jsonb"))
    return column == cast(dims, JSONB)


def net_quantity_expr():
    """Row-level net-количество одной строки ledger: компенсация вычитается.

    ``case(compensates_tx_id IS NULL → quantity, else_ -quantity)`` — единая
    нетто-формула для ЛЮБОЙ причины (ADR-0017). Единственное место, где
    ``compensates_tx_id`` интерпретируется для вычисления net; всё остальное
    строится поверх этого выражения.
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
        func.coalesce(func.sum(net_quantity_expr()), 0).label(_NET_LABEL),
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
    """Scalar-select net по причине и ровно одному ключу.

    ``dims=None`` — безразмерная группа (строки без габарита), ``dims=dict`` —
    JSONB-равенство.
    """
    key_column, key_value = _resolve_key(task_id, section_plan_line_id)
    return select(func.coalesce(func.sum(net_quantity_expr()), 0)).where(
        StockTransaction.reason == reason,
        _dimensions_match_clause(StockTransaction.dimensions, dims),
        key_column == key_value,
    )


async def net_by_reason(
    db: AsyncSession,
    *,
    reason: Reason,
    task_id: int | None = None,
    section_plan_line_id: int | None = None,
    dims: dict | None = None,
) -> Decimal:
    """Скалярный net по произвольной причине и ровно одному ключу.

    ``dims=None`` — безразмерная группа (строки без габарита);
    ``dims=dict`` — только строки этого габарита. Пусто → ``Decimal("0")``.
    """
    stmt = _net_scalar_query(
        reason=reason,
        task_id=task_id,
        section_plan_line_id=section_plan_line_id,
        dims=dims,
    )
    return (await db.scalar(stmt)) or Decimal("0")


async def net_transferred(
    db: AsyncSession,
    *,
    task_id: int | None = None,
    section_plan_line_id: int | None = None,
    dims: dict | None = None,
) -> Decimal:
    """Скалярный net TRANSFER_SEND — thin wrapper над ``net_by_reason``."""
    return await net_by_reason(
        db, reason=Reason.TRANSFER_SEND,
        task_id=task_id, section_plan_line_id=section_plan_line_id, dims=dims,
    )


async def net_received(
    db: AsyncSession,
    *,
    task_id: int | None = None,
    section_plan_line_id: int | None = None,
    dims: dict | None = None,
) -> Decimal:
    """Скалярный net TRANSFER_RECEIVE — thin wrapper над ``net_by_reason``."""
    return await net_by_reason(
        db, reason=Reason.TRANSFER_RECEIVE,
        task_id=task_id, section_plan_line_id=section_plan_line_id, dims=dims,
    )


async def net_by_reason_by_dimensions(
    db: AsyncSession,
    *,
    reason: Reason,
    task_id: int | None = None,
    section_plan_line_id: int | None = None,
) -> dict[str | None, Decimal]:
    """Grouped net по причине и габаритам задачи/строки (все группы, включая NULL).

    Ключи — ``hash_key`` габарита (``json.dumps sort_keys``); строки без
    габарита — под ключом ``None``.
    """
    # Lazy-импорт: ledger↔stock.services — цикл на уровне модулей (services
    # импортирует ledger). Канон живёт в stock.services до к.3 (дом размера).
    from app.stock.services import _dimensions_hash_key

    key_column, key_value = _resolve_key(task_id, section_plan_line_id)
    rows = await db.execute(
        select(
            StockTransaction.dimensions,
            func.coalesce(func.sum(net_quantity_expr()), 0).label(_NET_LABEL),
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
    """Grouped net TRANSFER_SEND — thin wrapper над ``net_by_reason_by_dimensions``."""
    return await net_by_reason_by_dimensions(
        db, reason=Reason.TRANSFER_SEND,
        task_id=task_id, section_plan_line_id=section_plan_line_id,
    )


async def net_received_by_dimensions(
    db: AsyncSession,
    *,
    task_id: int | None = None,
    section_plan_line_id: int | None = None,
) -> dict[str | None, Decimal]:
    """Grouped net TRANSFER_RECEIVE — thin wrapper над ``net_by_reason_by_dimensions``."""
    return await net_by_reason_by_dimensions(
        db, reason=Reason.TRANSFER_RECEIVE,
        task_id=task_id, section_plan_line_id=section_plan_line_id,
    )


def net_by_reason_sq(
    reason: Reason,
    alias: str | None = None,
    *,
    task_id: bool = True,
    section_plan_line_id: bool = False,
    dims: dict | None = None,
) -> Select | Subquery:
    """SQL-форма net по произвольной причине для set-based потребителей.

    Групповой подзапрос ``select(key, net_quantity) group by key`` — пригодный
    для JOIN (по ``key``), WHERE и ORDER BY (по ``net_quantity``); корреляция
    с внешним запросом — по ключевой колонке (``task_id`` по умолчанию).
    ``dims=None`` — без dimension-фильтра (total по ключу).

    ``alias=None`` → сырой select; ``alias="t"`` → ``.subquery("t")``
    (колонки: ``t.c.task_id | t.c.section_plan_line_id``, ``t.c.net_quantity``).
    """
    key_column = _resolve_key_column(
        task_id=task_id, section_plan_line_id=section_plan_line_id
    )
    stmt = _transfer_net_subquery(
        reason=reason, key_column=key_column, dims=dims
    )
    if alias is not None:
        return stmt.subquery(alias)
    return stmt


def net_transferred_sq(
    alias: str | None = None,
    *,
    task_id: bool = True,
    section_plan_line_id: bool = False,
    dims: dict | None = None,
) -> Select | Subquery:
    """SQL-форма net TRANSFER_SEND — thin wrapper над ``net_by_reason_sq``."""
    return net_by_reason_sq(
        Reason.TRANSFER_SEND, alias,
        task_id=task_id, section_plan_line_id=section_plan_line_id, dims=dims,
    )


def net_received_sq(
    alias: str | None = None,
    *,
    task_id: bool = True,
    section_plan_line_id: bool = False,
    dims: dict | None = None,
) -> Select | Subquery:
    """SQL-форма net TRANSFER_RECEIVE — thin wrapper над ``net_by_reason_sq``."""
    return net_by_reason_sq(
        Reason.TRANSFER_RECEIVE, alias,
        task_id=task_id, section_plan_line_id=section_plan_line_id, dims=dims,
    )
