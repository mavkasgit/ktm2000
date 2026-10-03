"""Мёртвые selectin-связи не грузятся (#303).

Инвентаризация нашла четыре связи без потребителей. **Три действительно мёртвые**,
одна — нет:

* `StorageProductionGroup.sections` — потребителей ноль;
* `ProductionRoute.rules` — `routes.py:190` берёт правила отдельным запросом;
* `RouteRuleProfile.rules` — `load_selection_rules_for_profile` идёт прямо
  `WHERE profile_id IN (…)`;
* `User.sections` — **живая**: её читает свойство `section_ids`, а его отдают
  `UserOut` и `MeResponse`. С `lazy="raise"` на ней падают 27 тестов, поэтому
  она остаётся selectin. Тест ниже фиксирует это, чтобы следующая инвентаризация
  не объявила её мёртвой во второй раз.

Проверять запись `user.sections` здесь не нужно: её покрывают существующие
`tests/test_users.py` и `tests/test_me_ttl.py`. Именно они, а не чтение кода,
показали, что `lazy="raise"` ломает `UserOut`/`MeResponse`. Дублировать их в
этом файле означало бы писать хрупкие фикстуры поверх уже работающих.
"""
from __future__ import annotations

import re
import pytest
from app.api.routes import routes as routes_api
from app.models.route import ProductionRoute, RouteRuleProfile, RouteStage
from app.models.section import Section
from app.models.spg import StorageProductionGroup
from app.models.user import User
from app.services.section_ref import SectionRef, load_section_refs
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


def _counting(session: AsyncSession):
    """Счётчик SELECT вокруг блока — и список загруженных таблиц.

    Считаются только `SELECT`: SAVEPOINT/RELEASE — это работа фикстуры
    (транзакция на тест), а не запрос ручки. Считать их вместе нельзя —
    число начинает зависеть от того, сколько savepoint'ов сделала фикстура,
    а не от того, что читает код под тестом.
    """
    counter = {"n": 0}
    tables: list[str] = []
    sync_engine = session.bind.sync_engine  # type: ignore[union-attr]

    def _before(_conn, _cursor, statement, _params, _context, _many):
        head = statement.lstrip().split(None, 1)[0].upper()
        if head != "SELECT":
            return
        counter["n"] += 1
        m = re.search(r"\bFROM\s+([a-z_]+)", statement)
        if m:
            tables.append(m.group(1))

    event.listen(sync_engine, "before_cursor_execute", _before)
    return counter, tables, lambda: event.remove(
        sync_engine, "before_cursor_execute", _before
    )


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (ProductionRoute, "rules"),
        (RouteRuleProfile, "rules"),
        (StorageProductionGroup, "sections"),
    ],
)
def test_dead_relationships_are_not_eager(model, field) -> None:
    """Мёртвые связи не объявляются selectin.

    `selectin` платит на каждую материализацию, а читать эти коллекции нечего.
    """
    rel = model.__mapper__.relationships[field]
    assert rel.lazy != "selectin", (
        f"{model.__name__}.{field} объявлена lazy='selectin', но потребителей нет — "
        "это лишний запрос на каждую материализацию"
    )


def test_user_sections_stays_eager_because_section_ids_reads_it() -> None:
    """`User.sections` — исключение: её читает свойство `section_ids`.

    Инвентаризация #303 объявила её мёртвой, потому что grep искал `user.sections`
    и не дошёл до свойства. `UserOut.section_ids` и `MeResponse.section_ids` идут
    через `from_attributes`, то есть через это свойство. С `lazy="raise"` падают
    27 тестов — фиксируем здесь, чтобы вывод не повторился.
    """
    rel = User.__mapper__.relationships["sections"]
    assert rel.lazy == "selectin"
    assert "sections" in User.section_ids.fget.__code__.co_names


async def test_materializing_route_does_not_load_its_rules(
    session: AsyncSession,
) -> None:
    """Материализация `ProductionRoute` не тянет правила маршрута.

    С `lazy="selectin"` на `rules` список маршрутов стоил 4 SELECT: маршруты,
    `stages`, `operations` и `rules`. Правила не читал никто — после правки
    остаётся три, и проверяется это не «число упало», а отсутствие
    `route_matching_rules` в списке таблиц.

    Маршруты и этапы создаются здесь же: на пустой базе `select` отдаёт ноль
    строк, selectin не срабатывает, и тест проходит, ничего не проверяя.
    """
    section = Section(
        code="T303-RULES", name="Проба правил", sort_order=953, type="production"
    )
    session.add(section)
    await session.flush()
    for index in range(5):
        route = ProductionRoute(
            code=f"T303-RULES-{index}", name="Проба правил", sort_order=953 + index
        )
        session.add(route)
        await session.flush()
        session.add(RouteStage(route_id=route.id, sequence=1, section_id=section.id))
    await session.commit()

    counter, tables, remove = _counting(session)
    try:
        rows = (
            await session.scalars(
                select(ProductionRoute).order_by(ProductionRoute.id).limit(5)
            )
        ).all()
    finally:
        remove()
    # Раньше список маршрутов стоил 4 SELECT: маршруты, `stages`, `operations`
    # и `rules`. Правила не читал никто — их SELECT'а быть не должно.
    assert "route_matching_rules" not in tables, f"потянулись правила маршрутов: {tables}"
    assert counter["n"] == 3, f"ожидались маршруты+stages+operations, получили {tables}"


async def test_section_ref_does_not_load_section_relationships(
    session: AsyncSession,
) -> None:
    """`SectionRef` не грузит `user_sections`/`spg_sections` — в отличие от Section.

    Проверка намеренно не «число запросов упало»: количество SQL меняется по
    самым разным причинам и такой тест ничего не защищает. Здесь ловится
    конкретная связь — если `load_section_refs` снова начнёт отдавать
    ORM-`Section`, появятся `user_sections` и `spg_sections`, и тест упадёт.
    """
    section = Section(
        code="T303-REF", name="Проба проекции", sort_order=951, type="production"
    )
    session.add(section)
    await session.flush()

    seen: list[str] = []

    def _before(_conn, _cursor, statement, _params, _ctx, _many):
        flat = " ".join(statement.split())
        if "FROM user_sections" in flat or "FROM spg_sections" in flat:
            seen.append(flat[:70])

    sync_engine = session.bind.sync_engine  # type: ignore[union-attr]
    event.listen(sync_engine, "before_cursor_execute", _before)
    try:
        refs = await load_section_refs(session, ids={section.id})
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before)

    assert seen == [], f"поехали связи секций: {seen}"
    ref = refs[section.id]
    assert (ref.code, ref.name, ref.type) == ("T303-REF", "Проба проекции", "production")


async def test_routes_sections_cache_returns_section_refs(
    session: AsyncSession,
) -> None:
    """`routes._load_sections_cache` отдаёт проекцию, а не ORM-объекты.

    Структурная страховка на саму правку #303: если кто-то вернёт туда
    `select(Section)`, появятся четыре запроса вместо одного. Значения
    проверяются на равенство — ответ ручки не меняется.
    """
    section = Section(
        code="T303-CACHE", name="Проба кэша", sort_order=952, type="production"
    )
    session.add(section)
    await session.flush()
    route = ProductionRoute(code="T303-CACHE", name="Проба кэша", sort_order=952)
    session.add(route)
    await session.flush()
    session.add(RouteStage(route_id=route.id, sequence=1, section_id=section.id))
    await session.commit()

    staged = (
        await session.scalars(
            select(ProductionRoute)
            .where(ProductionRoute.id == route.id)
            .options(selectinload(ProductionRoute.stages))
        )
    ).one()

    cache = await routes_api._load_sections_cache([staged], session)
    ref = cache[section.id]
    assert isinstance(ref, SectionRef)
    assert not isinstance(ref, Section)
    assert (ref.code, ref.name, ref.type) == ("T303-CACHE", "Проба кэша", "production")
    # поля ответа карточки маршрута
    fields = routes_api._section_step_fields(ref)
    assert fields == {
        "section_code": "T303-CACHE",
        "section_name": "Проба кэша",
        "icon": None,
        "icon_color": None,
        "section_type": "production",
    }
