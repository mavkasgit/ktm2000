"""Route selection engine: evaluates rules against import payload and selects the best matching route."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import RouteSelectionRule
from app.models.section import Section
from app.models.route import ProductionRoute, RouteStep, SectionOperation


@dataclass
class RouteSelectionResult:
    route_id: int | None = None
    route_name: str | None = None
    match_reason: str | None = None
    matched_rule_ids: list[int] = field(default_factory=list)
    required_sections: set[int] = field(default_factory=set)
    excluded_sections: set[int] = field(default_factory=set)
    selected_operations: dict[int, str] = field(default_factory=dict)  # section_id -> operation_code
    candidate_routes: list[int] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


def _get_nested_value(data: dict, path: str) -> Any:
    """Traverse a dict using dot-separated path."""
    keys = path.split(".")
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return None
        if current is None:
            return None
    return current


def _evaluate_condition(condition: dict, payload: dict, product: Any | None, raw_columns: dict) -> bool:
    """Evaluate a single rule condition against the available data sources."""
    source = condition.get("source", "payload")
    field_path = condition.get("field_path", "")
    operator = condition.get("operator", "equals")
    expected = condition.get("value")
    case_sensitive = condition.get("case_sensitive", False)

    # Resolve value from source
    if source == "excel":
        actual = raw_columns.get(field_path)
    elif source == "payload":
        actual = _get_nested_value(payload, field_path)
    elif source == "product":
        if product is None:
            actual = None
        else:
            actual = getattr(product, field_path, None)
            # Handle boolean fields stored as strings
            if isinstance(actual, bool):
                pass  # keep as bool
    else:
        actual = None

    # Normalize for comparison
    if not case_sensitive and isinstance(actual, str):
        actual = actual.lower()
        if isinstance(expected, str):
            expected = expected.lower()

    # Apply operator
    if operator == "empty":
        return actual is None or actual == "" or actual == []
    elif operator == "not_empty":
        return actual is not None and actual != "" and actual != []
    elif operator == "equals":
        return actual == expected
    elif operator == "not_equals":
        return actual != expected
    elif operator == "contains":
        if actual is None or expected is None:
            return False
        return str(expected) in str(actual)
    elif operator == "not_contains":
        if actual is None or expected is None:
            return True
        return str(expected) not in str(actual)
    elif operator == "in":
        if isinstance(expected, list):
            return actual in expected
        return False
    elif operator == "not_in":
        if isinstance(expected, list):
            return actual not in expected
        return True
    elif operator == "regex":
        if actual is None or expected is None:
            return False
        try:
            return bool(re.search(str(expected), str(actual)))
        except re.error:
            return False

    return False


async def select_route(
    db: AsyncSession,
    payload: dict,
    product: Any | None,
    raw_columns: dict,
    profile_id: int | None,
) -> RouteSelectionResult:
    """Select the best matching production route based on global + profile rules.

    Order:
    1. Fetch global rules (profile_id IS NULL) + profile rules (profile_id = X)
    2. Sort by priority DESC, id ASC
    3. Evaluate conditions (AND within a rule)
    4. Collect require_section / exclude_section actions
    5. Check conflicts (required ∩ excluded)
    6. Filter candidate routes
    7. Score: fewer extras → sort_order → id
    """
    result = RouteSelectionResult()

    # Step 1: Fetch rules
    stmt = select(RouteSelectionRule).where(
        RouteSelectionRule.is_active == True,
    )
    if profile_id is not None:
        stmt = stmt.where(
            (RouteSelectionRule.profile_id.is_(None)) | (RouteSelectionRule.profile_id == profile_id)
        )
    else:
        stmt = stmt.where(RouteSelectionRule.profile_id.is_(None))

    stmt = stmt.order_by(RouteSelectionRule.priority.desc(), RouteSelectionRule.id.asc())
    rules = (await db.execute(stmt)).scalars().all()
    result.diagnostics["rules_evaluated"] = len(rules)

    # Step 2-4: Evaluate rules and collect actions
    required_sections: set[int] = set()
    excluded_sections: set[int] = set()
    selected_operations: dict[int, str] = {}  # section_id -> operation_code
    matched_rule_ids: list[int] = []

    for rule in rules:
        conditions = rule.conditions or []
        # All conditions must pass (AND)
        if all(_evaluate_condition(cond, payload, product, raw_columns) for cond in conditions):
            matched_rule_ids.append(rule.id)
            for action in (rule.actions or []):
                section_id = action.get("section_id")
                action_type = action.get("action")
                if action_type == "require_section" and section_id is not None:
                    required_sections.add(section_id)
                elif action_type == "exclude_section" and section_id is not None:
                    excluded_sections.add(section_id)
                elif action_type == "set_operation" and section_id is not None:
                    op_code = action.get("operation_code")
                    if op_code:
                        selected_operations[section_id] = op_code

    result.matched_rule_ids = matched_rule_ids
    result.required_sections = required_sections
    result.excluded_sections = excluded_sections
    result.selected_operations = selected_operations
    result.diagnostics["required_section_ids"] = list(required_sections)
    result.diagnostics["excluded_section_ids"] = list(excluded_sections)
    result.diagnostics["selected_operations"] = selected_operations

    # Step 5: Check for conflicts
    conflict = required_sections & excluded_sections
    if conflict:
        result.match_reason = "route_rule_conflict"
        result.diagnostics["conflicting_section_ids"] = list(conflict)
        return result

    # Step 6: Fetch all active routes with their steps
    from sqlalchemy.orm import selectinload

    routes_stmt = (
        select(ProductionRoute)
        .where(ProductionRoute.is_active == True)
        .options(selectinload(ProductionRoute.steps))
    )
    routes = (await db.execute(routes_stmt)).scalars().all()

    # Build section sets for each route
    route_sections: dict[int, set[int]] = {}
    for route in routes:
        section_ids = {step.section_id for step in route.steps}
        route_sections[route.id] = section_ids

    # Filter candidates: must have ALL required, must have NONE of excluded
    candidates = []
    for route in routes:
        sections = route_sections[route.id]
        if not required_sections.issubset(sections):
            continue
        if sections & excluded_sections:
            continue
        candidates.append(route)

    result.candidate_routes = [r.id for r in candidates]
    result.diagnostics["candidate_count"] = len(candidates)

    if not candidates:
        result.match_reason = "no_route_candidate"
        return result

    # Step 7: Score candidates
    controlled_sections = required_sections | excluded_sections

    def score_route(route: ProductionRoute) -> tuple[int, int, int]:
        sections = route_sections[route.id]
        # Fewer extra controlled sections is better
        extras = len(sections & controlled_sections) - len(required_sections)
        return (extras, route.sort_order, route.id)

    candidates.sort(key=score_route)
    best = candidates[0]

    result.route_id = best.id
    result.route_name = best.name
    result.match_reason = "exact"
    result.diagnostics["selected_route_sort_order"] = best.sort_order

    return result
