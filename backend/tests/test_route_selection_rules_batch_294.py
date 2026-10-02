"""Регресс N+1 списка правил подбора (#294, место 1).

`GET /route-selection-rules` строил ответ поштучно: на каждое правино уходили
запросы за участками, за операциями участка и за профилем. Здесь проверяется,
что список читает справочники один раз и что батч-ответ побайтово совпадает с
поштучным.
"""

from __future__ import annotations

import json

import pytest
from app.api.routes import route_selection_rules as rsr
from app.models.route import (
    RouteRuleProfile,
    RouteSelectionRule,
    SectionOperation,
)
from app.models.section import Section
from sqlalchemy import event, select

from tests.test_routes_seed import _seed_default_sections


def _count_sql(session):
    """Счётчик SQL на время блока с ``try/finally`` — по образцу тестов #290."""
    counter = {"n": 0}
    sync_engine = session.bind.sync_engine

    def _count(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(sync_engine, "before_cursor_execute", _count)
    return counter, lambda: event.remove(sync_engine, "before_cursor_execute", _count)


async def _seed_rules(
    session, count: int, *, code_prefix: str = "p294"
) -> tuple[list[RouteSelectionRule], list[Section]]:
    """count правил, каждое ссылается на свой участок, операцию и профиль."""
    sections = (
        (await session.execute(select(Section).order_by(Section.id).limit(count))).scalars().all()
    )
    if not sections:
        await _seed_default_sections(session)
        sections = (
            (await session.execute(select(Section).order_by(Section.id).limit(count))).scalars().all()
        )
    assert len(sections) == count, "нужно столько участков, сколько правил"

    profiles = []
    for index, section in enumerate(sections):
        profile = RouteRuleProfile(
            code=f"{code_prefix}_prof{index}", name=f"Профиль {index}", is_active=True, priority=index
        )
        session.add(profile)
        await session.flush()
        profiles.append(profile)
        session.add(
            SectionOperation(
                section_id=section.id,
                operation_code=f"OP_{code_prefix}{index}",
                operation_name=f"Операция {index}",
                group_code="GRP",
                group_name="Группа",
                sort_order=0,
                is_significant=True,
            )
        )
    await session.flush()

    rules = []
    for index, (section, profile) in enumerate(zip(sections, profiles, strict=True)):
        rule = RouteSelectionRule(
            code=f"{code_prefix}_rule{index}",
            name=f"Правило {index}",
            profile_id=profile.id,
            priority=100 - index,
            is_active=True,
            phase="route_select",
            conditions=[],
            actions=[
                {"action": "require_section", "section_id": section.id},
                {
                    "action": "set_operation",
                    "section_id": section.id,
                    "group_code": "GRP",
                    "operation_code": f"OP_{code_prefix}{index}",
                },
            ],
        )
        session.add(rule)
        rules.append(rule)
    await session.commit()
    for rule in rules:
        await session.refresh(rule)
    return rules, sections


@pytest.mark.asyncio
async def test_rule_list_batch_matches_per_row(session) -> None:
    """Батч-ответ списка равен поштучному — по всему, что видит клиент."""
    rules, sections = await _seed_rules(session, 5)

    per_row = [await rsr._rule_out(session, rule) for rule in rules]
    batch = await rsr._rule_outs(session, rules)

    def dump(items):
        return json.dumps([item.model_dump() for item in items], sort_keys=True, default=str)

    assert dump(batch) == dump(per_row)
    first = batch[0]
    assert first.actions[0].section_code == sections[0].code
    assert first.actions[0].section_name == sections[0].name
    assert first.actions[1].operation_name == "Операция 0"
    assert (first.profile_code, first.profile_name) == ("p294_prof0", "Профиль 0")



@pytest.mark.asyncio
async def test_rule_list_sql_does_not_grow_with_rules(session) -> None:
    """Число SQL не зависит от числа правил в списке.

    Сверка идёт по двум размерам списка, а не по абсолютному числу: у
    справочников есть и постоянная часть (ленивые связи моделей), и она не
    имеет отношения к N+1. До правки список из n правил стоил до 3n
    запросов — здесь ловится именно эта разница.
    """
    rules, _sections = await _seed_rules(session, 2)
    counter_small, remove_small = _count_sql(session)
    try:
        await rsr._rule_outs(session, rules)
    finally:
        remove_small()

    more, _ = await _seed_rules(session, 2, code_prefix="big")
    counter_big, remove_big = _count_sql(session)
    try:
        await rsr._rule_outs(session, [*rules, *more])
    finally:
        remove_big()

    assert counter_big["n"] == counter_small["n"], (
        f"4 правила дали {counter_big['n']} SQL против {counter_small['n']} у двух"
    )


@pytest.mark.asyncio
async def test_single_rule_out_still_reads_own_reference_data(session) -> None:
    """Одиночный вызов `_rule_out` без снимка работает как раньше.

    Создание и правка правила зовут его напрямую: если бы путь без снимка
    был сломан, эти ручки падали бы, а тесты списка — проходили.
    """
    rules, sections = await _seed_rules(session, 1)

    out = await rsr._rule_out(session, rules[0])

    assert out.actions[0].section_code == sections[0].code
    assert out.actions[0].section_name == sections[0].name
    assert out.actions[1].operation_name == "Операция 0"
    assert out.profile_code == "p294_prof0"
