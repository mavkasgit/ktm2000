"""Build route names from profile templates with data-driven operation names.

Operation signatures come from SectionOperation reference table.
Derived values (output_kind, shot_op) are set by resolve_signatures
seed rules, with legacy fallback when payload is empty.
"""

from __future__ import annotations

import re

from app.models.route import RouteRuleProfile


def build_route_name(
    profile: RouteRuleProfile,
    included_sections: list[str],
    excluded_sections: set[str],
    resolved_ops: dict[tuple[str, str], str],
    resolved_names: dict[tuple[str, str], str],
    payload: dict | None = None,
) -> str:
    """Build route name using profile.route_name_pattern with data-driven operation names.

    Args:
        profile: RouteRuleProfile with route_name_pattern.
        included_sections: Section codes included in the final route.
        excluded_sections: Section codes excluded from the route.
        resolved_ops: {(section_code, group_code): operation_code}.
        resolved_names: {(section_code, group_code): operation_name} — looked up
            from SectionOperation by the async caller.
        payload: Raw import payload.

    Returns:
        Formatted route name string.
    """
    pattern = profile.route_name_pattern or "{output_kind} - {operations}"
    payload = payload or {}

    values: dict[str, str] = {}

    # output_kind: from resolve_signatures phase; fallback to hardcoded logic
    output_kind = payload.get("output_kind")
    if not output_kind:
        has_pack = "PACKING" in included_sections
        has_wip = "WIP_STOCK" in included_sections
        has_saw = "SAWING" in included_sections
        if has_pack and has_wip and has_saw:
            output_kind = "ГП"
        elif not has_pack and not has_wip and not has_saw:
            output_kind = "П/Ф"
        else:
            output_kind = ""
    values["output_kind"] = output_kind

    # press_op — from resolved_names (was hardcoded "Окно", "Гребёнка", "Пресс")
    has_press = "PRESSING" in included_sections
    values["press_op"] = resolved_names.get(("PRESSING", "PRESS"), "") if has_press else ""

    # drill_op — from resolved_names (was hardcoded "Сверловка")
    has_drill = "DRILLING" in included_sections
    values["drill_op"] = resolved_names.get(("DRILLING", "DRILLING"), "") if has_drill else ""

    # shot_op: from resolve_signatures phase; fallback to hardcoded logic
    shot_op = payload.get("shot_op")
    if not shot_op:
        has_shot = "SHOT_BLAST" in included_sections
        shot_op = "" if has_shot else "Без операций"
    values["shot_op"] = shot_op

    # color — from resolved_names (was hardcoded color map)
    values["color"] = resolved_names.get(("ANODIZING", "ANOD"), "")

    # pack_op — from resolved_names (was hardcoded "Стрейч", "Спанбонд")
    values["pack_op"] = resolved_names.get(("ANODIZING", "PACK"), "")

    # operations: combined list of significant ops
    ops_parts = []
    if values.get("press_op"):
        ops_parts.append(values["press_op"])
    if values.get("drill_op"):
        ops_parts.append(values["drill_op"])
    if values.get("color"):
        ops_parts.append(values["color"])
    values["operations"] = " - ".join(ops_parts)

    # Substitute and clean up
    name = pattern
    for key, val in values.items():
        name = name.replace(f"{{{key}}}", val)

    name = re.sub(r'\{\w+\}', '', name)  # remove unmatched placeholders
    parts = [p.strip() for p in name.split('-') if p.strip()]
    name = ' - '.join(parts)
    return name or "Универсальный"
