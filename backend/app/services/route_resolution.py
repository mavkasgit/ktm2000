from __future__ import annotations

from typing import Any

# ─── Operation code lookup tables ────────────────────────────────────────────

ANOD_OPERATION_BY_COLOR = {
    "серебро": "ANOD_01",
    "серебрист": "ANOD_01",
    "золото": "ANOD_02",
    "золот": "ANOD_02",
    "бронза": "ANOD_03",
    "бронз": "ANOD_03",
    "черный": "ANOD_05",
    "черн": "ANOD_05",
    "чёрный": "ANOD_05",
    "чёрн": "ANOD_05",
    "шампань": "ANOD_06",
    "медь": "ANOD_07",
    "мед": "ANOD_07",
    "титан": "ANOD_08",
}

# Sections that use placeholder operation_code=None and resolves from payload.
# Exact matches: PRESS, ANOD
# Suffix matches: *-ANOD (e.g. FG-COMBO-STAGE-ANOD), *-PRESS
_PLACEHOLDER_EXACT = {"PRESS", "ANOD"}


def _is_placeholder_section(section_code: str) -> bool:
    if section_code in _PLACEHOLDER_EXACT:
        return True
    # Suffix-based placeholders
    if section_code.endswith("-ANOD") or section_code.endswith("-PRESS"):
        return True
    return False

# ─── Public API ──────────────────────────────────────────────────────────────


def resolve_operation(
    section_code: str,
    source_payload: dict[str, Any] | None,
) -> str | None:
    """Resolve the concrete operation_code for a placeholder route step.

    Route templates store certain section steps with operation_code=None.
    This function extracts the actual operation code from the import payload
    based on the section type.

    Supported placeholder sections:
      - PRESS / *-PRESS: resolves to PRESS_WINDOW, PRESS_COMB, or PRESS
      - ANOD / *-ANOD:   resolves to ANOD_01..ANOD_08 by color, or PACK_SPUNBOND/PACK_STRETCH

    Returns None if the section does not use placeholders or no match found.
    """
    if not _is_placeholder_section(section_code):
        return None
    if not source_payload:
        return None

    operation_code = (source_payload.get("operation_code") or "").strip().upper()

    if section_code == "PRESS" or section_code.endswith("-PRESS"):
        return _resolve_press(operation_code)

    if section_code == "ANOD" or section_code.endswith("-ANOD"):
        return _resolve_anod(operation_code, source_payload)

    return None


# ─── Internal resolvers ──────────────────────────────────────────────────────


def _resolve_press(operation_code: str) -> str | None:
    if operation_code in ("PRESS_WINDOW", "PRESS_COMB", "PRESS"):
        return operation_code
    return None


def _resolve_anod(operation_code: str, source_payload: dict[str, Any]) -> str | None:
    # Explicit ANOD codes
    if operation_code.startswith("ANOD_"):
        return operation_code

    # Pack operations performed by ANOD section
    if operation_code in ("PACK_SPUNBOND", "PACK_STRETCH"):
        return operation_code

    # Resolve by color
    color = (source_payload.get("color") or "").strip().lower().replace("ё", "е")
    for token, anod_code in ANOD_OPERATION_BY_COLOR.items():
        if token.replace("ё", "е") in color:
            return anod_code

    return None


# ─── Backwards compatibility ─────────────────────────────────────────────────
# Kept for existing callers; new code should use resolve_operation().


def resolve_anod_operation(source_payload: dict[str, Any] | None) -> str | None:
    """Resolve the specific ANOD operation code from source_payload."""
    if not source_payload:
        return None
    operation_code = (source_payload.get("operation_code") or "").strip().upper()
    return _resolve_anod(operation_code, source_payload)


def resolve_press_operation(source_payload: dict[str, Any] | None) -> str | None:
    """Resolve the specific PRESS operation code from source_payload."""
    if not source_payload:
        return None
    operation_code = (source_payload.get("operation_code") or "").strip().upper()
    return _resolve_press(operation_code)
