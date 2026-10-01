"""Предикат идентичности маршрута — единственное место, где он задан (#230).

Функцию ``route_identity_query`` проверяем отдельно от вызывающих: она
задаёт правило, по которому живут все семь мест поиска, и разойтись с
ними может только здесь. Тесты контрастные — каждый пункт закрывает
конкретное расхождение, найденное при инвентаризации.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import ProductionRoute
from app.services.route_identity import (
    find_route_by_code,
    find_route_by_name,
    route_identity_query,
)

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
