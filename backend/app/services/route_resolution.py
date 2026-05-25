from __future__ import annotations

from typing import Any


def resolve_anod_operation(source_payload: dict[str, Any] | None) -> str | None:
    """Resolve the specific ANOD operation code from source_payload.

    Route templates store ANOD steps with operation_code=None as placeholders.
    This function extracts the actual operation code (ANOD_01..ANOD_08, PACK_SPUNBOND,
    PACK_STRETCH) from the import payload's operation_code field when it refers to
    an ANOD-related operation.

    Returns None if no specific ANOD operation is found in the payload.
    """
    if not source_payload:
        return None

    operation_code = (source_payload.get("operation_code") or "").strip().upper()

    # ANOD color operations (ANOD_01..ANOD_08)
    if operation_code.startswith("ANOD_"):
        return operation_code

    # Pack operations performed by ANOD section
    if operation_code in ("PACK_SPUNBOND", "PACK_STRETCH"):
        return operation_code

    return None
