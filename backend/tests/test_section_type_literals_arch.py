"""Архитектурный тест: единый владелец литералов ``Section.type``.

Единственный модуль, которому разрешено знать строковые литералы типа участка
(``"production"``, ``"raw_stock"``, ``"wip_stock"``, ``"finished_stock"``,
``"scrap"``, ``"quarantine"``) — это ``app.services.route_storage_classifier``.
Весь остальной код должен звать предикаты (``is_production_section`` и т.п.)
или ссылаться на экспортируемые классификатором константы/наборы.

Тест статически (через ``ast``) сканирует ``backend/app`` и падает, если находит:

* Rule A — прямое сравнение ``<...>.type == "raw_stock"`` (и ``!=``, ``in``,
  ``not in``) со строковым литералом из словаря типов участка;
* Rule B — вызов ``<...>.type.in_([...])`` / ``.notin_([...])`` с такими
  литералами в аргументах;
* Rule C — коллекцию-литерал (``{...}``/``[...]``/``(...)``), содержащую два и
  более разных «складских» литерала — так ловятся локальные копии наборов
  вроде ``STOCK_SECTION_TYPES``.

Тест НЕ ловит докстринги, комментарии, enum-определения (одиночные присваивания
вроде ``SCRAP = "scrap"``), сравнения с enum (``x.type != ProductType.component``)
и сам модуль-классификатор.
"""
from __future__ import annotations

import ast
from pathlib import Path

import app
import app.services.route_storage_classifier as classifier

# Полный словарь литералов типа участка.
SECTION_TYPE_LITERALS = frozenset(
    {"production", "raw_stock", "wip_stock", "finished_stock", "scrap", "quarantine"}
)
# «Складские» литералы (без ``production``): их совместное появление в одной
# коллекции почти наверняка означает ad-hoc классификатор участков.
STORAGE_LITERALS = SECTION_TYPE_LITERALS - {"production"}

APP_ROOT = Path(app.__file__).resolve().parent
CLASSIFIER_PATH = Path(classifier.__file__).resolve()


def _iter_app_files() -> list[Path]:
    return [
        p
        for p in APP_ROOT.rglob("*.py")
        if "__pycache__" not in p.parts and p.resolve() != CLASSIFIER_PATH
    ]


def _str_constants(node: ast.AST) -> list[str]:
    """Строковые литералы верхнего уровня коллекции (Set/List/Tuple)."""
    values: list[str] = []
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                values.append(elt.value)
    return values


def _is_type_attribute(node: ast.AST) -> bool:
    """``True`` для обращения к атрибуту ``.type`` (Section.type, sec.type, ...)."""
    return isinstance(node, ast.Attribute) and node.attr == "type"


def _find_violations(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    violations: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        # Rule A: сравнение <...>.type <op> <литерал>
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            if any(_is_type_attribute(op) for op in operands):
                for op, cmp in zip(node.ops, node.comparators):
                    if isinstance(op, (ast.Eq, ast.NotEq)):
                        for operand in operands:
                            if (
                                isinstance(operand, ast.Constant)
                                and operand.value in SECTION_TYPE_LITERALS
                            ):
                                violations.append(
                                    (node.lineno, f"сравнение .type с '{operand.value}'")
                                )
                    elif isinstance(op, (ast.In, ast.NotIn)):
                        for lit in _str_constants(cmp):
                            if lit in SECTION_TYPE_LITERALS:
                                violations.append(
                                    (node.lineno, f".type in {{... '{lit}' ...}}")
                                )

        # Rule B: <...>.type.in_([...]) / .notin_([...])
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"in_", "notin_"}
            and _is_type_attribute(node.func.value)
        ):
            for arg in node.args:
                candidates = _str_constants(arg)
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    candidates.append(arg.value)
                for lit in candidates:
                    if lit in SECTION_TYPE_LITERALS:
                        violations.append(
                            (node.lineno, f".type.{node.func.attr}(... '{lit}' ...)")
                        )

        # Rule C: коллекция с двумя+ разными складскими литералами
        if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
            found = {lit for lit in _str_constants(node) if lit in STORAGE_LITERALS}
            if len(found) >= 2:
                violations.append(
                    (node.lineno, f"локальный набор типов участка {sorted(found)}")
                )

    return violations


def test_no_direct_section_type_literals_outside_classifier():
    offenders: dict[str, list[tuple[int, str]]] = {}
    for path in _iter_app_files():
        found = _find_violations(path)
        if found:
            offenders[str(path.relative_to(APP_ROOT))] = found

    assert not offenders, (
        "Прямое обращение к литералам Section.type вне классификатора. "
        "Используйте предикаты/константы из app.services.route_storage_classifier:\n"
        + "\n".join(
            f"  app/{file}:{ln} — {msg}"
            for file, items in sorted(offenders.items())
            for ln, msg in items
        )
    )


def test_classifier_still_owns_the_literals():
    """Санити-проверка: классификатор действительно содержит все литералы."""
    owned = classifier.STORAGE_TYPES | {classifier.SECTION_TYPE_PRODUCTION}
    assert owned == SECTION_TYPE_LITERALS - {"quarantine"}
    # ``quarantine`` осознанно удалён — не должен вернуться в наборы.
    assert "quarantine" not in classifier.STORAGE_TYPES
    assert "quarantine" not in classifier.STOCK_TYPES
