"""Предикат идентичности маршрута — единственное место, где он задан (#230).

Функцию ``route_identity_query`` проверяем отдельно от вызывающих: она
задаёт правило, по которому живут все семь мест поиска, и разойтись с
ними может только здесь. Тесты контрастные — каждый пункт закрывает
конкретное расхождение, найденное при инвентаризации.
"""
from __future__ import annotations

import pytest
from app.models.route import ProductionRoute
from app.services.route_identity import (
    MATCH_BY_CODE,
    MATCH_BY_LEGACY_NAME,
    find_route_by_code,
    find_route_by_identity,
    find_route_by_name,
    route_identity_query,
)
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _route(
    session: AsyncSession,
    *,
    name: str,
    code: str | None = None,
    is_active: bool = True,
) -> ProductionRoute:
    route = ProductionRoute(name=name, code=code, is_active=is_active)
    session.add(route)
    await session.flush()
    return route


def _sql(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


async def test_code_and_name_are_different_inputs(session: AsyncSession) -> None:
    """Код и имя — разные входы; оба сразу искать нельзя."""
    with pytest.raises(ValueError, match="разные входы"):
        route_identity_query(code="auto-1", name="Маршрут")
    with pytest.raises(ValueError, match="нечего искать"):
        route_identity_query()


async def test_lookup_by_code_ignores_name_filtering(session: AsyncSession) -> None:
    """По коду находится строка с любым именем и даже без кода-поиска."""
    route = await _route(session, name="ЮП-460 резка", code="auto-abc")

    found = await find_route_by_code(session, "auto-abc")

    assert found is not None
    assert found.id == route.id
    assert await find_route_by_code(session, "auto-none") is None


async def test_name_lookup_is_restricted_to_rows_without_code(session: AsyncSession) -> None:
    """`legacy_name_only`: найденный по имени маршрут С КОДОМ — не наш.

    ADR-0051 п. 3: у маршрута с кодом своя идентичность, и опознавать его
    по подписи нельзя. Собственно на этом держатся все fallback-по-имени.
    """
    manual = await _route(session, name="ЮП-460 резка", code="manual-1")
    legacy = await _route(session, name="ЮП-460 резка", code=None)
    await session.commit()

    found = await find_route_by_name(session, "ЮП-460 резка")

    assert found is not None, "маршрут до #230 (без кода) обязан находиться"
    assert found.id == legacy.id
    assert found.id != manual.id, "маршрут с кодом не должен находиться по имени"


async def test_name_lookup_without_legacy_filter_sees_every_row(session: AsyncSession) -> None:
    """Ручной путь снимает фильтр: там код не играет роли.

    Проверка уникальности имени у `POST /api/routes` обязана видеть и
    автомаршрут — иначе 409 не срабатывает, и оператор получает вместо
    внятного отказа `IntegrityError` по уникальности кода.
    """
    manual = await _route(session, name="ЮП-460 резка", code="manual-1")
    await session.commit()

    found = await find_route_by_name(
        session, "ЮП-460 резка", legacy_name_only=False
    )

    assert found is not None, "ручной путь обязан видеть маршрут с кодом"
    assert found.id == manual.id


async def test_only_active_filters_archived_routes(session: AsyncSession) -> None:
    """`only_active`: архивный маршрут назначением не считается."""
    archived = await _route(session, name="Архивный", code="auto-arch", is_active=False)
    await session.commit()

    assert await find_route_by_code(session, "auto-arch") is not None, "без флага виден"
    assert await find_route_by_code(session, "auto-arch", only_active=True) is None
    assert (
        await find_route_by_name(
            session, "Архивный", legacy_name_only=False, only_active=True
        )
        is None
    )
    assert archived.is_active is False


async def test_order_is_oldest_first(session: AsyncSession) -> None:
    """Порядок выборки — `id` ASC, и он одинаков для кода и имени.

    При `limit(1)` «самый свежий» и «самый старый» дают разные ответы на
    одних и тех же данных. Сид и импорт берут самого старого, и это
    совпадает с тем, кого обновляет `run_seed`.
    """
    older = await _route(session, name="Дубль", code=None)
    newer = await _route(session, name="Дубль", code=None)
    await session.commit()
    assert newer.id > older.id

    by_name = await find_route_by_name(session, "Дубль")
    assert by_name is not None and by_name.id == older.id

    sql = _sql(route_identity_query(name="Дубль"))
    assert "ORDER BY production_routes.id" in sql
    assert "DESC" not in sql, "самый свежий — не тот, кого обновляет run_seed"


async def test_code_lookup_orders_by_id_ascending(session: AsyncSession) -> None:
    """И по коду порядок тот же — иначе сид обновлял бы нестабильный набор."""
    sql = _sql(route_identity_query(code="auto-1"))
    assert "ORDER BY production_routes.id" in sql
    assert "DESC" not in sql


async def test_exclude_id_skips_the_edited_route(session: AsyncSession) -> None:
    """`exclude_id`: переименование не считается конфликтом с самим собой."""
    route = await _route(session, name="Маршрут", code="manual-1")
    await session.commit()

    found = await find_route_by_name(
        session, "Маршрут", legacy_name_only=False, exclude_id=route.id
    )

    assert found is None, "маршрут не должен конфликтовать сам с собой"


async def test_query_always_limits_to_one_row(session: AsyncSession) -> None:
    """`limit(1)` обязателен: без него `db.scalar` на дублях raises."""
    for _ in range(3):
        await _route(session, name="Дубль", code=None)
    await session.commit()

    stmt = route_identity_query(name="Дубль")
    assert "LIMIT" in _sql(stmt)
    assert await find_route_by_name(session, "Дубль") is not None


# --- #326: порядок поиска тождества объявлен один раз -----------------------


async def test_identity_order_prefers_code_over_legacy_name(session: AsyncSession) -> None:
    """Сначала код: одноимённый legacy-маршрут не подменяет найденный по коду.

    Ровно это расхождение и лечится: имя — подпись, и два разных маршрута
    законно носят одно имя (ADR-0045). Найденный по имени (без кода) не
    должен забирать строку, у которой есть код.
    """
    coded = await _route(session, name="Общее имя", code="auto-abc")
    await _route(session, name="Общее имя", code=None)
    await session.commit()

    match = await find_route_by_identity(session, code="auto-abc", name="Общее имя")

    assert match is not None
    assert match.route.id == coded.id
    assert match.matched_by == MATCH_BY_CODE


async def test_identity_order_falls_back_to_legacy_name(session: AsyncSession) -> None:
    """Кода нет или по коду пусто — тогда, и только тогда, ищем по имени.

    По имени находятся лишь строки без кода: маршрут с кодом — чужой
    (ADR-0051 п. 3), и подставлять его по подписи нельзя.
    """
    legacy = await _route(session, name="Легаси", code=None)
    await _route(session, name="С кодом", code="auto-coded")
    await session.commit()

    by_missing_code = await find_route_by_identity(
        session, code="auto-none", name="Легаси"
    )
    assert by_missing_code is not None
    assert by_missing_code.route.id == legacy.id
    assert by_missing_code.matched_by == MATCH_BY_LEGACY_NAME

    without_code = await find_route_by_identity(session, code=None, name="Легаси")
    assert without_code is not None and without_code.route.id == legacy.id

    assert await find_route_by_identity(session, code=None, name="С кодом") is None
    assert await find_route_by_identity(session, code="auto-none", name=None) is None


async def test_identity_order_respects_only_active(session: AsyncSession) -> None:
    """`only_active` действует на обе ступени: архивный — не назначение.

    Автоматчик ищет назначение с этим флагом; без него архивный маршрут
    выглядел бы назначенным и падал бы позже, в take-to-work.
    """
    archived_coded = await _route(
        session, name="Архивный код", code="auto-arch", is_active=False
    )
    legacy = await _route(session, name="Архивный код", code=None)
    await session.commit()

    assert (await find_route_by_identity(session, code="auto-arch", name=None)).route.id == archived_coded.id
    active_only = await find_route_by_identity(
        session, code="auto-arch", name="Архивный код", only_active=True
    )
    assert active_only is not None and active_only.route.id == legacy.id

    legacy.is_active = False
    await session.flush()
    assert (
        await find_route_by_identity(
            session, code="auto-arch", name="Архивный код", only_active=True
        )
        is None
    )


async def test_identity_caches_memoize_both_misses_and_hits(session: AsyncSession) -> None:
    """Кэш вызывающего — «уже искали», в том числе для промаха (``None``).

    Без записи ``None`` батч импорта повторял бы запрос на каждой строке с
    тем же кодом/именем, а снимок батча позиций не сохранял бы «нет такого».
    """
    route = await _route(session, name="Кэш", code="auto-cache")
    await session.commit()
    code_cache: dict[str, ProductionRoute | None] = {}
    name_cache: dict[str, ProductionRoute | None] = {}

    first = await find_route_by_identity(
        session, code="auto-cache", name="Кэш", code_cache=code_cache, name_cache=name_cache
    )
    assert first is not None and first.route.id == route.id
    assert code_cache == {"auto-cache": route}
    assert name_cache == {}, "по имени не искали: код нашёлся"

    miss = await find_route_by_identity(
        session,
        code="auto-missing",
        name="Нет такого",
        code_cache=code_cache,
        name_cache=name_cache,
    )
    assert miss is None
    assert code_cache["auto-missing"] is None
    assert name_cache["Нет такого"] is None


async def test_identity_snapshot_cache_miss_does_not_query(session: AsyncSession) -> None:
    """Снимок батча — полный: промах в нём значит «нет», а не «спроси БД».

    Снимок собирается одним запросом по всем маршрутам, поэтому отсутствие
    ключа — ответ. Если бы промах уходил в БД, список из N позиций с новыми
    составами дал бы N запросов — тот самый N+1, ради снятия которого снимок
    и заведён (батч-резолв обещает один запрос на список).
    """
    code_cache: dict[str, ProductionRoute | None] = {}
    name_cache: dict[str, ProductionRoute | None] = {}
    counter = {"n": 0}
    sync_engine = session.bind.sync_engine

    def _count(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(sync_engine, "before_cursor_execute", _count)
    try:
        match = await find_route_by_identity(
            session,
            code="auto-none",
            name="Нет в снимке",
            code_cache=code_cache,
            name_cache=name_cache,
            cache_is_snapshot=True,
        )
    finally:
        event.remove(sync_engine, "before_cursor_execute", _count)

    assert match is None
    assert counter["n"] == 0, "промах по снимку не должен ходить в БД"
    assert code_cache == {} and name_cache == {}, "снимок не дописывается"
