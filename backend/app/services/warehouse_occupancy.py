"""Занятость склада в штуках (#350).

Экран склада показывает по каждому складу три числа — ``in_work``,
``free``, ``total`` — и общий итог. Строка ответа — СКЛАД, а не продукт:
занятость больше не агрегируется по артикулу.

Формула и её источник в данных
-----------------------------

* ``total`` — физический годный остаток склада: сумма ``StockBalance``
  с ``quality_state = GOOD`` по складам-хранилищам (``STOCK_TYPES``, без
  брака и терминала — то же множество, что у выдачи и индикатора #207).
* ``in_work`` — часть этого остатка, расписанная открытыми позициями.
  Источник — существующий спрос #207
  (:func:`app.services.position_remainders.committed_demand_by_product_ids`):
  сумма плановых количеств выпущенных позиций с незавершёнными задачами.
  Второго учёта нет: занятость — производное от остатка и спроса.
* ``free = total - in_work`` — свободно к выдаче.

**Ёмкости склада в модели нет** — ``Section`` не хранит лимит, а объявить
его здесь значило бы выдумать число. Поэтому «всего» — это физический
остаток, а не «ёмкость»: ``total`` всегда равен сумме ``in_work + free``,
и по пустому складу все три числа — нули.

Разрез заявки по складам
------------------------

В данных нет брони на складскую строку: спрос #207 считается по продукту
целиком. Поэтому заявка продукта закрывается складами в системном порядке
участков (``Section.sort_order``, затем ``id``) и никогда не превышает
остатка на складе::

    claim_w = min(остаток_w, остаток_заявки)

Порядок детерминирован и совпадает с «вычерпыванием» выдачи: материал
расписан с первых складов завода, и экран честно показывает, с какого
склада брать уже нельзя. Документированное упрощение: заявка продукта не
несёт осей размера и пройденных операций, поэтому точная привязка к
строке баланса появится только вместе с настоящей бронью — это
за пределами #350.

Позиция не вычитает сама себя на уровне индикатора позиции (#207), но
складская занятость — свойство склада: здесь учитывается весь спрос
открытых позиций, включая ту, ради которой открыт экран.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.section import Section
from app.services.position_remainders import committed_demand_by_product_ids
from app.services.route_storage_classifier import STOCK_TYPES
from app.stock.models import QualityState, StockBalance

__all__ = ["WarehouseOccupancy", "WarehouseOccupancyRow", "warehouse_occupancy"]

ZERO = Decimal(0)


@dataclass(frozen=True)
class WarehouseOccupancyRow:
    """Один склад: занято, свободно, всего — в штуках."""

    warehouse_id: int
    warehouse: str
    warehouse_code: str
    in_work: Decimal
    free: Decimal
    total: Decimal


@dataclass(frozen=True)
class WarehouseOccupancy:
    """Строки по складам и их сумма — «общий итог» экрана."""

    warehouses: tuple[WarehouseOccupancyRow, ...]
    in_work: Decimal
    free: Decimal
    total: Decimal


async def warehouse_occupancy(db: AsyncSession) -> WarehouseOccupancy:
    """Посчитать занятость по каждому складу-хранилищу (см. докстринг модуля).

    Пустой склад остаётся в ответе нулевой строкой: «здесь ничего нет» —
    содержательный факт, а не повод спрятать склад из списка.
    """
    warehouses = (
        await db.execute(
            select(
                Section.id,
                Section.code,
                Section.name,
                Section.sort_order,
            )
            .where(Section.type.in_(STOCK_TYPES))
            .order_by(Section.sort_order.asc(), Section.id.asc())
        )
    ).all()
    if not warehouses:
        return WarehouseOccupancy(warehouses=(), in_work=ZERO, free=ZERO, total=ZERO)

    location_ids = [row.id for row in warehouses]
    stock_rows = (
        await db.execute(
            select(
                StockBalance.location_id,
                StockBalance.product_id,
                func.sum(StockBalance.balance_qty).label("quantity"),
            )
            .where(
                StockBalance.location_id.in_(location_ids),
                StockBalance.balance_qty > 0,
                StockBalance.quality_state == QualityState.GOOD,
            )
            .group_by(StockBalance.location_id, StockBalance.product_id)
        )
    ).all()

    # (location_id, product_id) → физический остаток; итог по складу и
    # по продукту — две свёртки одного и того же чтения.
    stock_by_pair: dict[tuple[int, int], Decimal] = {}
    stock_by_warehouse: dict[int, Decimal] = {}
    stock_by_product: dict[int, Decimal] = {}
    for location_id, product_id, quantity in stock_rows:
        qty = Decimal(quantity or 0)
        if qty <= 0:
            continue
        stock_by_pair[(location_id, product_id)] = qty
        stock_by_warehouse[location_id] = stock_by_warehouse.get(location_id, ZERO) + qty
        stock_by_product[product_id] = stock_by_product.get(product_id, ZERO) + qty

    demand = await committed_demand_by_product_ids(db, set(stock_by_product))

    # Заявка продукта закрывается складами в системном порядке и не больше
    # физического остатка на складе: свободным может быть только то, что
    # реально лежит.
    in_work_by_pair: dict[tuple[int, int], Decimal] = {}
    for product_id, total_qty in stock_by_product.items():
        remaining = min(Decimal(str(demand.get(product_id, 0.0))), total_qty)
        if remaining <= 0:
            continue
        for row in warehouses:
            if remaining <= 0:
                break
            pair_qty = stock_by_pair.get((row.id, product_id), ZERO)
            if pair_qty <= 0:
                continue
            claim = min(remaining, pair_qty)
            in_work_by_pair[(row.id, product_id)] = claim
            remaining -= claim

    rows: list[WarehouseOccupancyRow] = []
    totals_in_work = ZERO
    totals_free = ZERO
    totals_total = ZERO
    for warehouse in warehouses:
        total_qty = stock_by_warehouse.get(warehouse.id, ZERO)
        in_work = sum(
            (claim for (location_id, _product_id), claim in in_work_by_pair.items()
             if location_id == warehouse.id),
            ZERO,
        )
        free = total_qty - in_work
        rows.append(
            WarehouseOccupancyRow(
                warehouse_id=warehouse.id,
                warehouse=warehouse.name,
                warehouse_code=warehouse.code,
                in_work=in_work,
                free=free,
                total=total_qty,
            )
        )
        totals_in_work += in_work
        totals_free += free
        totals_total += total_qty

    return WarehouseOccupancy(
        warehouses=tuple(rows),
        in_work=totals_in_work,
        free=totals_free,
        total=totals_total,
    )
