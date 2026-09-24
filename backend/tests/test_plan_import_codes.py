"""Сторож каталога кодов строк импорта плана (issue #166, спека §3).

Фиксирует классификацию error/warning рядом с правилом статуса
(plan_import_service.plan_import_row_status): новый errors.append /
warnings.append без записи в каталог ломает test_source_appends_classified.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.models.production_plan import PlanChangeItemStatus
from app.services.plan_import_service import (
    PLAN_IMPORT_ERROR_CODES,
    PLAN_IMPORT_WARNING_CODES,
    PLAN_IMPORT_WARNING_PREFIXES,
    classify_plan_import_code,
    plan_import_row_status,
)

# Спека docs/plan-import-spec.md §3 — эталон, дублирует каталог намеренно:
# дрейф каталога мимо спеки должен ломать тест.
SPEC_ERROR_CODES = frozenset(
    {
        "product_not_found",
        "product_inactive",
        "product_pair_not_found",
        "hanger_calc_zero",
        "no_route_candidate",
        "route_rule_conflict",  # значение selection.error (§3: «/ selection.error»)
        "active_route_has_no_steps",
        "route_contains_inactive_section",
        "duplicate_sku_due_date",
        "normal_length_not_found",
    }
)
SPEC_WARNING_BASES = frozenset(
    {
        "hanger_quantity_not_set",
        "input_dimensions_unresolved",
        "product_name_missing",
        "invalid_input_length",
        "invalid_output_length",
        "paired_row_auto_included",
        "plan_group_balance_mismatch",  # фактический row-warning вне спеки §3 (баланс группы)
        "row_selection_applied",
        "row_selection_auto_included",
        "paired_profile_product_unmapped",
    }
)

SERVICES_DIR = Path(__file__).resolve().parent.parent / "app" / "services"
SCANNED_FILES = ("plan_import_service.py", "excel_import.py")
ERROR_ATTRS = {"errors"}
WARNING_ATTRS = {"warnings"}
# Динамические passthrough с классификацией вне append-строки:
# selection.error — RouteSelectionResult.error (значения в ERROR_CODES).
ALLOWED_DYNAMIC_ERRORS = {"selection.error"}


def test_error_catalog_matches_spec():
    assert PLAN_IMPORT_ERROR_CODES == SPEC_ERROR_CODES

def test_warning_catalog_matches_spec():
    assert PLAN_IMPORT_WARNING_CODES | frozenset(PLAN_IMPORT_WARNING_PREFIXES) == SPEC_WARNING_BASES


def test_classify_errors():
    for code in SPEC_ERROR_CODES:
        assert classify_plan_import_code(code) == "error", code


def test_classify_warnings_with_params():
    samples = [
        "product_name_missing",
        "input_dimensions_unresolved",
        "paired_profile_product_unmapped",
        "hanger_quantity_not_set:SKU1",
        "invalid_input_length:row=3",
        "invalid_output_length:row=5",
        "paired_row_auto_included:7",
        "row_selection_applied:1,2,3",
        "row_selection_auto_included:4,5",
        "plan_group_balance_mismatch:in=2700mm,out=2600mm",
    ]
    for code in samples:
        assert classify_plan_import_code(code) == "warning", code


def test_classify_unknown_is_none():
    assert classify_plan_import_code("some_future_code") is None
    assert classify_plan_import_code("raw_length_not_found") is None
    assert classify_plan_import_code("raw_length_substituted:2700→2750") is None


def test_row_status_rule():
    assert plan_import_row_status(["product_not_found"], ["product_name_missing"]) is PlanChangeItemStatus.invalid
    assert plan_import_row_status([], ["product_name_missing"]) is PlanChangeItemStatus.warning
    assert plan_import_row_status([], []) is PlanChangeItemStatus.pending


def _static_head(node: ast.AST) -> str | None:
    """Статическая голова строкового выражения: Constant или f-строка без динамики в префиксе."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                break
        return "".join(parts) or None
    return None


def _iter_appends(tree: ast.AST):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "append":
            continue
        if not isinstance(func.value, ast.Attribute):
            continue
        attr = func.value.attr
        if attr in ERROR_ATTRS:
            side: str | None = "error"
        elif attr in WARNING_ATTRS:
            side = "warning"
        else:
            continue
        if not node.args:
            continue
        yield side, node.args[0], node.lineno


def _dynamic_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            if isinstance(child.value, ast.Name):
                names.add(f"{child.value.id}.{child.attr}")
            else:
                names.add(child.attr)
    return names


def _assignment_statics(tree: ast.AST) -> dict[str, str]:
#: Простые присвоения вида marker = f"код:..." — append(marker) ниже
#: резолвится через эту карту, иначе новый код через переменную ушёл бы от сторожа.
    statics: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name):
            head = _static_head(node.value)
            if head is not None:
                statics[target.id] = head
    return statics


def _check_append(
    *, side: str, arg: ast.AST, location: str, var_statics: dict[str, str], unclassified: list[str],
) -> None:
    head = _static_head(arg)
    if head is None and isinstance(arg, ast.Name) and arg.id in var_statics:
        head = var_statics[arg.id]
    if head is not None:
        base = head.split(":", 1)[0].strip("{} ")
        if not base:
            unclassified.append(f"{location}: пустой статический код")
        elif classify_plan_import_code(base if ":" in head else head) != side:
            unclassified.append(f"{location}: {head!r} не классифицирован как {side}")
        return
    names = _dynamic_names(arg)
    if side == "error" and names <= ALLOWED_DYNAMIC_ERRORS:
        return
    unclassified.append(f"{location}: динамический {side}.append без классификации: {ast.dump(arg)}")


def test_source_appends_classified():
    unclassified: list[str] = []
    for filename in SCANNED_FILES:
        tree = ast.parse((SERVICES_DIR / filename).read_text(encoding="utf-8"))
        var_statics = _assignment_statics(tree)
        for side, arg, lineno in _iter_appends(tree):
            _check_append(
                side=side, arg=arg, location=f"{filename}:{lineno}",
                var_statics=var_statics, unclassified=unclassified,
            )
    assert not unclassified, "Неклассифицированные коды строк импорта:\n" + "\n".join(unclassified)
