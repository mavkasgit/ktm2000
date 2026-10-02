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

import pytest
from app.models.route import ProductionRoute, RouteRuleProfile
from app.models.spg import StorageProductionGroup
from app.models.user import User
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession


def _counting(session: AsyncSession):
    """Счётчик SQL на время блока."""
    counter = {"n": 0}
    sync_engine = session.bind.sync_engine  # type: ignore[union-attr]

    def _before(*_args, **_kwargs):
        counter["n"] += 1

    event.listen(sync_engine, "before_cursor_execute", _before)
    return counter, lambda: event.remove(sync_engine, "before_cursor_execute", _before)


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

    Раньше список маршрутов стоил 4 запроса: сам маршрут, `stages` (её читает
    `routes.py`) и `rules` — а вот `rules` не читал никто. Теперь остаётся два.
    """
    counter, remove = _counting(session)
    try:
        rows = (
            await session.scalars(
                select(ProductionRoute).order_by(ProductionRoute.id).limit(5)
            )
        ).all()
    finally:
        remove()
    assert rows is not None
    assert counter["n"] == 2, "потянулись правила маршрутов"
