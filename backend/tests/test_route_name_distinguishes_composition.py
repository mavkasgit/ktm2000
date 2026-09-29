"""Имя маршрута различает состав маршрута (#226).

Импорт находит уже заведённый маршрут по имени и сверяет его сигнатуру с
сигнатурой строки (#214). Если две строки, у которых разный состав, делят одно
имя, вторая приходит в импорт как `route_signature_conflict` — операция упаковки
или резки по длине в имя не попадала, и строки становились неразличимы.

Тест строится на ORM-моделях, а не на сиде: контракт здесь — слоты имени
(`{packing_op}`, `{saw_op}`) и их привязка к группам операций, а не набор
операций в сиде. Канон операций проверяет
`test_route_operation_group_resolution.test_route_name_slots_point_at_existing_operation_groups`.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import RouteRuleProfile, RouteSelectionRule, SectionOperation
from app.models.section import Section
from app.seeds.route_rule_profiles import ROUTE_RULE_PROFILES
from app.services.route_builder import _NAME_VAR_MAPPING, build_route_from_profile

# Слоты имени, добавленные ради различия состава (#226).
PACKING_SLOT = "packing_op"
SAW_SLOT = "saw_op"

# Слоты адресуют базовые группы участков: правило выбирает операцию в них,
# поэтому значение слота — имя операции («Упаковка», «Склейка», «Резка на
# 2,7 м»), а не код группы.
PACKING_GROUP = "PACKING"
SAWING_GROUP = "SAWING"

PROFILE_SECTIONS = ["SAWING", "PACKING", "FINISHED_STOCK"]


def _seed_pattern() -> str:
    return str(ROUTE_RULE_PROFILES[0]["route_name_pattern"])


async def _seed_sections(session: AsyncSession) -> None:
    """Пила и упаковка с группами состава; склад выпуска — транзитный этап."""
    for code, name, sort_order, section_type in (
        ("SAWING", "Пила", 70, "production"),
        ("PACKING", "Упаковка", 80, "production"),
        ("FINISHED_STOCK", "Склад готовой продукции", 90, "finished_stock"),
    ):
        session.add(Section(code=code, name=name, sort_order=sort_order, type=section_type, is_active=True))
    await session.flush()

    sawing = await session.scalar(select(Section).where(Section.code == "SAWING"))
    packing = await session.scalar(select(Section).where(Section.code == "PACKING"))

    session.add_all([
        # Базовые группы участков — к ним адресованы слоты имени.
        SectionOperation(
            section_id=sawing.id,
            operation_code="SAW",
            operation_name="Резка на пиле",
            group_code=SAWING_GROUP,
            group_name="Резка",
            is_significant=True,
            transforms_dimensions=True,
            sort_order=10,
        ),
        SectionOperation(
            section_id=packing.id,
            operation_code="PACK",
            operation_name="Упаковка",
            group_code=PACKING_GROUP,
            group_name="Упаковка",
            is_significant=True,
            sort_order=10,
        ),
        # Операции состава — отдельными группами, как в сиде (#226); правило
        # выбирает их код в базовой группе участка.
        SectionOperation(
            section_id=sawing.id,
            operation_code="SAW_1350",
            operation_name="Резка на 1,35 м",
            group_code="SAWING_LENGTHS",
            group_name="Резка по длинам",
            is_significant=True,
            transforms_dimensions=True,
            sort_order=20,
        ),
        SectionOperation(
            section_id=sawing.id,
            operation_code="SAW_2700",
            operation_name="Резка на 2,7 м",
            group_code="SAWING_LENGTHS",
            group_name="Резка по длинам",
            is_significant=True,
            transforms_dimensions=True,
            sort_order=30,
        ),
        SectionOperation(
            section_id=packing.id,
            operation_code="PACK_GLUE",
            operation_name="Склейка",
            group_code="PACKING_EXTRA",
            group_name="Упаковка: вид и сборка",
            is_significant=True,
            sort_order=20,
        ),
        SectionOperation(
            section_id=packing.id,
            operation_code="PACK_LENS",
            operation_name="Установка рассеивателя",
            group_code="PACKING_EXTRA",
            group_name="Упаковка: вид и сборка",
            is_significant=True,
            sort_order=30,
        ),
    ])
    await session.commit()


async def _make_profile(session: AsyncSession) -> RouteRuleProfile:
    profile = RouteRuleProfile(
        code="composition_name_profile",
        name="Профиль состава",
        is_active=True,
        priority=1000,
        route_sections=list(PROFILE_SECTIONS),
        route_name_pattern=_seed_pattern(),
    )
    session.add(profile)
    await session.commit()
    return profile


async def _add_composition_rules(
    session: AsyncSession,
    profile: RouteRuleProfile,
    *,
    field: str,
    pairs: list[tuple[str, str, str]],
) -> None:
    """По одному правилу на пару «значение строки → (участок, группа, операция)»."""
    for index, (value, section_code, group_code, operation_code) in enumerate(pairs):
        session.add(RouteSelectionRule(
            code=f"composition_{field}_{index}",
            name=f"Состав: {value}",
            profile_id=profile.id,
            priority=100,
            is_active=True,
            phase="resolve_operations",
            conditions=[
                {"source": "payload", "field_path": field, "operator": "equals", "value": value},
            ],
            actions=[
                {
                    "action": "set_operation",
                    "section_code": section_code,
                    "group_code": group_code,
                    "operation_code": operation_code,
                },
            ],
        ))
    await session.commit()


async def _add_length_rules(
    session: AsyncSession,
    profile: RouteRuleProfile,
    *,
    lookup_field: str = "length",
    pairs: list[tuple[str, str]],
) -> None:
    """Длина реза приходит из карты, а не из равенства: в значении «2,7» есть
    запятая, и оператор ``equals`` по строке её разрезает на список частей."""
    mapping = [
        {"keyword": keyword, "operation_code": operation_code}
        for keyword, operation_code in pairs
    ]
    session.add(RouteSelectionRule(
        code=f"composition_{lookup_field}_map",
        name=f"Состав: длина реза ({lookup_field})",
        profile_id=profile.id,
        priority=100,
        is_active=True,
        phase="resolve_operations",
        conditions=[],
        actions=[
            {
                "action": "set_operation_by_mapping",
                "section_code": "SAWING",
                "group_code": SAWING_GROUP,
                "lookup_field": lookup_field,
                "mapping": mapping,
            },
        ],
    ))
    await session.commit()


async def _build_name(session: AsyncSession, profile: RouteRuleProfile, payload: dict) -> str:
    built = await build_route_from_profile(session, profile, dict(payload))
    assert not built.error, f"Маршрут не собрался: {built.error}"
    return built.name


def test_profile_pattern_carries_composition_slots() -> None:
    """Слоты состава есть в сид-шаблоне имени — иначе значение некуда попасть."""
    pattern = _seed_pattern()
    assert "{" + PACKING_SLOT + "}" in pattern
    assert "{" + SAW_SLOT + "}" in pattern


def test_composition_slots_point_at_own_groups() -> None:
    """Каждый новый слот адресует базовую группу своего участка.

    Адресация базовой группы, а не «вида и сборки»/«по длинам»: новых групп в
    маршруте нет, различает строки операция, которую правило выбирает в базовой
    группе, — и именно её имя обязано попасть в слот.
    """
    assert _NAME_VAR_MAPPING[PACKING_SLOT] == ("PACKING", PACKING_GROUP)
    assert _NAME_VAR_MAPPING[SAW_SLOT] == ("SAWING", SAWING_GROUP)


@pytest.mark.asyncio
async def test_packing_operation_does_not_collapse_route_names(session: AsyncSession) -> None:
    """Две сборки, различающиеся только упаковочной операцией, — разные маршруты.

    До #226 обе строки собирали одно имя, и вторая приходила в импорт как
    `route_signature_conflict`: операция упаковки в имя не попадала.
    """
    await _seed_sections(session)
    profile = await _make_profile(session)
    await _add_composition_rules(session, profile, field="operation", pairs=[
        ("клей", "PACKING", PACKING_GROUP, "PACK_GLUE"),
        ("рассеиватель", "PACKING", PACKING_GROUP, "PACK_LENS"),
    ])

    glue = await _build_name(session, profile, {"output_kind": "ГП", "operation": "клей"})
    lens = await _build_name(session, profile, {"output_kind": "ГП", "operation": "рассеиватель"})

    assert glue != lens, f"Состав упаковки не попал в имя: {glue!r} == {lens!r}"
    assert "Склейка" in glue
    assert "Установка рассеивателя" in lens
    assert "Склейка" not in lens


@pytest.mark.asyncio
async def test_slot_carries_resolved_operation_name(session: AsyncSession) -> None:
    """Значение слота — имя операции, разрешённой правилом, а не код группы.

    Слот «упаковки» у обычной ГП обязан читаться как «Упаковка», а не как
    ``PACKING``: в шаблон идёт отображаемое имя из ``resolved_names``.
    """
    await _seed_sections(session)
    profile = await _make_profile(session)
    await _add_composition_rules(session, profile, field="operation", pairs=[
        ("обычная", "PACKING", PACKING_GROUP, "PACK"),
    ])

    name = await _build_name(session, profile, {"output_kind": "ГП", "operation": "обычная"})

    assert "Упаковка" in name
    assert "PACKING" not in name


@pytest.mark.asyncio
async def test_sawing_length_does_not_collapse_route_names(session: AsyncSession) -> None:
    """То же про длину реза: маршрут по 1,35 м и по 2,7 м — разные."""
    await _seed_sections(session)
    profile = await _make_profile(session)
    await _add_length_rules(session, profile, pairs=[
        ("1,35", "SAW_1350"),
        ("2,7", "SAW_2700"),
    ])

    short = await _build_name(session, profile, {"output_kind": "ГП", "length": "1,35"})
    long = await _build_name(session, profile, {"output_kind": "ГП", "length": "2,7"})

    assert short != long, f"Длина реза не попала в имя: {short!r} == {long!r}"
    assert "Резка на 1,35 м" in short
    assert "Резка на 2,7 м" in long


@pytest.mark.asyncio
async def test_rows_of_same_composition_still_share_one_name(session: AsyncSession) -> None:
    """Регресс: одинаковый состав по-прежнему переиспользует один маршрут.

    Новые слоты не должны запрещать переиспользование — иначе каждая строка
    плана плодила бы свой маршрут.
    """
    await _seed_sections(session)
    profile = await _make_profile(session)
    await _add_composition_rules(session, profile, field="operation", pairs=[
        ("клей", "PACKING", PACKING_GROUP, "PACK_GLUE"),
    ])
    await _add_length_rules(session, profile, pairs=[("2,7", "SAW_2700")])

    first = await build_route_from_profile(session, profile, {"output_kind": "ГП", "operation": "клей", "length": "2,7"})
    second = await build_route_from_profile(session, profile, {"output_kind": "ГП", "operation": "клей", "length": "2,7"})

    assert not first.error and not second.error
    assert first.signature == second.signature, "Одинаковый состав обязан давать одну сигнатуру"
    assert first.name == second.name, f"Одинаковый состав обязан давать одно имя: {first.name!r} != {second.name!r}"


@pytest.mark.asyncio
async def test_absent_operation_leaves_no_placeholder_in_name(session: AsyncSession) -> None:
    """«Без рассеивателя» — признак отсутствия операции, а не отдельная операция.

    Слот без значения схлопывается: в имени нет ни прочерка на его месте, ни
    двойного разделителя — иначе «ГП - -» смотрелось бы как битый маршрут.
    """
    await _seed_sections(session)
    profile = await _make_profile(session)
    await _add_composition_rules(session, profile, field="operation", pairs=[
        ("клей", "PACKING", PACKING_GROUP, "PACK_GLUE"),
    ])

    with_glue = await _build_name(session, profile, {"output_kind": "ГП", "operation": "клей"})
    without = await _build_name(session, profile, {"output_kind": "ГП", "operation": "Без рассеивателя"})

    assert "Склейка" in with_glue
    assert "Склейка" not in without
    assert "Без рассеивателя" not in without
    assert "  " not in without
    assert not without.endswith(" -"), f"Пустой слот оставил висячий разделитель: {without!r}"
    assert "--" not in without
