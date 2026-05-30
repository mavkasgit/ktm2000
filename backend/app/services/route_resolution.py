from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import SectionOperation
from app.models.section import Section


# ─── Public API ──────────────────────────────────────────────────────────────


async def resolve_operation(
    db: AsyncSession,
    section_code: str,
    source_payload: dict[str, Any] | None,
) -> str | None:
    """Resolve the concrete operation_code for a placeholder route step.

    Route templates store certain section steps with operation_code=None.
    This function extracts the actual operation code from the import payload
    based on the resolver_type stored in SectionOperation records.

    Returns None if no match found or resolver_type is not set.
    """
    if not source_payload:
        return None

    # Find resolver_type from SectionOperation for this section
    resolver_type, resolver_config = await _get_resolver_config(db, section_code)
    if not resolver_type:
        return None

    operation_code = (source_payload.get("operation_code") or "").strip().upper()

    if resolver_type == "press":
        return _resolve_press(operation_code)

    if resolver_type == "anod":
        return _resolve_anod(operation_code, source_payload, resolver_config)

    return None


# ─── Internal helpers ────────────────────────────────────────────────────────


async def _get_resolver_config(db: AsyncSession, section_code: str) -> tuple[str | None, dict]:
    """Find resolver_type and resolver_config from any SectionOperation of the given section."""
    section = await db.scalar(select(Section).where(Section.code == section_code))
    if not section:
        return None, {}

    sop = await db.scalar(
        select(SectionOperation)
        .where(
            SectionOperation.section_id == section.id,
            SectionOperation.resolver_type.isnot(None),
        )
        .limit(1)
    )
    if not sop:
        return None, {}

    return sop.resolver_type, sop.resolver_config or {}


def _resolve_press(operation_code: str) -> str | None:
    if operation_code in ("PRESS_WINDOW", "PRESS_COMB", "PRESS"):
        return operation_code
    return None


def _resolve_anod(
    operation_code: str,
    source_payload: dict[str, Any],
    resolver_config: dict,
) -> str | None:
    # Explicit ANOD codes
    if operation_code.startswith("ANOD_"):
        return operation_code

    # Pack operations performed by ANOD section
    if operation_code in ("PACK_SPUNBOND", "PACK_STRETCH"):
        return operation_code

    # Resolve by color using config from DB
    color_map = resolver_config.get("color_map", {})
    if not color_map:
        return None

    color = (source_payload.get("color") or "").strip().lower().replace("ё", "е")
    # Find the longest matching token to avoid partial matches
    # (e.g. "черный матовый" should match before "черный")
    best_match: tuple[int, str | None] = (0, None)
    for token, anod_code in color_map.items():
        normalized = token.replace("ё", "е")
        if normalized in color and len(normalized) > best_match[0]:
            best_match = (len(normalized), anod_code)
    return best_match[1]


# ─── Backwards compatibility (sync, hardcoded) ──────────────────────────────
# Kept for existing callers; new code should use the async resolve_operation().

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


def resolve_anod_operation(source_payload: dict[str, Any] | None) -> str | None:
    """Resolve the specific ANOD operation code from source_payload."""
    if not source_payload:
        return None
    operation_code = (source_payload.get("operation_code") or "").strip().upper()
    return _resolve_anod_compat(operation_code, source_payload)


def resolve_press_operation(source_payload: dict[str, Any] | None) -> str | None:
    """Resolve the specific PRESS operation code from source_payload."""
    if not source_payload:
        return None
    operation_code = (source_payload.get("operation_code") or "").strip().upper()
    return _resolve_press(operation_code)


def _resolve_anod_compat(operation_code: str, source_payload: dict[str, Any]) -> str | None:
    if operation_code.startswith("ANOD_"):
        return operation_code
    if operation_code in ("PACK_SPUNBOND", "PACK_STRETCH"):
        return operation_code
    color = (source_payload.get("color") or "").strip().lower().replace("ё", "е")
    best_match: tuple[int, str | None] = (0, None)
    for token, anod_code in ANOD_OPERATION_BY_COLOR.items():
        normalized = token.replace("ё", "е")
        if normalized in color and len(normalized) > best_match[0]:
            best_match = (len(normalized), anod_code)
    return best_match[1]
