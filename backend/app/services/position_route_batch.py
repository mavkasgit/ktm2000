"""Батчевый резолв маршрутов позиций — снятие N+1 в списках позиций (#292).

Почему так
----------
``resolve_position_route`` вызывается почти всеми списками позиций в цикле,
и стоимость вызова — от одного SQL (сохранённый ``route_id``) до 7–12
(динамическая пересборка маршрута или подбор по правилам). Ключ кэша
``make_position_route_cache_key`` включает весь ``source_payload``, поэтому
на реальных данных он уникален почти на каждую позицию: кэш не бьётся, и
список из N позиций стоит N × (1…12) запросов.

Что здесь
---------
Снимок данных на список позиций (:func:`load_position_route_batch_cache`) плюс
:func:`resolve_position_routes_batch`, которая резолвит список, отдавая
``resolve_position_route`` уже прогретый снимок. Сам ``resolve_position_route``
меняется только необязательным параметром ``batch``: без него поведение
побайтово прежнее, и ни один вызывающий на это не переведён (expand, тикет
#292; переводят #296/#297/#298).

Ключ кэша результата — :func:`position_route_identity_key`, то есть то, что
резолв действительно читает, а не сырой payload:

* ветка «ручное/сохранённое назначение» payload не читает вовсе — ключ его
  не содержит, и позиции, отличающиеся только шумом ``raw_columns``,
  резолвятся один раз;
* ветка «динамическая сборка» читает payload через мемоизированную сборку
  (``RouteBuildBatchCache.built_routes``), поэтому в ключ входит результат
  сборки — имя, сигнатура и её ошибка, а не весь payload;
* ветка «подбор по правилам» читает payload целиком (условия правил адресуют
  произвольные поля и сырые колонки Excel) — там ключ узким быть не может,
  и он остаётся полным.

Снимок — согласованный слепок на момент чтения, как и все прочие батч-кэши
репозитория (``RouteSelectionBatchCache``, ``RouteBuildBatchCache``, #163).
Внутри одного HTTP-запроса справочники не меняются; кэш на этом и держится.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.imports import ImportBatch
from app.models.product import Product
from app.models.production_plan import (
    PlanPosition,
    PlanPositionRouteOrigin,
)
from app.models.route import ProductionRoute, RouteRuleProfile, RouteStage
from app.services.route_builder import (
    BuiltRoute,
    RouteBuildBatchCache,
    build_route_from_profile,
    load_route_build_batch_cache,
)
from app.services.route_matcher import (
    ResolvedRouteInfo,
    _payload_for_dynamic_build,
    _product_for_build,
    resolve_position_route,
)
from app.services.route_selection import (
    RouteSelectionBatchCache,
    load_route_selection_batch_cache,
)
from app.services.route_signature import (
    auto_route_code,
    encode_signature,
    signature_steps_from_stages,
)

# Ветки резолва в ключе кэша. Имена — часть контракта функции: по ним видно,
# какая ветка дала результат, когда ключи сравнивают в тестах и в логах.
BRANCH_MANUAL = "manual"
BRANCH_STORED = "stored"
BRANCH_DYNAMIC = "dynamic"
BRANCH_SELECTION = "selection"


def freeze_identity_value(value: Any) -> Any:
    """Хэшируемая проекция значения payload для ключа идентичности.

    Отличается от ``make_position_route_cache_key`` тем, что не падает на
    нехэшируемых значениях (set, вложенные структуры с ключами не-str) и
    приводит ключи к строке: два payload, отличающиеся только порядком
    пары «ключ → значение», дают один ключ, а не два.
    """
    if isinstance(value, dict):
        return tuple(
            (str(key), freeze_identity_value(value[key]))
            for key in sorted(value, key=str)
        )
    if isinstance(value, (list, tuple)):
        return tuple(freeze_identity_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((freeze_identity_value(item) for item in value), key=repr))
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value


@dataclass(slots=True)
class PositionRouteBatchCache:
    """Снимок справочников для резолва маршрутов списка позиций (#292).

    Заполняется один раз на список и переиспользуется всеми позициями:
    маршруты (они же — сохранённые назначения и поиск по идентичности),
    профили, продукты, батчи импорта, кэши подбора и сборки. Привязан к
    сессии батча, как и ``RouteSelectionBatchCache``.

    ``signatures_by_route`` — фактические сигнатуры маршрутов, посчитанные
    по этапам; туда попадают только те маршруты, у которых сохранённой
    сигнатуры нет (именно их ``route_signature_conflicts`` читает поштучно).
    """

    routes_by_id: dict[int, ProductionRoute] = field(default_factory=dict)
    profiles_by_id: dict[int, RouteRuleProfile] = field(default_factory=dict)
    products_by_id: dict[int, Product] = field(default_factory=dict)
    import_batches_by_id: dict[int, ImportBatch] = field(default_factory=dict)
    selection_caches: dict[int | None, RouteSelectionBatchCache] = field(default_factory=dict)
    build_caches: dict[int, RouteBuildBatchCache] = field(default_factory=dict)
    route_by_code: dict[str, ProductionRoute] = field(default_factory=dict)
    legacy_route_by_name: dict[str, ProductionRoute] = field(default_factory=dict)
    signatures_by_route: dict[int, str | None] = field(default_factory=dict)


def _payload_product_ids(positions: list[PlanPosition]) -> set[int]:
    """``product_id`` из payload позиций — вторая ветка выбора продукта.

    Сборщик берёт его, когда ``product_id`` позиции пуст (путь
    предпросмотра импорта). Нечисловые значения отсекаются: на них сборщик
    и так падает в ``int()``, и широкий перехват вызывающего отработает
    одинаково — просто без лишнего запроса к ``products``.
    """
    ids: set[int] = set()
    for position in positions:
        raw = (position.source_payload or {}).get("product_id")
        if not raw:
            continue
        try:
            ids.add(int(raw))
        except (TypeError, ValueError):
            continue
    return ids


def _needs_dynamic_build(position: PlanPosition, cache: PositionRouteBatchCache) -> bool:
    """Дойдёт ли резолв позиции до динамической пересборки маршрута."""
    if position.route_profile_id is None:
        return False
    profile = cache.profiles_by_id.get(position.route_profile_id)
    return profile is not None and bool(profile.route_sections)


def _reaches_selection(position: PlanPosition, cache: PositionRouteBatchCache) -> bool:
    """Дойдёт ли резолв позиции до подбора маршрута по правилам.

    Ветка одна и последняя: сохранённое назначение и динамическая сборка
    уходят из неё всегда, когда у них есть что отдать. Правило нужно,
    чтобы не грузить кэш подбора профиля ради позиций, которые до него
    не дойдут.
    """
    if position.route_id is not None:
        return False
    return not _needs_dynamic_build(position, cache)


async def load_position_route_batch_cache(
    db: AsyncSession,
    positions: list[PlanPosition],
) -> PositionRouteBatchCache:
    """Собрать снимок справочников для резолва списка позиций.

    Число запросов не зависит от числа позиций: маршруты, профили,
    продукты, батчи импорта и по одному кэшу подбора на каждый профиль,
    упомянутый позициями.
    """
    cache = PositionRouteBatchCache()

    # Маршруты одним снимком: он же словарь сохранённых назначений (то,
    # что делает `db.get`), он же поиск по коду и по имени. Сортировка по
    # id — как в `route_identity_query`, поэтому «первый» маршрут здесь
    # тот же самый, что и в поштучном поиске.
    routes = (
        await db.execute(select(ProductionRoute).order_by(ProductionRoute.id))
    ).scalars().all()
    for route in routes:
        cache.routes_by_id[route.id] = route
    for route in routes:
        if not route.is_active:
            continue
        if route.code is not None and route.code and route.code not in cache.route_by_code:
            cache.route_by_code[route.code] = route
        if route.code is None and route.name not in cache.legacy_route_by_name:
            cache.legacy_route_by_name[route.name] = route

    profile_ids = {
        position.route_profile_id
        for position in positions
        if position.route_profile_id is not None
    }
    if profile_ids:
        profiles = (
            await db.execute(
                select(RouteRuleProfile).where(RouteRuleProfile.id.in_(profile_ids))
            )
        ).scalars().all()
        for profile in profiles:
            cache.profiles_by_id[profile.id] = profile

    product_ids = {
        int(position.product_id)
        for position in positions
        if position.product_id is not None
    }
    product_ids |= _payload_product_ids(positions)
    if product_ids:
        products = (
            await db.execute(
                select(Product)
                .options(selectinload(Product.processing_flags))
                .where(Product.id.in_(product_ids))
            )
        ).scalars().all()
        for product in products:
            cache.products_by_id[product.id] = product

    import_batch_ids = {
        position.import_batch_id
        for position in positions
        if position.import_batch_id is not None
    }
    if import_batch_ids:
        import_batches = (
            await db.execute(
                select(ImportBatch).where(ImportBatch.id.in_(import_batch_ids))
            )
        ).scalars().all()
        for import_batch in import_batches:
            cache.import_batches_by_id[import_batch.id] = import_batch

    # Профили, чьи правила нужны хоть одной позиции: подбору — напрямую,
    # сборке — через общий снимок (правила и участки не грузятся дважды).
    # Позиция с сохранённым назначением до подбора не доходит, и её профиль
    # из батча импорта в снимок не попадает.
    rule_profile_ids: set[int | None] = set()
    for position in positions:
        if _needs_dynamic_build(position, cache):
            rule_profile_ids.add(position.route_profile_id)
        if _reaches_selection(position, cache):
            rule_profile_ids.add(_rule_profile_id(position, cache))
    for profile_id in sorted(pid for pid in rule_profile_ids if pid is not None):
        cache.selection_caches[profile_id] = await load_route_selection_batch_cache(
            db, profile_id
        )
    if None in rule_profile_ids:
        cache.selection_caches[None] = await load_route_selection_batch_cache(db, None)

    for profile_id in sorted(
        {p.route_profile_id for p in positions if _needs_dynamic_build(p, cache)}
    ):
        cache.build_caches[profile_id] = await load_route_build_batch_cache(
            db,
            cache.profiles_by_id[profile_id],
            selection_cache=cache.selection_caches.get(profile_id),
        )
    return cache


async def _prefetch_built_routes(
    db: AsyncSession,
    cache: PositionRouteBatchCache,
    positions: list[PlanPosition],
) -> dict[int, BuiltRoute]:
    """Пересобрать маршрут каждой позиции с профилем — до резолва.

    Сборка с батч-кэшем не ходит в БД и мемоизирует результат по derived-входу,
    поэтому проход здесь бесплатный: последующий вызов
    ``resolve_position_route`` попадёт в тот же ``BuiltRoute``. Нужен он,
    чтобы ключ идентичности динамической ветви знал имя и сигнатуру
    пересборки, а ``_prefetch_route_signatures`` — какие маршруты сверять.
    """
    built: dict[int, BuiltRoute] = {}
    for position in positions:
        if not _needs_dynamic_build(position, cache):
            continue
        profile = cache.profiles_by_id[position.route_profile_id]
        built[position.id] = await build_route_from_profile(
            db,
            profile,
            _payload_for_dynamic_build(position),
            position,
            product=_product_for_build(position, cache),
            batch=cache.build_caches.get(profile.id),
        )
    return built


async def _prefetch_route_signatures(
    db: AsyncSession,
    cache: PositionRouteBatchCache,
    built_routes: list[BuiltRoute],
) -> None:
    """Посчитать фактические сигнатуры кандидатов одним запросом.

    Кандидат — маршрут, найденный по коду из сигнатуры пересборки
    (ADR-0051 п. 4). Сохранённая сигнатура ответа не меняет: её читать
    не нужно. Нужны только этапы маршрутов без сохранённой сигнатуры, и
    только для них — остальные отсекаются по ``route_signature``.
    """
    candidates: dict[int, ProductionRoute] = {}
    for built in built_routes:
        if built.error or not built.signature:
            continue
        code = auto_route_code(built.signature)
        if code is None:
            continue
        matched = cache.route_by_code.get(code)
        if matched is not None:
            candidates.setdefault(matched.id, matched)

    pending = [route_id for route_id, route in candidates.items() if not route.route_signature]
    if not pending:
        return
    stages = (
        await db.execute(
            select(RouteStage)
            .where(RouteStage.route_id.in_(pending))
            .options(
                selectinload(RouteStage.operations),
                selectinload(RouteStage.section),
                selectinload(RouteStage.storage_section),
            )
            .order_by(RouteStage.route_id, RouteStage.sequence)
        )
    ).scalars().all()
    stages_by_route: dict[int, list[RouteStage]] = {}
    for stage in stages:
        stages_by_route.setdefault(stage.route_id, []).append(stage)
    for route_id in pending:
        route_stages = stages_by_route.get(route_id) or []
        cache.signatures_by_route[route_id] = (
            encode_signature(signature_steps_from_stages(route_stages))
            if route_stages
            else None
        )


def position_route_identity_key(
    position: PlanPosition,
    *,
    built: BuiltRoute | None = None,
    rule_profile_id: int | None = None,
) -> tuple:
    """Ключ кэша результата резолва — нормализованная идентичность позиции.

    Не «сырой payload», а то, что резолв читает на этой позиции: ветка,
    сохранённое назначение, профиль, продукт, профиль правил из батча
    импорта, отдаваемые позицией поля маршрута — и payload там, где он
    действительно влияет на резолв (см. модульный docstring).

    Поля ``route_origin``/``route_match_quality``/``route_match_reason``
    берутся как есть, без нормализации: неразобранные значения — редкий
    случай, и лишний элемент в ключе даёт лишь промах кэша, а не подмену
    результата. Побочные значения (``datetime``, ``Enum``) в ключе не
    приводятся: они хэшируются как есть и сравниваются по значению.
    """
    branch = _branch(position, built)
    if branch == BRANCH_DYNAMIC:
        # Пересборка мемоизирована по derived-входу: тот же BuiltRoute —
        # те же имя, сигнатура и вердикт сборки, а значит и тот же ответ
        # резолва (дальше идут только они и строки маршрутов снимка).
        payload_key: Any = (
            built.name,
            built.signature,
            built.error,
        ) if built is not None else None
    elif branch == BRANCH_SELECTION:
        # Подбор по правилам читает payload целиком: условия адресуют
        # произвольные поля и сырые колонки, сузить ключ здесь нельзя.
        payload_key = freeze_identity_value(position.source_payload)
    else:
        # Ручное и сохранённое назначение payload не читают.
        payload_key = None

    return (
        branch,
        position.route_id,
        position.route_profile_id,
        rule_profile_id,
        position.product_id,
        position.source_sku,
        position.route_origin,
        position.route_match_quality,
        position.route_match_reason,
        position.route_assigned_at,
        position.route_manual_confirmed_at,
        payload_key,
    )


def _branch(position: PlanPosition, built: BuiltRoute | None) -> str:
    """Ветка резолва позиции — тот же порядок, что в ``resolve_position_route``."""
    if built is not None:
        return BRANCH_DYNAMIC
    if position.route_id is not None:
        if position.route_origin == PlanPositionRouteOrigin.manual_confirmed.value:
            return BRANCH_MANUAL
        return BRANCH_STORED
    return BRANCH_SELECTION


async def resolve_position_routes_batch(
    db: AsyncSession,
    positions: list[PlanPosition],
    *,
    cache: PositionRouteBatchCache | None = None,
) -> dict[int, ResolvedRouteInfo]:
    """Разрешить маршруты списка позиций — по одному проходу, не по N+1.

    Возвращает результат по ``position.id``. Каждый элемент равен тому, что
    вернул бы поштучный ``resolve_position_route`` на той же позиции: резолв
    тот же, отличается только источник данных (снимок вместо запроса на
    строку) и мемоизация результата по идентичности позиции.

    Позиции, у которых динамическая сборка не дала маршрута, уходят в
    сохранённое назначение, а при его отсутствии — в подбор по правилам:
    ветка выводится из результата пересборки, а не из полей позиции, иначе
    ключ кэша разошёлся бы с реально отработавшей веткой.

    Позиции одной идентичности получают **один и тот же объект**
    ``ResolvedRouteInfo`` — по контракту разделяемых строк снимка (как в
    ``RouteSelectionBatchCache``). Его читают, не мутируют; кому нужна своя
    копия, делает ``dataclasses.replace``.
    """
    position_list = list(positions)
    if not position_list:
        return {}
    if cache is None:
        cache = await load_position_route_batch_cache(db, position_list)

    built_by_position = await _prefetch_built_routes(db, cache, position_list)
    await _prefetch_route_signatures(db, cache, list(built_by_position.values()))

    results: dict[int, ResolvedRouteInfo] = {}
    memo: dict[tuple, ResolvedRouteInfo] = {}
    for position in position_list:
        built = built_by_position.get(position.id)
        rule_profile_id = _rule_profile_id(position, cache)
        key = position_route_identity_key(
            position, built=built, rule_profile_id=rule_profile_id
        )
        route_info = memo.get(key)
        if route_info is None:
            route_info = await resolve_position_route(
                db, position, route_cache=cache.routes_by_id, batch=cache
            )
            memo[key] = route_info
        results[position.id] = route_info
    return results


def _rule_profile_id(
    position: PlanPosition, cache: PositionRouteBatchCache
) -> int | None:
    """Профиль правил подбора для позиции — из её батча импорта."""
    if position.import_batch_id is None:
        return None
    import_batch = cache.import_batches_by_id.get(position.import_batch_id)
    return import_batch.rule_profile_id if import_batch is not None else None
