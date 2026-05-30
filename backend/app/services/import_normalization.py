from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_IMPORT_NORMALIZATION_RULES: dict[str, Any] = {}


def default_import_normalization_rules() -> dict[str, Any]:
    return deepcopy(DEFAULT_IMPORT_NORMALIZATION_RULES)


def has_valid_normalization_rules(value: Any) -> bool:
    """Normalization rules are deprecated — always return False."""
    return False


def apply_import_normalization(
    *,
    raw_operation: str | None,
    raw_output_kind: str | None,
    normalization_rules: dict[str, Any] | None,
) -> dict[str, Any]:
    """No-op — normalization is handled by route selection rules now."""
    return {
        "operation_code": None,
        "operation_name": None,
        "additional_pack_operations": [],
        "normalized_pack_op_family": "NONE",
        "output_kind": raw_output_kind,
    }


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
