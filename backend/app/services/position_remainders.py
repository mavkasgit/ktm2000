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

С #394 (эквивалентные артикулы, ADR-0073) те же три числа считаются по
группе: остаток и спрос суммируются по всем её членам, «свой» спрос
вычитается по группе, а раскладка ``free_stock_breakdown`` показывает
SKU, из которых сложился пул.
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
from app.services.product_alias_groups import (
    AliasGroup,
    AliasGroups,
    load_alias_groups,
)
from app.services.route_storage_classifier import STOCK_TYPES
from app.stock.models import QualityState, StockBalance


@dataclass(frozen=True)
class ProductStockFigures:
    """Остатки одного артикула: что свободно и что доступно позиции."""

    free_stock: float
    available_for_position: float


@dataclass(frozen=True)
class StockBreakdownLine:
    """Строка раскладки свободного остатка группы по фактическому SKU."""

    product_id: int
    sku: str | None
    quantity: float


@dataclass(frozen=True)
class PositionStockFigures:
    """Три числа индикатора позиции и раскладка группы по SKU.

    Любое из чисел ``None`` означает «данных о наличии нет» — индикатор не
    показывается. Ноль — это ноль, а не неизвестно. ``breakdown`` — та
    группа, которая дала ``free_stock`` (при паре в нескольких группах —
    связывающая, с минимальным ``free_g``); для ``None`` список пуст.
    """

    free_stock: float | None
    available_for_position: float | None
    deficit: float | None
    breakdown: tuple[StockBreakdownLine, ...] = ()

    def as_fields(self) -> dict[str, object]:
        """Числа индикатора в форме ответа API.

        Форму держит сам доменный тип: раскладка «три поля + округление»
        повторялась в семи местах, и правка четвёртого числа индикатора
        требовала бы семи одинаковых правок. Округление здесь же, и
        ``None`` («нет данных о наличии») переживает его нетронутым.

        ``free_stock_breakdown`` — расшифровка группы по SKU (§3 спеки).
        Последняя строка подправляется на копейки округления, чтобы сумма
        раскладки сходилась с уже округлённым ``free_stock_quantity``.
        """
        rounded_free = _rounded_or_none(self.free_stock)
        breakdown = [
            {
                "product_id": line.product_id,
                "sku": line.sku,
                "quantity": round(line.quantity, 3),
            }
            for line in self.breakdown
        ]
        if breakdown and rounded_free is not None:
            delta = round(
                rounded_free - sum(row["quantity"] for row in breakdown), 3
            )
            if delta:
                breakdown[-1]["quantity"] = round(
                    breakdown[-1]["quantity"] + delta, 3
                )
        return {
            "free_stock_quantity": rounded_free,
            "available_remainder_quantity": _rounded_or_none(
                self.available_for_position
            ),
            "deficit_quantity": _rounded_or_none(self.deficit),
            "free_stock_breakdown": breakdown,
        }


def _rounded_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


async def free_stock_by_product_ids(
    db: AsyncSession,
    product_ids: set[int],
) -> dict[int, float]:
    """«Свободно на складах»: годный остаток по складам-хранилищам.

    Результат — разбивка по ``product_id``, поэтому он же служит
    ``free_stock_breakdown`` группы: отдельного запроса за раскладкой нет.
    """
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
    pair_cache = product_pair_resolver.PairResolutionCache()
    for position in pair_positions:
        component_ids = await product_pair_resolver.resolve_effective_product_ids(
            db, position, cache=pair_cache
        )
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


def _position_group_figures(
    *,
    aliases: AliasGroups,
    effective_ids: Sequence[int],
    required_quantity: float,
    free_by_product: dict[int, float],
    total_demand: dict[int, float],
) -> PositionStockFigures:
    """Свести пул групп позиции в три числа и раскладку (#394, спека §3).

    ``free_g`` — сумма остатка всех членов группы; ``demand_g`` — спрос
    открытых позиций на любом члене; ``own_g`` — потребность самой позиции
    в этой группе (``Q`` на каждый её компонент, для пары в одной группе —
    ``2Q``). ``available_g = max(0, free_g − max(0, demand_g − own_g))``;
    позиция не вычитает сама себя.

    Пара в нескольких группах связывает минимум: ``free``/``available`` —
    минимум по группам, ``deficit`` — максимум недостачи по группе.
    """
    unique_ids = tuple(dict.fromkeys(int(product_id) for product_id in effective_ids))
    if not unique_ids:
        return PositionStockFigures(None, None, None)

    groups: dict[int, AliasGroup] = {}
    for product_id in unique_ids:
        group = aliases.group_for(product_id)
        if group is None:
            # Продукт не резолвится в группу — данных о наличии нет.
            return PositionStockFigures(None, None, None)
        groups[group.key] = group

    own_by_product = dict.fromkeys(unique_ids, float(required_quantity))
    metrics: list[tuple[AliasGroup, float, float, float]] = []
    for group in groups.values():
        free_g = sum(free_by_product.get(pid, 0.0) for pid in group.product_ids)
        demand_g = sum(total_demand.get(pid, 0.0) for pid in group.product_ids)
        own_g = sum(own_by_product.get(pid, 0.0) for pid in group.product_ids)
        available_g = max(0.0, free_g - max(0.0, demand_g - own_g))
        metrics.append((group, free_g, available_g, own_g))

    free_stock = min(free_g for _group, free_g, _available, _own in metrics)
    available = min(available_g for _group, _free, available_g, _own in metrics)
    deficit = max(
        max(0.0, own_g - available_g)
        for _group, _free, available_g, own_g in metrics
    )

    # Раскладка — связывающая группа: минимальный free_g, при равенстве —
    # меньший group_key (детерминированно).
    binding_group = min(metrics, key=lambda item: (item[1], item[0].key))[0]
    breakdown = tuple(
        StockBreakdownLine(
            product_id=product_id,
            sku=sku,
            quantity=free_by_product[product_id],
        )
        for product_id, sku in zip(
            binding_group.product_ids, binding_group.skus, strict=True
        )
        if free_by_product.get(product_id, 0.0) > 0
    )
    return PositionStockFigures(
        free_stock=free_stock,
        available_for_position=available,
        deficit=deficit,
        breakdown=breakdown,
    )


async def compute_position_stock_figures(
    db: AsyncSession,
    positions: Sequence[tuple[int, list[int], float]],
) -> dict[int, PositionStockFigures]:
    """Индикатор сразу для нескольких позиций — три запроса, не N+1.

    ``positions`` — тройки ``(plan_position_id, эффективные product_id,
    плановое количество)``. Позиции без артикулов или без данных о наличии
    получают три ``None``.

    Расчёт — по группе эквивалентов (#394): остатки и спрос читаются сразу
    по всем членам групп позиций, поэтому число SQL не растёт с числом
    позиций. Справочник продуктов — один SELECT на вызов (или на кэш).
    """
    product_ids: set[int] = set()
    for _position_id, effective_ids, _quantity in positions:
        product_ids.update(effective_ids)

    if not product_ids:
        return {
            position_id: PositionStockFigures(None, None, None)
            for position_id, _effective_ids, _quantity in positions
        }

    aliases = await load_alias_groups(db, product_ids)
    expanded_ids = aliases.expand(product_ids)
    free_by_product = await free_stock_by_product_ids(db, expanded_ids)
    total_demand = await committed_demand_by_product_ids(db, expanded_ids)

    result: dict[int, PositionStockFigures] = {}
    for position_id, effective_ids, required_quantity in positions:
        result[position_id] = _position_group_figures(
            aliases=aliases,
            effective_ids=effective_ids,
            required_quantity=required_quantity,
            free_by_product=free_by_product,
            total_demand=total_demand,
        )
    return result

