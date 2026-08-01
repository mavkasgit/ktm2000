"""Pure template engine for route name assembly.

Contains no section codes, operation codes, or human-readable labels.
All domain knowledge (which operations map to which template variables)
lives in the caller (route_builder) and in seed rules (resolve_signatures).
"""

from __future__ import annotations

import re


def build_route_name(
    pattern: str,
    values: dict[str, str],
    *,
    fallback: str = "",
) -> str:
    """Substitute named values into a route name pattern.

    Args:
        pattern: Template with {variable} placeholders,
            e.g. "{output_kind} - {press_op} - {color}".
        values: {variable_name: display_value} — assembled by caller
            from resolved operation names and payload fields.
        fallback: Returned when result is empty after cleanup.

    Returns:
        Formatted route name string.
    """
    name = pattern
    for key, val in values.items():
        name = name.replace(f"{{{key}}}", val)

    name = re.sub(r'\{\w+\}', '', name)  # remove unmatched placeholders
    parts = [p.strip() for p in name.split('-') if p.strip()]
    name = ' - '.join(parts)
    return name or fallback
