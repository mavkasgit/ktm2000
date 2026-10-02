"""Эквивалентность батч-резолва маршрутов поштучному (#292).

Батч-форма — expand: она обязана отдавать ровно то же, что отдаёт
``resolve_position_route`` на каждой позиции по отдельности, во всех
ветках (ручное подтверждение, сохранённое назначение, архивный и
отсутствующий маршрут, динамическая пересборка с её fallback'ами и
конфликтом сигнатуры, подбор по правилам). Плюс проверки смысла самой
правки: нормализованный ключ идентичности и кэш продуктов, который не
стоит запроса на повторной позиции.
"""

from __future__ import annotations

import json

import pytest
from app.models.product import Product, ProductPair, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionRouteOrigin,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import (
    ProductionRoute,
    RouteRuleProfile,
    RouteSelectionRule,
    RouteStage,
)
from app.models.section import Section
from app.services.position_route_batch import (
    BRANCH_DYNAMIC,
    BRANCH_MANUAL,
    BRANCH_SELECTION,
    BRANCH_STORED,
    position_route_identity_key,
    resolve_position_routes_batch,
)
from app.services.product_pair_resolver import (
    PairResolutionCache,
    resolve_effective_product_ids,
)
from app.services.route_builder import build_route_from_profile
from app.services.route_matcher import (
    _payload_for_dynamic_build,
    resolve_position_route,
)
from app.services.route_signature import auto_route_code
from sqlalchemy import event, select


def _position(plan_id: int, **kwargs) -> PlanPosition:
    """Позиция плана: у резолва нет запроса к самому плану, но строка нужна для id."""
    fields = {
        "production_plan_id": plan_id,
        "product_id": None,
        "source_type": PlanSourceType.excel_import,
        "source_sku": "ХТ-292-0001",
        "quantity": 1,
        "status": PlanPositionStatus.draft,
        "validation_status": PlanPositionValidationStatus.pending,
        "validation_errors": [],
    }
    fields.update(kwargs)
    return PlanPosition(**fields)


def _info_key(info) -> tuple:
    """Всё наблюдаемое в ответе резолва — без ссылки на сам объект."""
    return (
        info.route_id,
        info.route_name,
        info.source,
        info.route_origin,
        info.route_match_quality,
        info.route_match_reason,
        info.route_assigned_at,
        info.route_manual_confirmed_at,
        info.error,
        tuple(info.checked_rules or ()),
        tuple(info.required_sections or ()),
        tuple(info.excluded_sections or ()),
        tuple(
            (c.route_id, c.route_name, tuple(c.section_codes), c.matched)
            for c in (info.candidate_routes or ())
        ),
        info.selected_route_id,
        json.dumps(info.condition_diagnostics, sort_keys=True, default=str),
    )


async def _make_plan(session, suffix: str) -> int:
    """План-владелец позиций: его id позиции цитируют как внешний ключ."""
    plan = ProductionPlan(
        plan_no=f"PLAN-292-{suffix}",
        name=f"План 292 {suffix}",
        status=ProductionPlanStatus.draft,
    )
    session.add(plan)
    await session.flush()
    return plan.id


async def _seed_profile(session) -> int:
    """Профиль с правилами и участки — как в тестах динамической генерации."""
    from tests.test_dynamic_route_generation import (
        _make_profile_with_rules,
        _seed_sections,
    )

    await _seed_sections(session)
    return await _make_profile_with_rules(session)


async def _build(session, position: PlanPosition):
    profile = await session.get(RouteRuleProfile, position.route_profile_id)
    assert profile is not None
    return await build_route_from_profile(
        session, profile, _payload_for_dynamic_build(position), position
    )


def _count_sql(session):
    """Счётчик SQL на время блока с ``try/finally`` — по образцу test_transfers_ready."""
    counter = {"n": 0}
    sync_engine = session.bind.sync_engine

    def _count(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(sync_engine, "before_cursor_execute", _count)
    return counter, lambda: event.remove(sync_engine, "before_cursor_execute", _count)


@pytest.mark.asyncio
async def test_batch_matches_per_row_on_all_branches(session) -> None:
    """Батч равен поштучному резолву на наборе из всех ветвей сразу.

    Список подобран так, чтобы одна проверка накрыла то, что тикет называет
    «семантику не менять»: ручное подтверждение, сохранённое назначение,
    архивный маршрут, динамическая пересборка с fallback'ом на сохранённое
    назначение, подбор по правилам.
    """
    profile_id = await _seed_profile(session)
    plan_id = await _make_plan(session, "branches")
    stored = ProductionRoute(name="Сохранённый 292", is_active=True)
    archived = ProductionRoute(name="Архивный 292", is_active=False)
    session.add_all([stored, archived])
    await session.flush()

    positions = [
        # ручное подтверждение: сохранённый маршрут берётся как есть
        _position(
            plan_id,
            source_payload={"operation": "упаковка"},
            route_id=stored.id,
            route_origin=PlanPositionRouteOrigin.manual_confirmed,
        ),
        # архивный маршрут — отзыв назначения, а не назначение
        _position(
            plan_id,
            source_payload={"operation": "упаковка"},
            route_id=archived.id,
            route_origin=PlanPositionRouteOrigin.auto,
        ),
        # ни назначения, ни профиля: подбор по правилам
        _position(plan_id, source_payload={"operation": "упаковка", "output_kind": "ГП"}),
        # профиль + пересборка, имя которой в базе нет: fallback на сохранённое
        _position(
            plan_id,
            source_payload={
                "output_kind": "П/Ф",
                "source_name": "РП-АКТ-03 2,7 м анодчерный матов",
            },
            route_id=stored.id,
            route_profile_id=profile_id,
            route_origin=PlanPositionRouteOrigin.auto,
        ),
    ]
    session.add_all(positions)
    await session.flush()

    per_row = {p.id: await resolve_position_route(session, p) for p in positions}
    batch = await resolve_position_routes_batch(session, positions)

    assert set(batch) == {p.id for p in positions}
    for position in positions:
        assert _info_key(batch[position.id]) == _info_key(per_row[position.id]), (
            f"позиция {position.id}: батч разошёлся с поштучным резолвом"
        )

    # Ветки в наборе действительно разные — иначе проверка ничего не накрыла бы.
    assert per_row[positions[0].id].source == "manual"
    assert per_row[positions[1].id].error == "route_not_found"
    assert per_row[positions[2].id].source == "auto"
    assert per_row[positions[3].id].source == "dynamic_build"
    assert per_row[positions[3].id].route_id == stored.id


@pytest.mark.asyncio
async def test_batch_reports_missing_stored_route_like_per_row(session) -> None:
    """Сохранённый ``route_id``, которого в базе нет, — тот же отказ, что и поштучно.

    Позицию с таким ``route_id`` нельзя сохранить (внешний ключ), поэтому она
    остаётся в памяти — ровно как в тестах fallback-ветки. Отдельно от общего
    набора: проверяет ветку «маршрут удалён», которую FK не даёт положить в базу.
    """
    plan_id = await _make_plan(session, "missing")
    stored = ProductionRoute(name="Будет удалён 292", is_active=True)
    session.add(stored)
    await session.flush()
    gone = stored.id
    await session.delete(stored)
    await session.flush()

    position = _position(
        plan_id,
        source_payload={"operation": "упаковка"},
        route_id=gone,
        route_origin=PlanPositionRouteOrigin.auto,
    )

    per_row = await resolve_position_route(session, position)
    (batched,) = (await resolve_position_routes_batch(session, [position])).values()

    assert per_row.error == "route_not_found"
    assert _info_key(batched) == _info_key(per_row)


@pytest.mark.asyncio
async def test_batch_keeps_signature_conflict_and_legacy_name_fallback(session) -> None:
    """Батч не теряет ни сверку сигнатуры, ни fallback по имени без кода.

    Оба случая — про маршруты, найденные по пересобранному имени: сначала
    по ``auto-``-коду (ADR-0051 п. 4), затем по имени среди строк без кода
    (ADR-0051 п. 6). Снимок батча ищет их в памяти, и именно тут легко
    выдать чужой маршрут за свой — тест фиксирует оба вердикта.
    """
    profile_id = await _seed_profile(session)
    plan_id = await _make_plan(session, "identity")

    conflict = _position(
        plan_id,
        source_payload={"output_kind": "П/Ф", "source_name": "РП-АКТ-03 2,7 м анодчерный матов"},
        route_profile_id=profile_id,
        route_origin=PlanPositionRouteOrigin.auto,
    )
    legacy = _position(
        plan_id,
        source_payload={"output_kind": "ГП", "source_name": "РП-АКТ-03"},
        route_profile_id=profile_id,
        route_origin=PlanPositionRouteOrigin.auto,
    )
    session.add_all([conflict, legacy])
    await session.flush()

    built_conflict = await _build(session, conflict)
    code = auto_route_code(built_conflict.signature)
    assert code is not None, "предусловие: у пересборки есть сигнатура и код"
    packing = await session.scalar(select(Section).where(Section.code == "PACKING"))
    edited = ProductionRoute(name=built_conflict.name, code=code, is_active=True)
    session.add(edited)
    await session.flush()
    # Состав в базе — один участок, сохранённой сигнатуры нет: ровно то, что
    # даёт правка маршрута руками (ADR-0051 п. 4).
    session.add(
        RouteStage(route_id=edited.id, sequence=1, section_id=packing.id, is_final=True)
    )

    built_legacy = await _build(session, legacy)
    older = ProductionRoute(name=built_legacy.name, code=None, is_active=True)
    session.add(older)
    await session.flush()
    newer = ProductionRoute(name=built_legacy.name, code=None, is_active=True)
    session.add(newer)
    await session.flush()
    assert newer.id > older.id

    positions = [conflict, legacy]
    per_row = {p.id: await resolve_position_route(session, p) for p in positions}
    batch = await resolve_position_routes_batch(session, positions)

    assert per_row[conflict.id].error == "route_signature_conflict"
    assert batch[conflict.id].error == "route_signature_conflict"
    assert batch[conflict.id].route_id is None
    assert per_row[legacy.id].route_id == older.id
    assert batch[legacy.id].route_id == older.id


@pytest.mark.asyncio
async def test_batch_selection_branch_keeps_reasons_and_diagnostics(session) -> None:
    """Ветка подбора: батч не меняет ни маршрут, ни причину, ни диагностику.

    Здесь ключ идентичности остаётся полным (условия правил адресуют
    произвольные поля payload), и сверяется диагностика условий: это самая
    «шумная» часть ответа, и потерять её молча хуже лишнего запроса.
    """
    from tests.test_dynamic_route_generation import _seed_sections

    await _seed_sections(session)
    plan_id = await _make_plan(session, "selection")
    packing = await session.scalar(select(Section).where(Section.code == "PACKING"))
    raw = await session.scalar(select(Section).where(Section.code == "RAW_STOCK"))
    # Глобальное правило (profile_id=None): подбор на ветке позиции без
    # батча импорта читает именно глобальные правила, и без него проверка
    # была бы пустой — правила не применились бы вовсе.
    session.add(
        RouteSelectionRule(
            code="global_packing_292",
            name="Требуется упаковка",
            profile_id=None,
            priority=900,
            is_active=True,
            phase="route_select",
            conditions=[],
            actions=[{"action": "require_section", "section_code": "PACKING"}],
        )
    )
    with_packing = ProductionRoute(name="Маршрут 292 с упаковкой", is_active=True, sort_order=10)
    without = ProductionRoute(name="Маршрут 292 без упаковки", is_active=True, sort_order=20)
    session.add_all([with_packing, without])
    await session.flush()
    session.add(RouteStage(route_id=with_packing.id, sequence=1, section_id=packing.id))
    session.add(RouteStage(route_id=without.id, sequence=1, section_id=raw.id))
    await session.flush()

    payloads = (
        {"operation": "", "output_kind": "ГП", "color": "черный"},
        {"operation": "", "output_kind": "П/Ф", "color": "серебро"},
    )
    positions = [_position(plan_id, source_payload=payload) for payload in payloads]
    session.add_all(positions)
    await session.flush()

    per_row = {p.id: await resolve_position_route(session, p) for p in positions}
    batch = await resolve_position_routes_batch(session, positions)

    assert [per_row[p.id].route_match_reason for p in positions] == ["selection_rules"] * 2
    assert [per_row[p.id].route_id for p in positions] == [with_packing.id] * 2
    for position in positions:
        assert _info_key(batch[position.id]) == _info_key(per_row[position.id])
        assert batch[position.id].required_sections, "правила профиля не применились"

    # Тот же список без маршрутов: ветка «кандидата нет» — тоже совпадение.
    for stage in (await session.execute(select(RouteStage))).scalars().all():
        await session.delete(stage)
    await session.flush()
    for route in (with_packing, without):
        await session.delete(route)
    await session.flush()

    per_row_empty = {p.id: await resolve_position_route(session, p) for p in positions}
    batch_empty = await resolve_position_routes_batch(session, positions)
    assert [per_row_empty[p.id].route_match_reason for p in positions] == [
        "no_route_candidate"
    ] * 2
    for position in positions:
        assert _info_key(batch_empty[position.id]) == _info_key(per_row_empty[position.id])


@pytest.mark.asyncio
async def test_identity_key_collapses_payload_noise_on_stored_branch(session) -> None:
    """На ветке сохранённого назначения payload в ключ не входит.

    Ровно то, за что тикет ругает ``make_position_route_cache_key``: тот
    ключ включает весь ``source_payload``, поэтому две позиции одного
    маршрута, отличающиеся сырыми колонками Excel, считались разными и
    резолвились по отдельности. Здесь они дают один ключ.
    """
    plan_id = await _make_plan(session, "identity-key")
    noisy = _position(
        plan_id,
        source_payload={"raw_columns": {"A": "1", "B": "2"}, "operation": "упаковка"},
        route_id=42,
        route_origin=PlanPositionRouteOrigin.manual_confirmed,
    )
    clean = _position(
        plan_id,
        source_payload={"raw_columns": {"A": "9", "B": "8"}},
        route_id=42,
        route_origin=PlanPositionRouteOrigin.manual_confirmed,
    )
    unassigned = _position(
        plan_id,
        source_payload={"raw_columns": {"A": "1", "B": "2"}, "operation": "упаковка"},
    )

    assert position_route_identity_key(noisy) == position_route_identity_key(clean)
    assert position_route_identity_key(noisy) != position_route_identity_key(unassigned)


@pytest.mark.asyncio
async def test_batch_returns_one_object_for_identical_positions(session) -> None:
    """Позиции одной идентичности резолвятся один раз — результат тот же объект.

    Не «случайно совпало»: мемо по нормализованной идентичности и есть
    заявленный эффект правки. Число SQL на таком наборе бесполезно —
    снимок всё равно один запрос, — а вот повторный резолв виден по самому
    факту переиспользования результата.
    """
    plan_id = await _make_plan(session, "memo")
    route = ProductionRoute(name="Маршрут 292 общий", is_active=True)
    session.add(route)
    await session.flush()
    positions = [
        _position(
            plan_id,
            source_payload={"raw_columns": {"колонка": f"строка-{index}"}},
            route_id=route.id,
            route_origin=PlanPositionRouteOrigin.legacy,
        )
        for index in range(5)
    ]
    session.add_all(positions)
    await session.flush()

    batch = await resolve_position_routes_batch(session, positions)

    first = batch[positions[0].id]
    assert first.route_id == route.id and first.error is None
    assert all(batch[p.id] is first for p in positions)


@pytest.mark.asyncio
async def test_batch_sql_count_does_not_grow_with_positions(session) -> None:
    """Рост списка позиций не добавляет SQL: снимок один на список."""
    plan_id = await _make_plan(session, "count")
    route = ProductionRoute(name="Маршрут 292 счёт", is_active=True)
    archived = ProductionRoute(name="Маршрут 292 архивный", is_active=False)
    session.add_all([route, archived])
    await session.flush()
    positions = [
        _position(
            plan_id,
            source_payload={"raw_columns": {"колонка": f"строка-{index}"}},
            route_id=route.id if index % 2 else archived.id,
            route_origin=PlanPositionRouteOrigin.legacy,
        )
        for index in range(40)
    ]
    session.add_all(positions)
    await session.flush()

    counter, remove = _count_sql(session)
    try:
        batch = await resolve_position_routes_batch(session, positions)
    finally:
        remove()

    assert counter["n"] <= 6, f"40 позиций дали {counter['n']} SQL — снимок не отработал"
    assert len(batch) == 40


def test_branch_constants_are_distinct() -> None:
    """Имена веток — часть контракта ключа; смешение сделало бы его хрупким."""
    assert len({BRANCH_MANUAL, BRANCH_STORED, BRANCH_DYNAMIC, BRANCH_SELECTION}) == 4


async def _seed_pair(session, sku_a: str, sku_b: str):
    product_a = Product(
        sku=sku_a, name=f"Компонент {sku_a}", type=ProductType.component, unit="pcs"
    )
    product_b = Product(
        sku=sku_b, name=f"Компонент {sku_b}", type=ProductType.component, unit="pcs"
    )
    session.add_all([product_a, product_b])
    await session.flush()
    pair = ProductPair(product_a_id=product_a.id, product_b_id=product_b.id)
    session.add(pair)
    await session.flush()
    return product_a, product_b, pair


@pytest.mark.asyncio
async def test_pair_cache_serves_repeat_without_sql(session) -> None:
    """Повторная позиция в одном запросе не даёт ни одного SQL.

    Без кэша каждая парная позиция без снапшота читала справочник пар
    целиком. Проверка идёт через число запросов: именно его и покупает
    кэш; ответ проверяется рядом, на равенство.
    """
    plan_id = await _make_plan(session, "pairs")
    product_a, product_b, pair = await _seed_pair(session, "292-A", "292-B")
    position = _position(plan_id, source_payload={"components": [{"sku": "292-A"}, {"sku": "292-B"}]})
    session.add(position)
    await session.flush()

    cache = PairResolutionCache()
    first = await resolve_effective_product_ids(session, position, cache=cache)
    assert first == [pair.product_a_id, pair.product_b_id] == [product_a.id, product_b.id]

    counter, remove = _count_sql(session)
    try:
        second = await resolve_effective_product_ids(session, position, cache=cache)
        third = await resolve_effective_product_ids(session, position, cache=cache)
    finally:
        remove()

    assert counter["n"] == 0, f"повторные резолвы дали {counter['n']} SQL"
    assert second == first and third == first


@pytest.mark.asyncio
async def test_pair_cache_remembers_unresolved_pair(session) -> None:
    """Пара, которой нет в справочнике, тоже не повторяет запрос.

    Именно этот случай стоит дороже всего в проде: позиция без снапшота и
    без строки в ``product_pairs`` отдаёт пустой список, и без кэша каждая
    такая позиция заново читала справочник.
    """
    plan_id = await _make_plan(session, "unresolved")
    position = _position(
        plan_id,
        source_payload={"components": [{"sku": "292-НЕТ-A"}, {"sku": "292-НЕТ-B"}]},
    )
    session.add(position)
    await session.flush()

    cache = PairResolutionCache()
    assert await resolve_effective_product_ids(session, position, cache=cache) == []

    counter, remove = _count_sql(session)
    try:
        again = await resolve_effective_product_ids(session, position, cache=cache)
    finally:
        remove()

    assert again == []
    assert counter["n"] == 0


@pytest.mark.asyncio
async def test_pair_cache_result_matches_plain_lookup(session) -> None:
    """Кэш пары отдаёт тот же результат, что и поштучный поиск без кэша.

    Нормализация SKU и порядок обхода справочника в кэше свои, поэтому
    равенство с эталонным путём проверяется явно, а не по отсутствию ошибок.
    """
    plan_id = await _make_plan(session, "equivalence")
    product_a, product_b, pair = await _seed_pair(session, "292-C", "292-D")
    other = Product(
        sku="292-E", name="Компонент 292-E", type=ProductType.component, unit="pcs"
    )
    session.add(other)
    await session.flush()
    # Посторонняя пара в справочнике: её нельзя спутать с искомой по порядку строк.
    session.add(ProductPair(product_a_id=product_b.id, product_b_id=other.id))
    await session.flush()

    position = _position(
        plan_id, source_payload={"components": [{"sku": " 292-d "}, {"sku": "292-c"}]}
    )
    session.add(position)
    await session.flush()

    plain = await resolve_effective_product_ids(session, position)
    cached = await resolve_effective_product_ids(
        session, position, cache=PairResolutionCache()
    )

    assert plain == cached == [pair.product_a_id, pair.product_b_id]
    assert plain == [product_a.id, product_b.id]
