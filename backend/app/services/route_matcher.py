from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.production_plan import (
    PlanPosition,
    PlanPositionRouteMatchQuality,
    PlanPositionRouteMatchReason,
    PlanPositionRouteOrigin,
)
from app.models.route import ProductionRoute
from app.models.routing import RouteOperationFamily, RouteOutputKind
from app.services.route_selection import RouteCandidateDiagnostic, select_route_for_payload


@dataclass(slots=True)
class RouteSignature:
    operation_family: RouteOperationFamily
    output_kind: RouteOutputKind
    has_pack_ops: bool


@dataclass(slots=True)
class ResolvedRouteInfo:
    route_id: int | None
    route_name: str | None
    source: str  # compatibility: "manual" | "auto" | "legacy" | "missing"
    route_origin: str | None = None
    route_match_quality: str | None = None
    route_match_reason: str | None = None
    route_assigned_at: datetime | None = None
    route_manual_confirmed_at: datetime | None = None
    error: str | None = None
    signature: RouteSignature | None = None
    checked_rules: list[int] = field(default_factory=list)
    required_sections: list[dict] = field(default_factory=list)
    excluded_sections: list[dict] = field(default_factory=list)
    candidate_routes: list[RouteCandidateDiagnostic] = field(default_factory=list)
    selected_route_id: int | None = None


def signature_from_position(position: PlanPosition) -> RouteSignature | None:
    if position.operation_family is None or position.output_kind is None or position.has_pack_ops is None:
        return None
    return RouteSignature(
        operation_family=position.operation_family,
        output_kind=position.output_kind,
        has_pack_ops=position.has_pack_ops,
    )


async def find_route(
    db: AsyncSession,
    signature: RouteSignature,
) -> tuple[ProductionRoute | None, list[int], str]:
    """Compatibility adapter for old callers.

    New auto-routing is based on source_payload rules. This helper builds a
    minimal payload from the canonical fields and deliberately does not fallback
    to the first active route when no global rule candidate exists.
    """
    result = await select_route_for_payload(
        db,
        {
            "operation_family": signature.operation_family.value,
            "output_kind": signature.output_kind.value,
            "has_pack_ops": signature.has_pack_ops,
        },
    )
    match_kind = "exact" if result.route is not None and result.route_match_quality == "exact" else result.route_match_reason
    return result.route, result.matched_rule_ids, match_kind


def _normalize_origin(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, PlanPositionRouteOrigin):
        return value.value
    raw = str(value)
    return raw or None


def _normalize_quality(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, PlanPositionRouteMatchQuality):
        return value.value
    raw = str(value)
    return raw or None


def _normalize_reason(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, PlanPositionRouteMatchReason):
        return value.value
    raw = str(value)
    return raw or None


def _compat_source_from_origin(origin: str | None, route_id: int | None) -> str:
    if route_id is None:
        return "missing"
    if origin == PlanPositionRouteOrigin.manual_confirmed.value:
        return "manual"
    if origin == PlanPositionRouteOrigin.auto.value:
        return "auto"
    if origin == PlanPositionRouteOrigin.legacy.value:
        return "legacy"
    # Default for old rows that still have route_id but no explicit origin.
    return "legacy"


async def resolve_position_route(
    db: AsyncSession,
    position: PlanPosition,
) -> ResolvedRouteInfo:
    """Resolve route strictly from manual override + canonical position fields."""
    route_id = position.route_id
    origin = _normalize_origin(position.route_origin)
    quality = _normalize_quality(position.route_match_quality)
    reason = _normalize_reason(position.route_match_reason)
    assigned_at = position.route_assigned_at
    manual_confirmed_at = position.route_manual_confirmed_at

    if route_id is not None:
        route = await db.get(ProductionRoute, route_id)
        source = _compat_source_from_origin(origin, route_id)
        if route is None:
            return ResolvedRouteInfo(
                route_id=None,
                route_name=None,
                source=source,
                route_origin=origin,
                route_match_quality=quality,
                route_match_reason=reason,
                route_assigned_at=assigned_at,
                route_manual_confirmed_at=manual_confirmed_at,
                error="manual_route_not_found" if source == "manual" else "route_not_found",
            )
        if not route.is_active:
            return ResolvedRouteInfo(
                route_id=route.id,
                route_name=route.name,
                source=source,
                route_origin=origin,
                route_match_quality=quality,
                route_match_reason=reason,
                route_assigned_at=assigned_at,
                route_manual_confirmed_at=manual_confirmed_at,
                error="manual_route_inactive" if source == "manual" else "active_route_not_found",
            )
        return ResolvedRouteInfo(
            route_id=route.id,
            route_name=route.name,
            source=source,
            route_origin=origin,
            route_match_quality=quality,
            route_match_reason=reason,
            route_assigned_at=assigned_at,
            route_manual_confirmed_at=manual_confirmed_at,
            signature=signature_from_position(position),
        )

    product = await db.get(Product, position.product_id) if position.product_id is not None else None
    selection = await select_route_for_payload(db, position.source_payload, product)
    if selection.route is None:
        return ResolvedRouteInfo(
            route_id=None,
            route_name=None,
            source="missing",
            route_origin=None,
            route_match_quality=None,
            route_match_reason=selection.route_match_reason,
            route_assigned_at=None,
            route_manual_confirmed_at=None,
            error=selection.error or "route_not_found",
            signature=signature_from_position(position),
            checked_rules=selection.matched_rule_ids,
            required_sections=selection.required_sections,
            excluded_sections=selection.excluded_sections,
            candidate_routes=selection.candidate_routes,
            selected_route_id=None,
        )
    return ResolvedRouteInfo(
        route_id=selection.route.id,
        route_name=selection.route.name,
        source="auto",
        route_origin=PlanPositionRouteOrigin.auto.value,
        route_match_quality=selection.route_match_quality or PlanPositionRouteMatchQuality.exact.value,
        route_match_reason=PlanPositionRouteMatchReason.selection_rules.value,
        route_assigned_at=None,
        route_manual_confirmed_at=None,
        error=None,
        signature=signature_from_position(position),
        checked_rules=selection.matched_rule_ids,
        required_sections=selection.required_sections,
        excluded_sections=selection.excluded_sections,
        candidate_routes=selection.candidate_routes,
        selected_route_id=selection.route.id,
    )
