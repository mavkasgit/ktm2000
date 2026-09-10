"""Эквивалентные тесты межстрочного кэша подбора маршрута (#163).

Кэш-путь обязан давать те же наблюдаемые результаты, что и бескэшный:
- select_route_for_payload(..., batch_cache=...) == без кэша;
- build_route_from_profile(..., batch=...) == без кэша (+ мемоизация built_routes);
- resolve_pair_n(..., length_candidates_mm=...) == без кандидатов (старый SQL-путь).
"""
from __future__ import annotations

import pytest

from app.models.product import Product, ProductLength, ProductPair, ProductType
from app.models.route import (
    ProductionRoute,
    RouteRuleProfile,
    RouteSelectionRule,
    RouteStage,
    SectionOperation,
)
from app.models.section import Section
from app.services.product_pair_resolver import (
    ResolvedPair,
    pair_length_candidates_mm,
    resolve_pair_n,
)
from app.services.route_builder import build_route_from_profile, load_route_build_batch_cache
from app.services.route_selection import load_route_selection_batch_cache, select_route_for_payload

R1_NAME = "Маршрут 163 пресс"
R2_NAME = "Маршрут 163 упаковка"


class _Seed163:
    def __init__(self) -> None:
        self.sections: dict[str, Section] = {}
        self.profile: RouteRuleProfile | None = None
        self.product: Product | None = None
        self.r1: ProductionRoute | None = None
        self.r2: ProductionRoute | None = None


async def _seed_163(session) -> _Seed163:
    """Минимальный сид: 4 Section, 2 маршрута, профиль с route_select /
    resolve_operations / resolve_signatures правилами, 1 продукт."""
    seed = _Seed163()
    for code, name, order in [
        ("PRESSING", "Пресс", 10),
        ("PACKING", "Упаковка", 20),
        ("FINISHED_STOCK", "Склад ГП", 30),
        ("DRILLING", "Сверловка", 40),
    ]:
        section = Section(code=code, name=name, sort_order=order, type="production", is_active=True)
        session.add(section)
        await session.flush()
        seed.sections[code] = section

    def _op(section_code: str, op: str, name: str, group: str, group_name: str, order: int) -> None:
        session.add(
            SectionOperation(
                section_id=seed.sections[section_code].id,
                operation_code=op,
                operation_name=name,
                group_code=group,
                group_name=group_name,
                sort_order=order,
                is_significant=True,
                operation_type="production",
            )
        )

    _op("PRESSING", "PRESS_WINDOW", "Окно", "PRESS", "Пресс", 10)
    _op("PRESSING", "PRESS_RED", "Красный", "PRESS", "Пресс", 20)
    _op("PRESSING", "PRESS_BLUE", "Синий", "PRESS", "Пресс", 30)
    _op("PACKING", "PACK_BOX", "Коробка", "PACK", "Упаковка", 10)
    _op("FINISHED_STOCK", "RECEIVE_FG", "Приёмка", "FG", "Приёмка", 10)
    await session.flush()

    profile = RouteRuleProfile(
        code="batch163",
        name="Профиль 163",
        is_active=True,
        priority=10,
        route_sections=["PRESSING", "PACKING", "FINISHED_STOCK"],
    )
    session.add(profile)
    await session.flush()
    seed.profile = profile
    sid = {code: s.id for code, s in seed.sections.items()}

    rules = [
        # route_select: require/exclude
        ("need_press", 900, "route_select",
         [{"source": "payload", "field_path": "operation", "operator": "contains",
           "value": "пресс", "case_sensitive": False}],
         [{"action": "require_section", "section_id": sid["PRESSING"]}]),
        ("need_drill", 900, "route_select",
         [{"source": "payload", "field_path": "operation", "operator": "contains",
           "value": "сверл", "case_sensitive": False}],
         [{"action": "require_section", "section_id": sid["DRILLING"]}]),
        ("pack_gp", 700, "route_select",
         [{"source": "payload", "field_path": "output_kind", "operator": "contains", "value": "ГП"}],
         [{"action": "require_section", "section_id": sid["PACKING"]}]),
        ("pf_no_press_pack", 700, "route_select",
         [{"source": "payload", "field_path": "output_kind", "operator": "contains", "value": "П/Ф"}],
         [{"action": "exclude_section", "section_id": sid["PRESSING"]},
          {"action": "exclude_section", "section_id": sid["PACKING"]}]),
        # resolve_operations: set_operation + mapping по цвету
        ("press_default_op", 200, "resolve_operations",
         [{"source": "payload", "field_path": "operation", "operator": "not_empty", "value": None}],
         [{"action": "set_operation", "section_code": "PRESSING",
           "group_code": "PRESS", "operation_code": "PRESS_WINDOW"}]),
        ("color_press_op", 100, "resolve_operations",
         [{"source": "payload", "field_path": "color", "operator": "not_empty", "value": None}],
         [{"action": "set_operation_by_mapping", "section_code": "PRESSING",
           "group_code": "PRESS", "lookup_field": "color",
           "mapping": [{"keyword": "красн", "operation_code": "PRESS_RED"},
                       {"keyword": "син", "operation_code": "PRESS_BLUE"}]}]),
        # resolve_signatures: set_field в payload
        ("sig_shot", 100, "resolve_signatures",
         [{"source": "payload", "field_path": "operation", "operator": "contains",
           "value": "пресс", "case_sensitive": False}],
         [{"action": "set_field", "path": "payload.shot_op", "value": "дробеструй"}]),
    ]
    for code, prio, phase, conditions, actions in rules:
        session.add(
            RouteSelectionRule(
                code=f"b163_{code}", name=code, profile_id=profile.id,
                priority=prio, is_active=True, phase=phase,
                conditions=conditions, actions=actions,
            )
        )
    await session.flush()

    async def _route(name: str, sort: int, section_codes: list[str]) -> ProductionRoute:
        route = ProductionRoute(name=name, code=f"b163_{sort}", is_active=True, sort_order=sort)
        session.add(route)
        await session.flush()
        for seq, scode in enumerate(section_codes, start=1):
            session.add(RouteStage(route_id=route.id, sequence=seq, section_id=seed.sections[scode].id))
        await session.flush()
        return route

    seed.r1 = await _route(R1_NAME, 10, ["PRESSING", "PACKING", "FINISHED_STOCK"])
    seed.r2 = await _route(R2_NAME, 20, ["PACKING", "FINISHED_STOCK"])

    seed.product = Product(sku="B163-MAIN", name="Продукт 163", type=ProductType.finished_good, unit="pcs")
    session.add(seed.product)
    await session.flush()
    return seed


def _sel_key(result) -> tuple:
    return (
        result.route.id if result.route is not None else None,
        list(result.required_section_ids),
        list(result.excluded_section_ids),
        list(result.matched_rule_ids),
        result.error,
        result.route_match_reason,
    )


def _steps_key(built) -> tuple:
    return tuple(
        (s.sequence, s.section_code, s.operation_code, s.operation_name, s.stage_kind, s.is_final)
        for s in built.steps
    )


# ─── a. select: кэш == бескэшный путь ─────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expect_reason", "expect_route"),
    [
        ({"operation": "прессовка окон", "output_kind": "ГП", "color": ""}, "selection_rules", R1_NAME),
        ({"operation": "", "output_kind": "ГП", "color": ""}, "selection_rules", R2_NAME),
        ({"operation": "сверловка", "output_kind": "ГП", "color": ""}, "no_route_candidate", None),
        ({"operation": "прессовка", "output_kind": "П/Ф", "color": ""}, "route_rule_conflict", None),
    ],
    ids=["match_r1", "match_r2", "no_candidate", "conflict"],
)
async def test_select_cache_equivalence_163(session, payload, expect_reason, expect_route) -> None:
    """Подбор с batch_cache даёт тот же маршрут/наборы/диагностику, что без него."""
    seed = await _seed_163(session)
    batch = await load_route_selection_batch_cache(session, seed.profile.id)

    plain = await select_route_for_payload(
        session, dict(payload), product=seed.product, profile_id=seed.profile.id)
    cached = await select_route_for_payload(
        session, dict(payload), product=seed.product,
        profile_id=seed.profile.id, batch_cache=batch)

    assert _sel_key(cached) == _sel_key(plain)
    assert cached.route_match_reason == expect_reason
    assert (cached.route.name if cached.route is not None else None) == expect_route


# ─── b. select видит маршрут, созданный внутри батча ──────────────────────────


@pytest.mark.asyncio
async def test_select_sees_route_created_inside_batch_163(session) -> None:
    """Miss → новый ProductionRoute + register_created_route → повторный select его видит."""
    seed = await _seed_163(session)
    batch = await load_route_selection_batch_cache(session, seed.profile.id)
    payload = {"operation": "сверловка", "output_kind": "ГП", "color": ""}

    miss = await select_route_for_payload(
        session, dict(payload), product=seed.product,
        profile_id=seed.profile.id, batch_cache=batch)
    assert miss.route is None and miss.error == "no_route_candidate"

    new_route = ProductionRoute(name="Маршрут 163 сверловка", code="b163_drill", is_active=True, sort_order=5)
    session.add(new_route)
    await session.flush()
    wanted = ["DRILLING", "PACKING", "FINISHED_STOCK"]
    for seq, scode in enumerate(wanted, start=1):
        session.add(RouteStage(route_id=new_route.id, sequence=seq, section_id=seed.sections[scode].id))
    await session.flush()
    batch.register_created_route(
        new_route, [(seed.sections[c].id, c) for c in wanted])

    hit = await select_route_for_payload(
        session, dict(payload), product=seed.product,
        profile_id=seed.profile.id, batch_cache=batch)
    assert hit.route is not None and hit.route.id == new_route.id


# ─── c. build: кэш == бескэшный путь (результат + мутации payload) ────────────


@pytest.mark.asyncio
async def test_build_cache_equivalence_163(session) -> None:
    """Сборка с batch и без: равны name/error/steps и мутации payload."""
    seed = await _seed_163(session)
    sel_cache = await load_route_selection_batch_cache(session, seed.profile.id)
    batch = await load_route_build_batch_cache(session, seed.profile, selection_cache=sel_cache)
    payload = {"operation": "прессовка окон", "output_kind": "ГП", "color": "красный", "quantity": 3}

    pay_cached, pay_plain = dict(payload), dict(payload)
    built_cached = await build_route_from_profile(
        session, seed.profile, source_payload=pay_cached, product=seed.product, batch=batch)
    built_plain = await build_route_from_profile(
        session, seed.profile, source_payload=pay_plain, product=seed.product)

    assert built_cached.error is None, built_cached.error
    assert built_cached.error == built_plain.error
    assert built_cached.name == built_plain.name
    assert _steps_key(built_cached) == _steps_key(built_plain)
    # Мутации payload (resolve_signatures пишет shot_op) одинаковы в обоих путях.
    assert pay_cached == pay_plain
    assert pay_cached.get("shot_op") == "дробеструй"


# ─── d. build: мемоизация — hit по quantity, miss по цвету ────────────────────


@pytest.mark.asyncio
async def test_build_memo_hit_and_miss_163(session) -> None:
    """Одинаковая сигнатура + разный quantity → одна запись; цвет меняет
    resolved_ops → разные записи."""
    seed = await _seed_163(session)
    batch = await load_route_build_batch_cache(session, seed.profile)

    base = {"operation": "прессовка", "output_kind": "ГП", "color": "красный"}
    first = await build_route_from_profile(
        session, seed.profile, source_payload={**base, "quantity": 1},
        product=seed.product, batch=batch)
    second = await build_route_from_profile(
        session, seed.profile, source_payload={**base, "quantity": 999},
        product=seed.product, batch=batch)
    assert second is first
    assert len(batch.built_routes) == 1

    other_color = await build_route_from_profile(
        session, seed.profile, source_payload={**base, "color": "синий", "quantity": 1},
        product=seed.product, batch=batch)
    assert other_color is not first
    assert len(batch.built_routes) == 2
    ops_first = [(s.section_code, s.operation_code) for s in first.steps]
    ops_other = [(s.section_code, s.operation_code) for s in other_color.steps]
    assert ops_first != ops_other


# ─── e. pair_n: кандидаты == старый SQL-путь ──────────────────────────────────


@pytest.mark.asyncio
async def test_pair_n_candidates_equivalence_163(session) -> None:
    """resolve_pair_n с предзагруженными кандидатами равен вызову без них —
    и в manual-ветке, и в calc_error-ветке вне пересечения."""
    prod_a = Product(sku="B163-A", name="A 163", type=ProductType.component, unit="шт")
    prod_b = Product(sku="B163-B", name="B 163", type=ProductType.component, unit="шт")
    session.add_all([prod_a, prod_b])
    await session.flush()
    session.add_all([
        ProductLength(product_id=prod_a.id, length_mm=2700),
        ProductLength(product_id=prod_a.id, length_mm=2800),
        ProductLength(product_id=prod_b.id, length_mm=2700),
        ProductLength(product_id=prod_b.id, length_mm=2900),
    ])
    pair = ProductPair(
        product_a_id=min(prod_a.id, prod_b.id), product_b_id=max(prod_a.id, prod_b.id),
        quantity_per_hanger={"2700": {"auto": None, "manual": 8}},
    )
    session.add(pair)
    await session.flush()
    resolved = ResolvedPair(pair=pair, product_a=prod_a, product_b=prod_b)

    candidates = await pair_length_candidates_mm(session, resolved)
    assert candidates == [2700.0]

    def _key(value) -> tuple:
        return (value.quantity_per_hanger, value.source, value.calc_error)

    manual_plain = await resolve_pair_n(session, resolved, length_mm=2700.0)
    manual_cached = await resolve_pair_n(session, resolved, length_mm=2700.0, length_candidates_mm=candidates)
    assert _key(manual_cached) == _key(manual_plain) == (8, "manual", False)

    # Длина вне пересечения (2800 есть только у A) → calc_error в обоих путях.
    err_plain = await resolve_pair_n(session, resolved, length_mm=2800.0)
    err_cached = await resolve_pair_n(session, resolved, length_mm=2800.0, length_candidates_mm=candidates)
    assert err_plain.calc_error and err_cached.calc_error
    assert _key(err_cached) == _key(err_plain)


# ─── f. batch чужого профиля игнорируется ─────────────────────────────────────


@pytest.mark.asyncio
async def test_foreign_profile_batch_cache_ignored_163(session) -> None:
    """select с batch чужого profile_id совпадает с бескэшным подбором."""
    seed = await _seed_163(session)
    foreign = RouteRuleProfile(
        code="batch163-foreign", name="Чужой профиль", is_active=True,
        priority=1, route_sections=[],
    )
    session.add(foreign)
    await session.flush()
    foreign_batch = await load_route_selection_batch_cache(session, foreign.id)

    payload = {"operation": "прессовка окон", "output_kind": "ГП", "color": ""}
    plain = await select_route_for_payload(
        session, dict(payload), product=seed.product, profile_id=seed.profile.id)
    with_foreign = await select_route_for_payload(
        session, dict(payload), product=seed.product,
        profile_id=seed.profile.id, batch_cache=foreign_batch)
    assert _sel_key(with_foreign) == _sel_key(plain)
