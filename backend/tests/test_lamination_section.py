"""#491 (скоуп 27.11.2026): справочник участка «Ламинация».

Проверяем только канон: ``build_plant_config()`` содержит секцию
``LAMINATION`` и 25 операций-декоров ``LAM_<декор>``. Маршрутов, правил
выбора и карточек продуктов здесь нет — это следующие шаги, поэтому секция
обязана отсутствовать в ``route_sections`` профилей.
"""

from __future__ import annotations

from app.seeds.canon import build_plant_config
from app.seeds.canon.models import OperationDef, SectionDef

#: Декоры ламинированных порогов: код операции, имя (ОСВ 27.11.2026).
LAMINATION_OPS: list[tuple[str, str]] = [
    ("LAM_013", "Ламинация: Белый"),
    ("LAM_017", "Ламинация: Дуб"),
    ("LAM_018", "Ламинация: Дуб натуральный"),
    ("LAM_106", "Ламинация: Дуб сибириана"),
    ("LAM_107", "Ламинация: Орех светлый"),
    ("LAM_117", "Ламинация: Дуб деревенский"),
    ("LAM_301", "Ламинация: Клен северный"),
    ("LAM_307", "Ламинация: Дуб топаз"),
    ("LAM_308", "Ламинация: Орех золотой"),
    ("LAM_310", "Ламинация: Орех темный"),
    ("LAM_313", "Ламинация: Черное дерево"),
    ("LAM_408", "Ламинация: Ясень темный"),
    ("LAM_409", "Ламинация: Ясень белый"),
    ("LAM_410", "Ламинация: Дуб кантри"),
    ("LAM_415", "Ламинация: Дуб светлый"),
    ("LAM_417", "Ламинация: Дуб золотой"),
    ("LAM_418", "Ламинация: Дуб античный"),
    ("LAM_614", "Ламинация: Дуб грэй"),
    ("LAM_615", "Ламинация: Дуб верден"),
    ("LAM_616", "Ламинация: Дуб ваниль"),
    ("LAM_617", "Ламинация: Дуб беленый"),
    ("LAM_618", "Ламинация: Дуб снежный"),
    ("LAM_619", "Ламинация: Дуб каньон"),
    ("LAM_620", "Ламинация: Дуб тобакко"),
    ("LAM_717", "Ламинация: Дуб глина"),
]


def _lamination_section(sections: list[SectionDef]) -> SectionDef:
    matches = [s for s in sections if s.code == "LAMINATION"]
    assert len(matches) == 1, "участок LAMINATION должен быть ровно один"
    return matches[0]


def _lamination_ops(ops: list[OperationDef]) -> list[OperationDef]:
    return [op for op in ops if op.section_code == "LAMINATION"]


def test_section_is_declared_in_canon() -> None:
    """Участок — производственный, между анодированием (50) и складом (60)."""
    config = build_plant_config()
    section = _lamination_section(config.production.sections)

    assert section.name == "Ламинация"
    assert section.type == "production"
    assert section.sort_order == 55
    assert section.icon == "Layers"
    assert section.icon_color == "#8B5CF6"
    assert section.is_output_default is False

    sort_orders = {s.code: s.sort_order for s in config.production.sections}
    assert sort_orders["ANODIZING"] < section.sort_order < sort_orders["WIP_STOCK"]


def test_twenty_five_color_operations_in_decor_order() -> None:
    """Одна группа, 25 операций-декоров в порядке возрастания декора."""
    config = build_plant_config()
    ops = _lamination_ops(config.production.ops)

    assert len(ops) == 25
    assert [(op.operation_code, op.operation_name) for op in ops] == LAMINATION_OPS

    for op in ops:
        assert op.group_code == "LAMINATION"
        assert op.group_name == "Ламинация"
        assert op.sort_order == 10
        assert op.is_significant is True
        assert op.operation_type == "production"
        assert op.resolver_type is None
        assert op.resolver_config == {}
        # Палитра и иконки операций появятся вместе с файлами — пока пусто.
        assert op.icon is None
        assert op.icon_color is None


def test_operation_codes_are_unique_within_section() -> None:
    """Правило 4: ``operation_code`` уникален в рамках участка."""
    config = build_plant_config()
    codes = [op.operation_code for op in _lamination_ops(config.production.ops)]

    assert len(codes) == len(set(codes))


def test_section_has_no_routes_yet() -> None:
    """Маршруты и план — отдельный шаг: секции нет в ``route_sections``."""
    config = build_plant_config()
    for profile in config.routing.route_rule_profiles:
        assert "LAMINATION" not in profile.route_sections, (
            f"профиль {profile.code} уже содержит LAMINATION: "
            "маршруты этой задачи не входят (#491)"
        )
