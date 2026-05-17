from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.routing import RouteOperationFamily, RouteOutputKind


@dataclass(slots=True)
class CanonicalRouteSignature:
    operation_family: RouteOperationFamily
    output_kind: RouteOutputKind
    has_pack_ops: bool


def normalize_output_kind(value: str | None) -> RouteOutputKind | None:
    if not value:
        return None
    if value in {RouteOutputKind.finished_good.value, RouteOutputKind.semi_finished_shipment.value}:
        return RouteOutputKind(value)
    return None


def normalize_operation_family(*, operation_code: str | None, raw_operation: str | None = None) -> RouteOperationFamily:
    del raw_operation
    code = (operation_code or "").strip().upper()
    if code in {"PRESS_WINDOW", "PRESS_COMB", "PRESS"}:
        return RouteOperationFamily.PRESS
    if code == "DRILL":
        return RouteOperationFamily.DRILL
    if code == "PACK":
        return RouteOperationFamily.PACK
    return RouteOperationFamily.NONE


def extract_additional_pack_codes(additional_pack_operations: list[Any] | None) -> list[str]:
    if not additional_pack_operations:
        return []
    result: list[str] = []
    for item in additional_pack_operations:
        if isinstance(item, dict):
            value = str(item.get("operation_code") or "").strip().upper()
            if value:
                result.append(value)
            continue
        value = str(item or "").strip().upper()
        if value:
            result.append(value)
    return result


def canonical_signature_from_payload(source_payload: dict[str, Any] | None) -> CanonicalRouteSignature | None:
    payload = source_payload or {}
    output_kind = normalize_output_kind(payload.get("output_kind"))
    if output_kind is None:
        return None

    operation_family = normalize_operation_family(
        operation_code=payload.get("operation_code"),
        raw_operation=payload.get("operation"),
    )
    has_pack_ops = bool(extract_additional_pack_codes(payload.get("additional_pack_operations")))

    return CanonicalRouteSignature(
        operation_family=operation_family,
        output_kind=output_kind,
        has_pack_ops=has_pack_ops,
    )
