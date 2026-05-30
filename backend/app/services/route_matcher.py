from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.imports import ImportBatch
from app.models.production_plan import (
    PlanPosition,
    PlanPositionRouteMatchQuality,
    PlanPositionRouteMatchReason,
    PlanPositionRouteOrigin,
)
from app.models.route import ProductionRoute, RouteRuleProfile
from app.services.route_selection import RouteCandidateDiagnostic, select_route_for_payload
from app.services.route_builder import build_route_from_profile


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
    checked_rules: list[int] = field(default_factory=list)
    required_sections: list[dict] = field(default_factory=list)
    excluded_sections: list[dict] = field(default_factory=list)
    candidate_routes: list[RouteCandidateDiagnostic] = field(default_factory=list)
    selected_route_id: int | None = None
    condition_diagnostics: list[dict] = field(default_factory=list)


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

    # If position has a stored route_id, use it directly without recalculation
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
        
        # Return stored route with its metadata
        return ResolvedRouteInfo(
            route_id=route.id,
            route_name=route.name,
            source=source,
            route_origin=origin,
            route_match_quality=quality,
            route_match_reason=reason,
            route_assigned_at=assigned_at,
            route_manual_confirmed_at=manual_confirmed_at,
            error=None,
        )

    # No stored route_id - check if we have a dynamic route profile
    if position.route_profile_id is not None:
        profile = await db.get(RouteRuleProfile, position.route_profile_id)
        if profile is not None and profile.route_sections:
            # Build dynamic route from profile
            try:
                product = await db.get(Product, position.product_id) if position.product_id is not None else None
                built_route = await build_route_from_profile(db, profile, position.source_payload, position)
                
                if not built_route.error:
                    return ResolvedRouteInfo(
                        route_id=None,  # Dynamic route, no static ProductionRoute
                        route_name=built_route.name or f"Dynamic: {profile.name}",
                        source="dynamic_build",
                        route_origin=PlanPositionRouteOrigin.auto.value,
                        route_match_quality=PlanPositionRouteMatchQuality.exact.value,
                        route_match_reason=PlanPositionRouteMatchReason.selection_rules.value,
                        route_assigned_at=position.route_assigned_at,
                        route_manual_confirmed_at=position.route_manual_confirmed_at,
                        error=None,
                    )
            except Exception:
                pass  # Fall through to normal route selection if dynamic build fails

    # No stored route_id - try to resolve from source_payload
    import_batch = await db.get(ImportBatch, position.import_batch_id) if position.import_batch_id is not None else None
    rule_profile_id = import_batch.rule_profile_id if import_batch is not None else None

    product = await db.get(Product, position.product_id) if position.product_id is not None else None
    selection = await select_route_for_payload(db, position.source_payload, product, profile_id=rule_profile_id)
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
            checked_rules=selection.matched_rule_ids,
            required_sections=selection.required_sections,
            excluded_sections=selection.excluded_sections,
            candidate_routes=selection.candidate_routes,
            selected_route_id=None,
            condition_diagnostics=selection.condition_diagnostics,
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
        checked_rules=selection.matched_rule_ids,
        required_sections=selection.required_sections,
        excluded_sections=selection.excluded_sections,
        candidate_routes=selection.candidate_routes,
        selected_route_id=selection.route.id,
        condition_diagnostics=selection.condition_diagnostics,
    )
