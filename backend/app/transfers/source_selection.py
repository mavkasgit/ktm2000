"""Автоподбор источника выдачи (#282): оракул «откуда брать материал».

Правило Q1/Q2 из #207, реализованное здесь: источник выдачи — ЛЮБОЙ
склад-хранилище, где есть материал группы эквивалентов (ADR-0073) в этом
размере, годный и с признаком операций, который маршрут позиции умеет
принять. Порядок считает система: артикул задания раньше эквивалентов,
затем ближайший назад по маршруту (этап-адресат дальше по маршруту —
склад ближе), склад вычерпывается целиком, материал без обработок идёт
последним, размер — строгое совпадение (Q7).

Что этот модуль НЕ делает:

- не двигает остатки — он только считает план (``IssuePlan``); запись
  передач и пропусков — ``app.transfers.issue_service``;
- не знает про снятые галочки как состояние — исключённые склады приходят
  параметром и живут ровно на один вызов («снятая галочка живёт, пока
  открыто окно», #282);
- не резервирует склад по участкам: «занято» остаётся по продукту
  (решение под капотом #282), гранулярность по складу — отдельный тикет.

Дефицит считается ЧЕСТНО: перебираются все кандидаты, прежде чем в
``deficit`` появится положительное число (сегодня — ровно один предыдущий
склад того же маршрута, ``limit(1)``, и отказ про нехватку после выбора).
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dimensions import (
    canonicalize_dimensions,
    dimensions_equal,
    format_dimensions,
)
from app.models.production_plan import PlanPosition
from app.models.route import RouteStage
from app.models.section import Section
from app.services.material_operations import completed_operations_through_stage
from app.services.plan_position_hanger import position_dimensions_for_task
from app.services.product_alias_groups import AliasGroups, load_alias_groups
from app.services.route_storage_classifier import SECTION_TYPE_PRODUCTION, STOCK_TYPES
from app.stock.models import QualityState, StockBalance

__all__ = [
    "IssueCandidate",
    "IssueHint",
    "IssuePlan",
    "build_issue_plan",
]

#: Признак-«заполнитель» склада без материала: candidate.take при нулевой
#: потребности — ноль, а remaining_after — прочерк (не доходила очередь).
ZERO = Decimal(0)


@dataclass(frozen=True)
class IssueCandidate:
    """Один склад-кандидат: что берём, что останется, куда выдавать."""

    balance_id: int
    location_id: int
    location_name: str
    dimensions: dict | None
    completed_operations: list[str] | None
    ops_count: int
    #: остаток на момент расчёта плана
    available: Decimal
    #: сколько возьмём (0 — склад исключён галочкой или очередь не дошла)
    take: Decimal
    #: остаток после выдачи; None — прочерк (склад не понадобился / снята
    #: галочка); 0 — склад вычерпан целиком
    remaining_after: Decimal | None
    #: включён ли в подбор (снят = «галочку убрали»)
    included: bool
    #: sequence производственного этапа-адресата (вход = признак операций)
    target_sequence: int
    #: позиция в системном порядке (0 — первый вычерпываемый)
    order: int
    #: группа эквивалентов строки (``min(product_id)``; для неразрешённой
    #: группы — сам артикул задания)
    group_key: int = 0
    #: фактический артикул строки остатка (может быть эквивалентом)
    product_id: int = 0
    #: SKU фактического артикула; None — справочник не дал SKU
    sku: str | None = None
    #: строка принадлежит артикулу задания (первый ключ порядка, ADR-0073)
    is_task_product: bool = False


@dataclass(frozen=True)
class IssueHint:
    """Подсказка оператору: «брак», «есть другой размер».

    Считается только по ВКЛЮЧЁННЫМ складам (#282): снятая галочка убирает
    склад из игры целиком — его брак и его чужой размер не аргумент.
    """

    kind: str  # "defect" | "other_size"
    location_id: int
    location_name: str
    quantity: Decimal
    dimensions: dict | None
    text: str


@dataclass(frozen=True)
class IssuePlan:
    """Результат подбора: кандидаты в системном порядке + итог + подсказки."""

    position_id: int
    product_id: int
    route_id: int
    required_dimensions: dict | None
    required: Decimal
    collected: Decimal
    deficit: Decimal
    #: ключ группы эквивалентов (``min(product_id)``); для неразрешённой
    #: группы — сам артикул задания (поведение группы из одного)
    group_key: int | None = None
    #: SKU группы по возрастанию id — подпись «A, B (эквиваленты)»
    group_skus: tuple[str, ...] = ()
    candidates: Sequence[IssueCandidate] = field(default_factory=tuple)
    hints: Sequence[IssueHint] = field(default_factory=tuple)


@dataclass(frozen=True)
class _RawCandidate:
    """Промежуточная строка подбора: остаток прошёл все фильтры."""

    balance_id: int
    location_id: int
    location_name: str
    product_id: int
    sku: str | None
    dimensions: dict | None
    completed_operations: list[str] | None
    available: Decimal
    target_sequence: int
    is_task_product: bool


async def _route_targets(
    db: AsyncSession, *, route_id: int
) -> list[tuple[int, list[str]]]:
    """Производственные этапы маршрута: ``[(sequence, вход-признак)]``.

    Тот же резолв адресата, что у ``resolve_source_issues`` (#314): складские
    и транзитные этапы пропускаются (заданий на них нет), вход этапа —
    операции маршрута до ПРЕДЫДУЩЕГО этапа включительно (материал приходит
    с признаком исходного этапа, ADR-0043/0055 п.7).
    """
    rows = (
        await db.execute(
            select(RouteStage.sequence, Section.type)
            .outerjoin(Section, Section.id == RouteStage.section_id)
            .where(RouteStage.route_id == route_id)
            .order_by(RouteStage.sequence)
        )
    ).all()
    targets: list[tuple[int, list[str]]] = []
    previous_sequence: int | None = None
    for sequence, section_type in rows:
        # Литералы типов живут в классификаторе; здесь — сравнение с его
        # константой на уже спроецированном типе (как SQL-фильтры в
        # ``transfers/queries``): тянуть ORM-Section на этап ради предиката
        # дороже, чем один ``==``.
        if section_type == SECTION_TYPE_PRODUCTION:
            inputs = await completed_operations_through_stage(
                db, route_id=route_id, through_sequence=previous_sequence or 0
            )
            targets.append((sequence, inputs))
        previous_sequence = sequence
    return targets


def _match_target(
    targets: Sequence[tuple[int, list[str]]], ops: list[str] | None
) -> int | None:
    """Этап, вход которого равен признаку операций остатка; None — не подходит."""
    if ops is None:
        return None
    normalized = sorted(ops)
    for sequence, inputs in targets:
        if inputs == normalized:
            return sequence
    return None


async def build_issue_plan(
    db: AsyncSession,
    *,
    position: PlanPosition,
    product_id: int,
    required: Decimal,
    excluded_balance_ids: Iterable[int] = (),
    selected_balance_ids: Iterable[int] | None = None,
    group_ids: Iterable[int] | None = None,
    alias_groups: AliasGroups | None = None,
) -> IssuePlan:
    """Один проход подбора: все склады-хранилища, системный порядок, дефицит.

    ``selected_balance_ids`` — legacy-форма явного выбора (``remainder_allocation``
    #314): если задан, кандидатами считаются только эти строки остатка (в
    системном порядке). ``excluded_balance_ids`` — снятые галочки окна:
    они не участвуют в вычерпывании, но остаются видны в списке (прочерк
    в колонке «остаток после»).

    Пул — группа эквивалентов (ADR-0073): остаток любого её члена годится в
    источник. ``group_ids``/``alias_groups`` — готовые члены и справочник
    (кэш одного запроса); без них группа резолвится здесь один раз на вызов,
    а не на строку баланса. Если продукт не попал в справочник, работаем как
    с группой из одного ``product_id`` — прежнее поведение не падает.
    """
    if position.route_id is None:
        raise ValueError(
            "Источник выдачи: у позиции динамический маршрут — подбор не применим"
        )

    required = Decimal(str(required))
    excluded = {int(bid) for bid in excluded_balance_ids}
    selected = None if selected_balance_ids is None else {int(b) for b in selected_balance_ids}

    if alias_groups is None:
        alias_groups = await load_alias_groups(db, {product_id})
    group = alias_groups.group_for(product_id)
    if group_ids is not None:
        members = tuple(sorted({int(gid) for gid in group_ids}))
    elif group is not None:
        members = group.product_ids
    else:
        members = (int(product_id),)
    if not members:
        members = (int(product_id),)
    member_set = set(members)
    group_key = group.key if group is not None else int(product_id)
    group_skus = group.skus if group is not None else ()
    sku_by_id = (
        dict(zip(group.product_ids, group.skus)) if group is not None else {}
    )

    targets = await _route_targets(db, route_id=position.route_id)
    required_dims = canonicalize_dimensions(position_dimensions_for_task(position))

    stock_locations = (
        await db.execute(
            select(Section.id, Section.name).where(Section.type.in_(STOCK_TYPES))
        )
    ).all()
    location_names = dict(stock_locations)
    if not location_names:
        return IssuePlan(
            position_id=position.id,
            product_id=product_id,
            route_id=position.route_id,
            required_dimensions=required_dims,
            required=required,
            collected=ZERO,
            deficit=required,
            group_key=group_key,
            group_skus=group_skus,
        )

    # Подбор и подсказки — по всем качествам одной группы (товар, склад):
    # источники — только GOOD (брак НЕ является источником, #282), а
    # подсказка «на Хранилище Б 20 шт. браком» считается именно по
    # бракованным строкам, которые GOOD-фильтр сюда бы не пустил.
    balances = (
        await db.execute(
            select(StockBalance).where(
                StockBalance.product_id.in_(members),
                StockBalance.location_id.in_(location_names.keys()),
                StockBalance.balance_qty > 0,
            )
        )
    ).scalars().all()

    # Кандидаты: годный остаток, строгий размер (Q7), признак операций
    # зафиксирован и встречается на маршруте, склад не исключён явным
    # списком selected.
    raw_candidates: list[_RawCandidate] = []
    for balance in balances:
        if balance.quality_state != QualityState.GOOD:
            continue
        if selected is not None and balance.id not in selected:
            continue
        if not dimensions_equal(balance.dimensions, required_dims):
            continue
        target_sequence = _match_target(targets, balance.completed_operations)
        if target_sequence is None:
            continue
        raw_candidates.append(
            _RawCandidate(
                balance_id=balance.id,
                location_id=balance.location_id,
                location_name=location_names[balance.location_id],
                product_id=balance.product_id,
                sku=sku_by_id.get(balance.product_id),
                dimensions=balance.dimensions,
                completed_operations=balance.completed_operations,
                available=Decimal(balance.balance_qty),
                target_sequence=target_sequence,
                is_task_product=balance.product_id == product_id,
            )
        )

    # Legacy-форма явного выбора: отказ на неподходящем остатке — тот же,
    # что давал ``resolve_source_issues`` (#314/#55), а не тихий пропуск:
    # оператор указал склад руками, молчание хуже отказа. Название склада
    # вместо ``#id`` — отказ читается по-русски и без цифровых id (#282).
    # Проверка артикула — по группе: эквивалент законен, чужой — нет.
    if selected is not None:
        chosen = {c.balance_id for c in raw_candidates}
        for balance_id in sorted(selected - chosen):
            balance = await db.get(StockBalance, balance_id)
            if balance is None:
                raise ValueError("Источник выдачи: выбранный складской остаток не найден")
            location = location_names.get(balance.location_id, "")
            label = f"«{location}»"
            if balance.product_id not in member_set:
                raise ValueError(
                    f"Источник выдачи: материал на {label} — не из группы эквивалентов"
                )
            if balance.completed_operations is None:
                raise ValueError(
                    f"Источник выдачи: на {label} состояние операций "
                    "не зафиксировано — списать этот материал на данный маршрут нельзя"
                )
            if Decimal(balance.balance_qty) <= 0:
                raise ValueError(f"Источник выдачи: на {label} материал закончился")
            if not dimensions_equal(balance.dimensions, required_dims):
                raise ValueError(
                    f"Источник выдачи: на {label} лежит "
                    f"{format_dimensions(balance.dimensions)}, нужен "
                    f"{format_dimensions(required_dims)}"
                )
            raise ValueError(
                f"Источник выдачи: материал на {label} (пройдено: "
                f"{', '.join(sorted(balance.completed_operations))}) "
                "не подходит маршруту позиции"
            )

    # Системный порядок: артикул задания — всегда первым (даже если
    # эквивалент ближе по маршруту), затем ближайший назад по маршруту,
    # материал без обработок последним; ничья — по id склада, чтобы
    # предвыбор не зависел от порядка строк в ответе (ADR-0073 §5).
    raw_candidates.sort(
        key=lambda c: (
            not c.is_task_product,
            -c.target_sequence,
            -len(c.completed_operations or []),
            c.location_id,
            c.balance_id,
        )
    )

    candidates: list[IssueCandidate] = []
    remaining = required
    collected = ZERO
    for order, raw in enumerate(raw_candidates):
        # «included» — состояние галочки, а не факт вычерпывания: склад,
        # до которого очередь не дошла (потребность закрыта раньше), остаётся
        # включённым и видимым отмеченным (#282: подсказки и снятие галочки
        # живут по включённым складам). Очередь решает только `take`.
        included = selected is not None or raw.balance_id not in excluded
        take = min(remaining, raw.available) if included and remaining > 0 else ZERO
        if take > 0:
            remaining -= take
            collected += take
        # «Остаток после»: 0 — склад вычерпан целиком; None — прочерк
        # (галочка снята или очередь до склада не дошла).
        remaining_after = raw.available - take if included and take > 0 else None
        candidates.append(
            IssueCandidate(
                balance_id=raw.balance_id,
                location_id=raw.location_id,
                location_name=raw.location_name,
                dimensions=raw.dimensions,
                completed_operations=raw.completed_operations,
                ops_count=len(raw.completed_operations or []),
                available=raw.available,
                take=take,
                remaining_after=remaining_after,
                included=included,
                target_sequence=raw.target_sequence,
                order=order,
                group_key=group_key,
                product_id=raw.product_id,
                sku=raw.sku,
                is_task_product=raw.is_task_product,
            )
        )
    # Снятый галочкой склад остаётся в списке (оператор видит, что снял),
    # исключённые потребностью — тоже; у обоих «остаток после» — прочерк.
    for balance_id in excluded:
        if any(c.balance_id == balance_id for c in candidates):
            continue
        balance = await db.get(StockBalance, balance_id)
        if balance is None or balance.product_id not in member_set:
            continue
        target_sequence = _match_target(targets, balance.completed_operations)
        if target_sequence is None:
            continue
        candidates.append(
            IssueCandidate(
                balance_id=balance.id,
                location_id=balance.location_id,
                location_name=location_names.get(balance.location_id, ""),
                dimensions=balance.dimensions,
                completed_operations=balance.completed_operations,
                ops_count=len(balance.completed_operations or []),
                available=Decimal(balance.balance_qty),
                take=ZERO,
                remaining_after=None,
                included=False,
                target_sequence=target_sequence,
                order=len(candidates),
                group_key=group_key,
                product_id=balance.product_id,
                sku=sku_by_id.get(balance.product_id),
                is_task_product=balance.product_id == product_id,
            )
        )

    hints = _build_hints(
        balances=balances,
        candidates=candidates,
        location_names=location_names,
        required_dims=required_dims,
    )

    return IssuePlan(
        position_id=position.id,
        product_id=product_id,
        route_id=position.route_id,
        required_dimensions=required_dims,
        required=required,
        collected=collected,
        deficit=max(ZERO, required - collected),
        group_key=group_key,
        group_skus=group_skus,
        candidates=tuple(candidates),
        hints=hints,
    )


_DEFECT_QUALITIES = {QualityState.SCRAP, QualityState.FINAL_SCRAP}


def _build_hints(
    *,
    balances: Iterable[StockBalance],
    candidates: Sequence[IssueCandidate],
    location_names: dict[int, str],
    required_dims: dict | None,
) -> list[IssueHint]:
    """Подсказки только по включённым складам: «брак», «есть другой размер»."""
    included_location_ids = {c.location_id for c in candidates if c.included}
    if not included_location_ids:
        return []

    defect_by_location: dict[int, Decimal] = {}
    other_size_by_location: dict[tuple[int, dict | None], Decimal] = {}
    for balance in balances:
        if balance.location_id not in included_location_ids:
            continue
        qty = Decimal(balance.balance_qty)
        if qty <= 0:
            continue
        if balance.quality_state in _DEFECT_QUALITIES:
            defect_by_location[balance.location_id] = (
                defect_by_location.get(balance.location_id, ZERO) + qty
            )
            continue
        # Годный другого размера — это «есть 3,00 м, нужен 2,75 м»; размер
        # безразмерной позиции не с чем сравнивать (подсказки нет).
        if required_dims is None or dimensions_equal(balance.dimensions, required_dims):
            continue
        key = (balance.location_id, tuple(sorted((balance.dimensions or {}).items())))
        other_size_by_location[key] = other_size_by_location.get(key, ZERO) + qty

    hints: list[IssueHint] = []
    for location_id, qty in sorted(defect_by_location.items()):
        name = location_names.get(location_id, "")
        hints.append(
            IssueHint(
                kind="defect",
                location_id=location_id,
                location_name=name,
                quantity=qty,
                dimensions=None,
                text=f"на {name} {int(qty)} шт. браком",
            )
        )
    for (location_id, dims_items), qty in sorted(other_size_by_location.items()):
        name = location_names.get(location_id, "")
        dims = dict(dims_items)
        required_label = format_dimensions(required_dims)
        hints.append(
            IssueHint(
                kind="other_size",
                location_id=location_id,
                location_name=name,
                quantity=qty,
                dimensions=dims,
                text=f"на {name} есть {format_dimensions(dims)}, нужен {required_label}",
            )
        )
    return hints
