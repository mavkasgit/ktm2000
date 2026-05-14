from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.route import ProductionRoute, RouteSelectionRule, RouteStep
from app.models.section import Section


Condition = dict[str, Any]
Action = dict[str, Any]


@dataclass(slots=True)
class RouteCandidateDiagnostic:
    route_id: int
    route_name: str
    section_ids: list[int]
    section_codes: list[str]
    missing_required_section_ids: list[int] = field(default_factory=list)
    excluded_present_section_ids: list[int] = field(default_factory=list)
    extra_controlled_sections_count: int = 0
    matched: bool = False


@dataclass(slots=True)
class RouteSelectionResult:
    route: ProductionRoute | None
    matched_rule_ids: list[int]
    required_section_ids: list[int]
    excluded_section_ids: list[int]
    required_sections: list[dict[str, Any]]
    excluded_sections: list[dict[str, Any]]
    candidate_routes: list[RouteCandidateDiagnostic]
    route_match_reason: str
    route_match_quality: str | None = None
    error: str | None = None


def build_route_rule_context(source_payload: dict[str, Any] | None, product: Product | None = None) -> dict[str, Any]:
    payload = source_payload or {}
    return {
        "excel": payload.get("raw_columns") or payload.get("raw_excel_row") or {},
        "payload": payload,
        "product": _product_context(product),
    }


async def select_route_for_payload(
    db: AsyncSession,
    source_payload: dict[str, Any] | None,
    product: Product | None = None,
) -> RouteSelectionResult:
    context = build_route_rule_context(source_payload, product)
    rules = (
        await db.execute(
            select(RouteSelectionRule)
            .where(RouteSelectionRule.is_active.is_(True))
            .order_by(RouteSelectionRule.priority.desc(), RouteSelectionRule.id.asc())
        )
    ).scalars().all()

    matched_rule_ids: list[int] = []
    required: set[int] = set()
    excluded: set[int] = set()
    controlled: set[int] = set()

    for rule in rules:
        actions = list(rule.actions or [])
        for action in actions:
            section_id = _int_or_none(action.get("section_id"))
            if section_id is not None:
                controlled.add(section_id)

        conditions = list(rule.conditions or [])
        if not _conditions_match(context, conditions):
            continue

        matched_rule_ids.append(rule.id)
        for action in actions:
            section_id = _int_or_none(action.get("section_id"))
            if section_id is None:
                continue
            action_kind = str(action.get("action") or "")
            if action_kind == "require_section":
                required.add(section_id)
            elif action_kind == "exclude_section":
                excluded.add(section_id)

    conflict = required & excluded
    sections_by_id = await _sections_by_id(db, required | excluded)
    if conflict:
        return RouteSelectionResult(
            route=None,
            matched_rule_ids=matched_rule_ids,
            required_section_ids=sorted(required),
            excluded_section_ids=sorted(excluded),
            required_sections=_section_dicts(required, sections_by_id),
            excluded_sections=_section_dicts(excluded, sections_by_id),
            candidate_routes=[],
            route_match_reason="route_rule_conflict",
            error="route_rule_conflict",
        )

    routes = (
        await db.execute(select(ProductionRoute).where(ProductionRoute.is_active.is_(True)).order_by(ProductionRoute.sort_order, ProductionRoute.id))
    ).scalars().all()
    route_sections = await _route_sections(db, [route.id for route in routes])

    candidates: list[tuple[int, int, int, ProductionRoute, RouteCandidateDiagnostic]] = []
    diagnostics: list[RouteCandidateDiagnostic] = []
    for route in routes:
        section_rows = route_sections.get(route.id, [])
        section_ids = {section_id for section_id, _code in section_rows}
        missing_required = sorted(required - section_ids)
        excluded_present = sorted(excluded & section_ids)
        matched = not missing_required and not excluded_present
        extra_count = len((section_ids & controlled) - required)
        diagnostic = RouteCandidateDiagnostic(
            route_id=route.id,
            route_name=route.name,
            section_ids=[section_id for section_id, _code in section_rows],
            section_codes=[code for _section_id, code in section_rows],
            missing_required_section_ids=missing_required,
            excluded_present_section_ids=excluded_present,
            extra_controlled_sections_count=extra_count,
            matched=matched,
        )
        diagnostics.append(diagnostic)
        if matched:
            candidates.append((extra_count, route.sort_order, route.id, route, diagnostic))

    if not candidates:
        return RouteSelectionResult(
            route=None,
            matched_rule_ids=matched_rule_ids,
            required_section_ids=sorted(required),
            excluded_section_ids=sorted(excluded),
            required_sections=_section_dicts(required, sections_by_id),
            excluded_sections=_section_dicts(excluded, sections_by_id),
            candidate_routes=diagnostics,
            route_match_reason="no_route_candidate",
            error="no_route_candidate",
        )

    extra_count, _sort_order, _route_id, selected, _diagnostic = sorted(candidates, key=lambda item: (item[0], item[1], item[2]))[0]
    return RouteSelectionResult(
        route=selected,
        matched_rule_ids=matched_rule_ids,
        required_section_ids=sorted(required),
        excluded_section_ids=sorted(excluded),
        required_sections=_section_dicts(required, sections_by_id),
        excluded_sections=_section_dicts(excluded, sections_by_id),
        candidate_routes=diagnostics,
        route_match_reason="selection_rules",
        route_match_quality="exact" if extra_count == 0 else "corrected",
        error=None,
    )


async def _sections_by_id(db: AsyncSession, ids: set[int]) -> dict[int, Section]:
    if not ids:
        return {}
    rows = (await db.execute(select(Section).where(Section.id.in_(ids)))).scalars().all()
    return {section.id: section for section in rows}


async def _route_sections(db: AsyncSession, route_ids: list[int]) -> dict[int, list[tuple[int, str]]]:
    if not route_ids:
        return {}
    rows = (
        await db.execute(
            select(RouteStep.route_id, Section.id, Section.code)
            .join(Section, Section.id == RouteStep.section_id)
            .where(RouteStep.route_id.in_(route_ids))
            .order_by(RouteStep.route_id, RouteStep.sequence)
        )
    ).all()
    result: dict[int, list[tuple[int, str]]] = {}
    for route_id, section_id, section_code in rows:
        result.setdefault(route_id, []).append((section_id, section_code))
    return result


def _section_dicts(section_ids: set[int], sections_by_id: dict[int, Section]) -> list[dict[str, Any]]:
    result = []
    for section_id in sorted(section_ids):
        section = sections_by_id.get(section_id)
        result.append(
            {
                "id": section_id,
                "code": section.code if section else None,
                "name": section.name if section else None,
            }
        )
    return result


def _conditions_match(context: dict[str, Any], conditions: list[Condition]) -> bool:
    return all(_condition_match(context, condition) for condition in conditions)


def _condition_match(context: dict[str, Any], condition: Condition) -> bool:
    source = str(condition.get("source") or "payload")
    field_path = str(condition.get("field_path") or "")
    operator = str(condition.get("operator") or "equals")
    expected = condition.get("value")
    case_sensitive = bool(condition.get("case_sensitive", False))
    actual = _lookup_context_value(context, source, field_path)

    if operator == "empty":
        return _is_empty(actual)
    if operator == "not_empty":
        return not _is_empty(actual)

    actual_values = _list_values(actual)
    if operator in {"in", "not_in"}:
        expected_values = _list_values(expected)
        matched = any(_equals(actual_value, expected_value, case_sensitive=case_sensitive) for actual_value in actual_values for expected_value in expected_values)
        return matched if operator == "in" else not matched

    if operator in {"contains", "not_contains"}:
        matched = any(_contains(actual_value, expected, case_sensitive=case_sensitive) for actual_value in actual_values)
        return matched if operator == "contains" else not matched

    if operator in {"equals", "not_equals"}:
        matched = any(_equals(actual_value, expected, case_sensitive=case_sensitive) for actual_value in actual_values)
        return matched if operator == "equals" else not matched

    if operator == "regex":
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = "" if expected is None else str(expected)
        try:
            return any(re.search(pattern, "" if value is None else str(value), flags=flags) is not None for value in actual_values)
        except re.error:
            return False

    return False


def _lookup_context_value(context: dict[str, Any], source: str, field_path: str) -> Any:
    root = context.get(source) or {}
    if source == "excel":
        if isinstance(root, dict) and field_path in root:
            return root[field_path]
        normalized = _normalize_key(field_path)
        for key, value in root.items():
            if _normalize_key(str(key)) == normalized:
                return value
        return None

    current: Any = root
    for part in field_path.split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if 0 <= index < len(current) else None
        else:
            return None
    return current


def _list_values(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple) or isinstance(value, set):
        return list(value)
    if isinstance(value, str) and "," in value:
        return [part.strip() for part in value.split(",")]
    return [value]


def _equals(actual: Any, expected: Any, *, case_sensitive: bool) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return _bool_or_raw(actual) == _bool_or_raw(expected)
    actual_text = _normalize_text(actual, case_sensitive=case_sensitive)
    expected_text = _normalize_text(expected, case_sensitive=case_sensitive)
    return actual_text == expected_text


def _contains(actual: Any, expected: Any, *, case_sensitive: bool) -> bool:
    actual_text = _normalize_text(actual, case_sensitive=case_sensitive)
    expected_text = _normalize_text(expected, case_sensitive=case_sensitive)
    return expected_text in actual_text


def _normalize_text(value: Any, *, case_sensitive: bool) -> str:
    text = "" if value is None else str(value).strip()
    return text if case_sensitive else text.lower()


def _normalize_key(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _bool_or_raw(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "да"}:
            return True
        if lowered in {"false", "0", "no", "нет"}:
            return False
    return value


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list) or isinstance(value, tuple) or isinstance(value, set) or isinstance(value, dict):
        return len(value) == 0
    return False


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _product_context(product: Product | None) -> dict[str, Any]:
    if product is None:
        return {}
    return {
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "type": product.type.value if hasattr(product.type, "value") else product.type,
        "is_active": product.is_active,
        "profile_type": product.profile_type,
        "alloy": product.alloy,
        "color": product.color,
        "anod_type": product.anod_type,
        "skip_shot_blast": product.skip_shot_blast,
        "is_laminated": product.is_laminated,
        "is_catalog_item": product.is_catalog_item,
        "is_paired_profile": product.is_paired_profile,
    }
