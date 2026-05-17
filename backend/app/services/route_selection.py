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
    condition_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    normalize_applied_actions: list[dict[str, Any]] = field(default_factory=list)
    ctx_snapshot: dict[str, Any] = field(default_factory=dict)
    route_select_matched_rule_ids: list[int] = field(default_factory=list)


def build_route_rule_context(source_payload: dict[str, Any] | None, product: Product | None = None) -> dict[str, Any]:
    payload = source_payload or {}
    return {
        "excel": payload.get("raw_columns") or payload.get("raw_excel_row") or {},
        "excel_meta": payload.get("raw_columns_meta") or [],
        "payload": payload,
        "product": _product_context(product),
        "ctx": {},  # mutable context for normalize phase
    }


def _normalize_template_mapping(mapping: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(mapping, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, value in mapping.items():
        key_text = str(key).strip()
        if not key_text:
            continue
        header: str | None = None
        if isinstance(value, dict):
            raw_header = value.get("header")
            if raw_header is not None:
                header = str(raw_header).strip()
        elif value is not None:
            header = str(value).strip()
        if header:
            normalized[key_text] = header
    return normalized


def _set_nested(ctx: dict[str, Any], parts: list[str], value: Any) -> None:
    """Set a value in ctx at the given dotted path."""
    current = ctx
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def _add_to_nested(ctx: dict[str, Any], parts: list[str], value: Any) -> None:
    """Add a value to a list in ctx at the given dotted path, creating the list if needed."""
    current = ctx
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    target = current.get(parts[-1])
    if target is None:
        current[parts[-1]] = []
    elif not isinstance(target, list):
        current[parts[-1]] = [target]
    current[parts[-1]].append(value)


def _remove_from_nested(ctx: dict[str, Any], parts: list[str], value: Any) -> None:
    """Remove a value from a list in ctx, or delete the key entirely."""
    current = ctx
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return
        current = current[part]
    if not isinstance(current, dict):
        return
    target = current.get(parts[-1])
    if isinstance(target, list) and value in target:
        target.remove(value)
        if not target:
            del current[parts[-1]]
    elif target == value:
        del current[parts[-1]]


def _apply_dsl_action(ctx: dict[str, Any], action: Action) -> dict[str, Any] | None:
    """Apply a DSL action (set/add/remove) to ctx. Returns diagnostic record or None."""
    path = action.get("path", "")
    if not path.startswith("ctx."):
        return None
    parts = path.split(".")[1:]  # strip "ctx"
    value = action.get("value")
    action_kind = action.get("action", "")
    if action_kind == "set":
        _set_nested(ctx, parts, value)
        return {"action": "set", "path": path, "value": value}
    elif action_kind == "add":
        _add_to_nested(ctx, parts, value)
        return {"action": "add", "path": path, "value": value}
    elif action_kind == "remove":
        _remove_from_nested(ctx, parts, value)
        return {"action": "remove", "path": path, "value": value}
    return None


def _load_rules_by_phase(
    rules: list[RouteSelectionRule],
    phase: str,
) -> list[RouteSelectionRule]:
    """Filter rules by phase. Rules without phase field default to 'route_select'."""
    return [r for r in rules if (r.phase if hasattr(r, "phase") else "route_select") == phase]


async def select_route_for_payload(
    db: AsyncSession,
    source_payload: dict[str, Any] | None,
    product: Product | None = None,
    profile_id: int | None = None,
    template_column_mapping: dict[str, Any] | None = None,
) -> RouteSelectionResult:
    context = build_route_rule_context(source_payload, product)
    normalized_mapping = _normalize_template_mapping(template_column_mapping)
    if normalized_mapping:
        context["template_mapping"] = normalized_mapping
    all_rules = await load_selection_rules_for_profile(db, profile_id=profile_id)

    # Phase 1: normalize — apply set/add/remove actions to ctx
    normalize_rules = _load_rules_by_phase(all_rules, "normalize")
    normalize_applied_actions: list[dict[str, Any]] = []
    for rule in normalize_rules:
        conditions = list(rule.conditions or [])
        conditions_matched = True
        for condition_index, condition in enumerate(conditions):
            matched, _diagnostic = _evaluate_condition_with_diagnostic(context, condition)
            if not matched:
                conditions_matched = False
                break
        if not conditions_matched:
            continue
        for action in rule.actions or []:
            result = _apply_dsl_action(context["ctx"], action)
            if result is not None:
                normalize_applied_actions.append({**result, "rule_id": rule.id, "rule_code": rule.code})

    ctx = context["ctx"]

    # Phase 2: route_select — evaluate rules and collect section constraints
    select_rules = _load_rules_by_phase(all_rules, "route_select")
    matched_rule_ids: list[int] = []
    route_select_matched_rule_ids: list[int] = []
    required: set[int] = set()
    excluded: set[int] = set()
    controlled: set[int] = set()
    condition_diagnostics: list[dict[str, Any]] = []

    # Collect controlled sections from all rules (for scoring)
    for rule in all_rules:
        for action in rule.actions or []:
            section_id = _int_or_none(action.get("section_id"))
            if section_id is not None:
                controlled.add(section_id)

    for rule in select_rules:
        actions = list(rule.actions or [])
        for action in actions:
            section_id = _int_or_none(action.get("section_id"))
            if section_id is not None:
                controlled.add(section_id)

        conditions = list(rule.conditions or [])
        conditions_matched = True
        for condition_index, condition in enumerate(conditions):
            matched, diagnostic = _evaluate_condition_with_diagnostic(context, condition)
            diagnostic["rule_id"] = rule.id
            diagnostic["rule_code"] = rule.code
            diagnostic["rule_name"] = rule.name
            diagnostic["rule_priority"] = rule.priority
            diagnostic["condition_index"] = condition_index
            condition_diagnostics.append(diagnostic)
            if not matched:
                conditions_matched = False
        if not conditions_matched:
            continue

        matched_rule_ids.append(rule.id)
        route_select_matched_rule_ids.append(rule.id)
        for action in actions:
            action_kind = str(action.get("action") or "")
            section_id = _int_or_none(action.get("section_id"))
            if action_kind == "require_section" and section_id is not None:
                required.add(section_id)
            elif action_kind == "exclude_section" and section_id is not None:
                excluded.add(section_id)

    # Merge section constraints from ctx (set by normalize phase)
    ctx_required = ctx.get("required_sections")
    ctx_excluded = ctx.get("excluded_sections")
    if isinstance(ctx_required, list):
        required.update(ctx_required)
    if isinstance(ctx_excluded, list):
        excluded.update(ctx_excluded)

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
            condition_diagnostics=condition_diagnostics,
            normalize_applied_actions=normalize_applied_actions,
            ctx_snapshot=dict(ctx),
            route_select_matched_rule_ids=route_select_matched_rule_ids,
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
            condition_diagnostics=condition_diagnostics,
            normalize_applied_actions=normalize_applied_actions,
            ctx_snapshot=dict(ctx),
            route_select_matched_rule_ids=route_select_matched_rule_ids,
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
        condition_diagnostics=condition_diagnostics,
        normalize_applied_actions=normalize_applied_actions,
        ctx_snapshot=dict(ctx),
        route_select_matched_rule_ids=route_select_matched_rule_ids,
    )


async def load_selection_rules_for_profile(
    db: AsyncSession,
    *,
    profile_id: int | None,
) -> list[RouteSelectionRule]:
    """Load active selection rules with deterministic ordering:
    global rules first, then profile rules; inside each group priority desc, id asc.
    """
    stmt = select(RouteSelectionRule).where(RouteSelectionRule.is_active.is_(True))
    if profile_id is None:
        stmt = stmt.where(RouteSelectionRule.profile_id.is_(None))
    else:
        stmt = stmt.where(
            (RouteSelectionRule.profile_id.is_(None)) | (RouteSelectionRule.profile_id == profile_id)
        )

    rules = (await db.execute(stmt)).scalars().all()
    return sorted(
        rules,
        key=lambda rule: (
            0 if rule.profile_id is None else 1,
            -rule.priority,
            rule.id,
        ),
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
    matched, _diagnostic = _evaluate_condition_with_diagnostic(context, condition)
    return matched


def _evaluate_condition_with_diagnostic(context: dict[str, Any], condition: Condition) -> tuple[bool, dict[str, Any]]:
    source = str(condition.get("source") or "payload")
    field_path = str(condition.get("field_path") or "")
    operator = str(condition.get("operator") or "equals")
    expected = condition.get("value")
    case_sensitive = bool(condition.get("case_sensitive", False))
    actual, lookup = _lookup_context_value_with_details(context, source, field_path, condition)
    diagnostic: dict[str, Any] = {
        "source": source,
        "field_path": field_path,
        "operator": operator,
        "expected": expected,
        "case_sensitive": case_sensitive,
        "actual": actual,
        "resolved_by": lookup.get("resolved_by"),
        "excel_column_index": lookup.get("excel_column_index"),
        "excel_column_letter": lookup.get("excel_column_letter"),
        "excel_header": lookup.get("excel_header"),
        "excel_actual_column_index": lookup.get("excel_actual_column_index"),
        "excel_actual_column_letter": lookup.get("excel_actual_column_letter"),
        "excel_actual_header": lookup.get("excel_actual_header"),
        "excel_header_match": lookup.get("excel_header_match"),
        "issues": list(lookup.get("issues") or []),
    }

    if operator == "empty":
        matched = _is_empty(actual)
        diagnostic["matched"] = matched
        return matched, diagnostic
    if operator == "not_empty":
        matched = not _is_empty(actual)
        diagnostic["matched"] = matched
        return matched, diagnostic

    actual_values = _list_values(actual)
    if operator in {"in", "not_in"}:
        expected_values = _list_values(expected)
        matched = any(_equals(actual_value, expected_value, case_sensitive=case_sensitive) for actual_value in actual_values for expected_value in expected_values)
        result = matched if operator == "in" else not matched
        diagnostic["matched"] = result
        return result, diagnostic

    if operator in {"contains", "not_contains"}:
        matched = any(_contains(actual_value, expected, case_sensitive=case_sensitive) for actual_value in actual_values)
        result = matched if operator == "contains" else not matched
        diagnostic["matched"] = result
        return result, diagnostic

    if operator in {"equals", "not_equals"}:
        matched = any(_equals(actual_value, expected, case_sensitive=case_sensitive) for actual_value in actual_values)
        result = matched if operator == "equals" else not matched
        diagnostic["matched"] = result
        return result, diagnostic

    if operator == "regex":
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = "" if expected is None else str(expected)
        try:
            matched = any(re.search(pattern, "" if value is None else str(value), flags=flags) is not None for value in actual_values)
            diagnostic["matched"] = matched
            return matched, diagnostic
        except re.error:
            diagnostic["matched"] = False
            diagnostic["issues"] = [*diagnostic["issues"], "regex_error"]
            return False, diagnostic

    diagnostic["matched"] = False
    return False, diagnostic


def _lookup_context_value(context: dict[str, Any], source: str, field_path: str) -> Any:
    value, _details = _lookup_context_value_with_details(context, source, field_path, {})
    return value


def _lookup_context_value_with_details(
    context: dict[str, Any],
    source: str,
    field_path: str,
    condition: Condition | None,
) -> tuple[Any, dict[str, Any]]:
    if source == "ctx":
        root = context.get("ctx") or {}
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
                return None, {"resolved_by": "path"}
        return current, {"resolved_by": "path"}

    if source == "excel":
        return _lookup_excel_context_value(context, field_path, condition or {})

    root = context.get(source) or {}
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
            return None, {"resolved_by": "path"}
    return current, {"resolved_by": "path"}


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


def _lookup_excel_context_value(
    context: dict[str, Any],
    field_path: str,
    condition: Condition,
) -> tuple[Any, dict[str, Any]]:
    root = context.get("excel") or {}
    excel_meta = context.get("excel_meta") or []
    template_mapping = context.get("template_mapping") or {}

    field_path_normalized = _normalize_key(field_path) if field_path else ""
    requested_index = _int_or_none(condition.get("excel_column_index"))
    requested_letter = str(condition.get("excel_column_letter") or "").strip()
    expected_header = str(condition.get("excel_header") or "").strip()
    expected_header_normalized = _normalize_key(expected_header) if expected_header else ""

    details: dict[str, Any] = {
        "resolved_by": "header",
        "excel_column_index": requested_index,
        "excel_column_letter": requested_letter or None,
        "excel_header": expected_header or None,
        "excel_actual_column_index": None,
        "excel_actual_column_letter": None,
        "excel_actual_header": None,
        "excel_header_match": None,
        "issues": [],
    }

    # 0) Resolve field_path through template column mapping (system_key → header_name)
    if template_mapping and field_path in template_mapping:
        mapped_header = template_mapping[field_path]
        if isinstance(root, dict) and mapped_header in root:
            details["resolved_by"] = "template_mapping"
            details["excel_actual_header"] = mapped_header
            return root[mapped_header], details
        # Try normalized match
        mapped_normalized = _normalize_key(mapped_header)
        if isinstance(root, dict):
            for key, value in root.items():
                if _normalize_key(str(key)) == mapped_normalized:
                    details["resolved_by"] = "template_mapping"
                    details["excel_actual_header"] = str(key)
                    return value, details

    # 1) Prefer explicit column index binding.
    if requested_index is not None and isinstance(excel_meta, list):
        index_match = next(
            (
                column
                for column in excel_meta
                if _int_or_none(column.get("index")) == requested_index
            ),
            None,
        )
        if index_match is not None:
            actual_header = str(index_match.get("header") or "")
            details["excel_actual_column_index"] = _int_or_none(index_match.get("index"))
            details["excel_actual_column_letter"] = str(index_match.get("letter") or "") or None
            details["excel_actual_header"] = actual_header or None
            header_match = True
            if expected_header_normalized:
                header_match = _normalize_key(actual_header) == expected_header_normalized
            details["excel_header_match"] = header_match
            if not header_match:
                details["issues"] = [*details["issues"], "excel_header_mismatch"]
            if header_match:
                details["resolved_by"] = "index"
                return index_match.get("value"), details
        else:
            details["issues"] = [*details["issues"], "excel_column_missing"]

    # 2) Backward-compatible fallback by exact/normalized header (field_path).
    if isinstance(root, dict) and field_path in root:
        details["resolved_by"] = "header" if requested_index is None else "header_fallback"
        return root[field_path], details

    if isinstance(root, dict) and field_path_normalized:
        for key, value in root.items():
            if _normalize_key(str(key)) == field_path_normalized:
                details["resolved_by"] = "header" if requested_index is None else "header_fallback"
                return value, details

    # 3) Fallback by explicit excel_header when provided.
    if isinstance(root, dict) and expected_header:
        if expected_header in root:
            details["resolved_by"] = "explicit_header"
            return root[expected_header], details
        for key, value in root.items():
            if _normalize_key(str(key)) == expected_header_normalized:
                details["resolved_by"] = "explicit_header"
                return value, details

    if requested_index is not None:
        details["issues"] = [*details["issues"], "excel_fallback_not_found"]
    return None, details


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
