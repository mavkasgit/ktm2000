"""Остатки для индикатора планирования (#207).

Два числа с двумя именами (решение Q4 тикета #207) — раньше здесь было
одно, и оно вычитало само себя:

* **Свободно на складах** (``free_stock``) — физический годный остаток
  артикула по складам-хранилищам. Свойство склада: не зависит ни от
  какой позиции.
* **Доступно для позиции** (``available_for_position``) — свободно минус то,
  что занято **чужими** открытыми позициями. Свойство пары
  «позиция + склад».
* **Дефицит позиции** (``deficit``) — сколько не хватает до планового
  количества позиции.

Три правила, которые этот модуль обязан обеспечивать:

1. **Позиция не вычитает сама себя.** Прежде индикатор суммировал
   плановые количества всех запущенных позиций, включая ту, для которой
   он и считается: ЮП-460 показывал ``1500 − 1512 = −12 → 0`` для
   запущенной позиции, то есть практически всегда. Спрос — величина
   агрегатная (по артикулу), «свой» спрос позиции — нет, поэтому он
   считается отдельно и вычитается: ``доступно = свободно − (весь спрос −
   свой спрос)``. Две позиции одного артикула видят друг друга как чужие.
2. **Брак не источник.** Множество секций — то же, что у выдачи
   (``STOCK_TYPES``: raw/wip/finished), а не ``OPERATIONAL_STOCK_TYPES``,
   куда входит ``scrap``. Раньше индикатор и выдача считались по разным
   правилам, и на одном экране показывались два несовпадающих числа.
3. **«Действительно ноль» и «неизвестно» — не одно и то же.** Нет данных
   о наличии → ``None``, индикатор не показывается; есть данные и их
   ноль → ``0.0``.

Оперативный баланс цеховых секций в остаток не входит: материал,
выданный открытой задаче, лежит на участке как баланс участка, но
свободным сырьём для планирования он не является.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_plan import SectionPlanLine
from app.models.production_plan import PlanPosition, PlanPositionStatus
from app.models.section import Section
from app.models.work_task import CLOSED_WORK_TASK_STATUSES, WorkTask
from app.services.route_storage_classifier import STOCK_TYPES
from app.stock.models import QualityState, StockBalance


@dataclass(frozen=True)
class ProductStockFigures:
    """Остатки одного артикула: что свободно и что доступно позиции."""

    free_stock: float
    available_for_position: float


@dataclass(frozen=True)
class PositionStockFigures:
    """Три числа индикатора позиции.

    Любое из них ``None`` означает «данных о наличии нет» — индикатор не
    показывается. Ноль — это ноль, а не неизвестно.
    """

    free_stock: float | None
    available_for_position: float | None
    deficit: float | None

    def as_fields(self) -> dict[str, float | None]:
        """Три числа в форме ответа API.

        Форму держит сам доменный тип: раскладка «три поля + округление»
        повторялась в семи местах, и правка четвёртого числа индикатора
        требовала бы семи одинаковых правок. Округление здесь же, и
        ``None`` («нет данных о наличии») переживает его нетронутым.
        """
        return {
            "free_stock_quantity": _rounded_or_none(self.free_stock),
            "available_remainder_quantity": _rounded_or_none(
                self.available_for_position
            ),
            "deficit_quantity": _rounded_or_none(self.deficit),
        }


def _rounded_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


async def free_stock_by_product_ids(
    db: AsyncSession,
    product_ids: set[int],
) -> dict[int, float]:
    """«Свободно на складах»: годный остаток по складам-хранилищам."""
    if not product_ids:
        return {}

    rows = await db.execute(
        select(
            StockBalance.product_id,
            func.coalesce(func.sum(StockBalance.balance_qty), 0),
        )
        .join(Section, Section.id == StockBalance.location_id)
        .where(
            StockBalance.product_id.in_(product_ids),
            StockBalance.balance_qty > 0,
            StockBalance.quality_state == QualityState.GOOD,
            # То же множество, что у выдачи (#207 Q3): брак — не свободное
            # сырьё, терминал — вне оперативных остатков.
            Section.type.in_(STOCK_TYPES),
        )
        .group_by(StockBalance.product_id)
    )
    return {int(product_id): float(total or 0) for product_id, total in rows.all()}


async def committed_demand_by_product_ids(
    db: AsyncSession,
    product_ids: set[int],
) -> dict[int, float]:
    """Спрос запущенных позиций по артикулам — сумма, включая «своих».

    Считается один раз на страницу; «свой» спрос позиции вычитается
    отдельно в :func:`product_stock_figures`.

    Позиция пары расходует равные количества ОБОИХ компонентов (``N×A + N×B``),
    хотя её строки и задачи несут только ``product_a``: одиночные позиции
    агрегируются в SQL, парные раскрываются по их эффективным продуктам.
    """
    if not product_ids:
        return {}

    open_task_on_position = exists(
        select(1)
        .select_from(SectionPlanLine)
        .join(WorkTask, WorkTask.section_plan_line_id == SectionPlanLine.id)
        .where(
            SectionPlanLine.plan_position_id == PlanPosition.id,
            WorkTask.status.notin_(CLOSED_WORK_TASK_STATUSES),
        )
    )

    position_rows = (
        select(
            PlanPosition.id.label("position_id"),
            PlanPosition.quantity.label("quantity"),
            func.min(SectionPlanLine.product_id).label("product_id"),
        )
        .join(SectionPlanLine, SectionPlanLine.plan_position_id == PlanPosition.id)
        .where(
            SectionPlanLine.product_id.in_(product_ids),
            # Парные позиции (product_id IS NULL) разбираем ниже: их строки
            # несут один компонент, агрегат по строкам потерял бы второй.
            PlanPosition.product_id.isnot(None),
            PlanPosition.status == PlanPositionStatus.released,
            open_task_on_position,
        )
        .group_by(PlanPosition.id, PlanPosition.quantity)
    ).subquery()

    rows = await db.execute(
        select(
            position_rows.c.product_id,
            func.coalesce(func.sum(position_rows.c.quantity), 0),
        ).group_by(position_rows.c.product_id)
    )
    demand = {int(product_id): float(total or 0) for product_id, total in rows.all()}

    from app.services import product_pair_resolver

    pair_positions = (
        await db.execute(
            select(PlanPosition).where(
                PlanPosition.product_id.is_(None),
                PlanPosition.status == PlanPositionStatus.released,
                open_task_on_position,
            )
        )
    ).scalars().all()
    resolved_cache: dict[tuple[str, ...], list[int]] = {}
    for position in pair_positions:
        resolved_key = product_pair_resolver.pair_component_key(
            product_pair_resolver.paired_component_skus(position)
        )
        if resolved_key not in resolved_cache:
            resolved_cache[resolved_key] = await product_pair_resolver.resolve_effective_product_ids(
                db, position
            )
        component_ids = resolved_cache[resolved_key]
        if not component_ids:
            # Пара не резолвится (нет снапшота и строки в справочнике): списываем
            # с того, что записано в строках позиции, — иначе её запуск не
            # уменьшил бы остаток ни одного компонента.
            component_ids = [
                int(line_product_id)
                for line_product_id in (
                    await db.execute(
                        select(SectionPlanLine.product_id)
                        .where(SectionPlanLine.plan_position_id == position.id)
                        .distinct()
                    )
                ).scalars().all()
                if line_product_id is not None
            ]
        for product_id in component_ids:
            if product_id in product_ids:
                demand[product_id] = demand.get(product_id, 0.0) + float(position.quantity or 0)
    return demand


def product_stock_figures(
    *,
    product_id: int,
    free_by_product: dict[int, float],
    total_demand: dict[int, float],
    own_demand: dict[int, float] | None = None,
) -> ProductStockFigures:
    """Свести остаток и спрос по одному артикулу.

    ``own_demand`` — сколько этого артикула занимает САМА позиция, для
    которой считается индикатор. Её собственный спрос в «доступно» не
    входит: позиция не занимает свой же материал (#207, дефект 1).
    """
    free = free_by_product.get(product_id, 0.0)
    # Свой спрос вычитается из АГРЕГАТНОГО и не может превысить агрегат:
    # позиция, которой ещё нет в спросе (не released или без открытых
    # задач), не должна УВЕЛИЧИВАЬ доступный остаток.
    committed = max(
        0.0, total_demand.get(product_id, 0.0) - (own_demand or {}).get(product_id, 0.0)
    )
    return ProductStockFigures(
        free_stock=free,
        available_for_position=max(0.0, free - committed),
    )


def position_stock_figures(
    per_product: dict[int, ProductStockFigures],
    product_ids: list[int],
    *,
    required_quantity: float,
) -> PositionStockFigures:
    """Свести остатки компонентов позиции в три числа индикатора.

    Пара заходит на маршрут как единая загрузка ``N×A + N×B``: нужны
    равные количества обоих, поэтому и свободный остаток, и доступный
    берутся минимумом по компонентам. Дефицит — против планового
    количества позиции.

    Пустой ``product_ids`` → все три поля ``None``: данных о наличии нет.
    """
    if not product_ids:
        return PositionStockFigures(
            free_stock=None, available_for_position=None, deficit=None
        )
    free = min(per_product[pid].free_stock for pid in product_ids)
    available = min(per_product[pid].available_for_position for pid in product_ids)
    return PositionStockFigures(
        free_stock=free,
        available_for_position=available,
        deficit=max(0.0, required_quantity - available),
    )


async def compute_position_stock_figures(
    db: AsyncSession,
    positions: Sequence[tuple[int, list[int], float]],
) -> dict[int, PositionStockFigures]:
    """Индикатор сразу для нескольких позиций — два запроса, не N+1.

    ``positions`` — тройки ``(plan_position_id, эффективные product_id,
    плановое количество)``. Позиции без артикулов или без данных о наличии
    получают три ``None``.
    """
    product_ids: set[int] = set()
    for _position_id, effective_ids, _quantity in positions:
        product_ids.update(effective_ids)

    free_by_product, total_demand = await free_stock_by_product_ids(
        db, product_ids
    ), await committed_demand_by_product_ids(db, product_ids)

    result: dict[int, PositionStockFigures] = {}
    for position_id, effective_ids, required_quantity in positions:
        own_demand = dict.fromkeys(effective_ids, required_quantity)
        per_product = {
            product_id: product_stock_figures(
                product_id=product_id,
                free_by_product=free_by_product,
                total_demand=total_demand,
                own_demand=own_demand,
            )
            for product_id in effective_ids
        }
        result[position_id] = position_stock_figures(
            per_product, effective_ids, required_quantity=required_quantity
        )
    return result

