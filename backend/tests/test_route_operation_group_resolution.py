"""Операции участка резолвятся в шаг маршрута (#210).

Правило ``set_operation_by_mapping`` адресует операцию парой
``(section_code, group_code)``. Если в ``group_code`` опечатка, резолв молча
теряется: шаг маршрута берёт первую операцию группы, и доска годами показывает
чужую операцию («Серебро» вместо цвета позиции).

Тесты строят маршрут из настоящего канона — того же, что идёт в БД сидом, —
поэтому опечатка в group_code валит их, а не проходит незамеченной.
"""
from __future__ import annotations

import pytest
from app.models.route import RouteRuleProfile
from app.seeds.canon.models import SelectionRuleDef
from app.seeds.canon.registry import build_plant_config, validate_rule_group_codes
from app.seeds.run_seed import run_full_seed
from app.services.route_builder import _NAME_VAR_MAPPING, build_route_from_profile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _anodizing_steps(session: AsyncSession, payload: dict) -> list[tuple[str, str]]:
    profile = await session.scalar(
        select(RouteRuleProfile).where(RouteRuleProfile.code == "packaging_map_rp")
    )
    assert profile is not None, "Профиль упаковочной карты должен быть засеян"
    built = await build_route_from_profile(session, profile, payload, None)
    assert not built.error, f"Маршрут не собрался: {built.error}"
    return [
        (step.operation_code or "", step.operation_name)
        for step in built.steps
        if step.section_code == "ANODIZING"
    ]


@pytest.mark.asyncio
async def test_color_operation_lands_in_route_step(session: AsyncSession) -> None:
    """Цвет позиции — первая операция участка анодирования, а не первая в группе."""
    await run_full_seed(session, force=True)

    steps = await _anodizing_steps(session, {"color": "медь", "output_kind": "ГП"})

    assert steps[0] == ("ANOD_07", "Медь"), (
        f"Цвет позиции должен стать первой операцией участка, получено {steps}"
    )


@pytest.mark.asyncio
async def test_packaging_is_second_operation_of_anodizing_stage(session: AsyncSession) -> None:
    """Упаковка — вторая операция участка; участок отдаёт обе операции."""
    await run_full_seed(session, force=True)

    for output_kind, expected in (("ГП", "PACK_STRETCH"), ("П/ф", "PACK_SPUNBOND")):
        steps = await _anodizing_steps(session, {"color": "медь", "output_kind": output_kind})
        assert len(steps) == 2, f"{output_kind}: участок должен отдать две операции, получено {steps}"
        assert steps[1][0] == expected, f"{output_kind}: упаковка не разрешилась, получено {steps}"


@pytest.mark.asyncio
async def test_press_operation_lands_in_route_step(session: AsyncSession) -> None:
    """Тот же класс дефекта на участке пресса."""
    await run_full_seed(session, force=True)

    profile = await session.scalar(
        select(RouteRuleProfile).where(RouteRuleProfile.code == "packaging_map_rp")
    )
    built = await build_route_from_profile(session, profile, {"operation": "окно"}, None)

    pressing = [
        step.operation_code
        for step in built.steps
        if step.section_code == "PRESSING"
    ]
    assert pressing == ["PRESS_WINDOW"], f"Операция пресса не разрешилась: {pressing}"


def test_rule_group_code_must_exist_in_section() -> None:
    """Опечатка в group_code правила ломает маршрут молча — канон её не пускает."""
    broken = SelectionRuleDef(
        code="broken_color_rule",
        name="Анод: определение цвета",
        profile_code="packaging_map_rp",
        priority=100,
        is_active=True,
        phase="resolve_operations",
        conditions=[],
        actions=[
            {
                "action": "set_operation_by_mapping",
                "section_code": "ANODIZING",
                "group_code": "ANOD",
                "lookup_field": "color",
                "mapping": [{"keyword": "мед", "operation_code": "ANOD_07"}],
            }
        ],
    )

    with pytest.raises(ValueError, match="unknown group"):
        validate_rule_group_codes([broken], build_plant_config().production.ops)


def test_route_name_slots_point_at_existing_operation_groups() -> None:
    """Слот имени маршрута адресует операцию той же парой, что и правило.

    Правило разбора и сборщик имени маршрута обращаются к операции ключом
    ``(section_code, group_code)`` независимо друг от друга. Если стороны
    разойдутся, резолв отработает, а в имени маршрута окажется прочерк — и
    никто этого не увидит. Тест берёт группы из канона, а не из литерала.
    """
    config = build_plant_config()
    canon_groups = {
        (op.section_code, op.group_code)
        for op in config.production.ops
        if op.group_code
    }

    missing = [
        f"{var_name}={section_code}/{group_code}"
        for var_name, (section_code, group_code) in _NAME_VAR_MAPPING.items()
        if (section_code, group_code) not in canon_groups
    ]

    assert not missing, f"слоты имени маршрута указывают на несуществующие группы: {missing}"
