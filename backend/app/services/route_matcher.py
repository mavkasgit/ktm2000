from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.production_plan import PlanPosition
from app.models.route import ProductionRoute, RouteSignatureRule
from app.models.routing import RouteOperationFamily, RouteOutputKind


@dataclass(slots=True)
class RouteSignature:
    operation_family: RouteOperationFamily
    output_kind: RouteOutputKind
    has_pack_ops: bool


@dataclass(slots=True)
class ResolvedRouteInfo:
    route_id: int | None
    route_name: str | None
    source: str  # "manual" | "auto" | "missing"
    error: str | None = None
    signature: RouteSignature | None = None
    checked_rules: list[int] = field(default_factory=list)


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
) -> tuple[ProductionRoute | None, list[int]]:
    """Resolve active route by canonical signature.

    Precedence:
    1) exact match by has_pack_ops
    2) wildcard match with has_pack_ops IS NULL
    Ties: higher priority first, then smaller rule id.
    """

    rows = (
        await db.execute(
            select(RouteSignatureRule, ProductionRoute)
            .join(ProductionRoute, ProductionRoute.id == RouteSignatureRule.route_id)
            .where(
                ProductionRoute.is_active.is_(True),
                RouteSignatureRule.is_active.is_(True),
                RouteSignatureRule.operation_family == signature.operation_family,
                RouteSignatureRule.output_kind == signature.output_kind,
                or_(
                    RouteSignatureRule.has_pack_ops == signature.has_pack_ops,
                    RouteSignatureRule.has_pack_ops.is_(None),
                ),
            )
            .order_by(
                # exact rule has precedence over wildcard
                RouteSignatureRule.has_pack_ops.is_(None).asc(),
                RouteSignatureRule.priority.desc(),
                RouteSignatureRule.id.asc(),
            )
        )
    ).all()

    checked_rules = [rule.id for rule, _route in rows]
    if not rows:
        return None, checked_rules
    rule, route = rows[0]
    return route, checked_rules


async def resolve_position_route(
    db: AsyncSession,
    position: PlanPosition,
) -> ResolvedRouteInfo:
    """Resolve route strictly from manual override + canonical position fields."""
    manual_route_id = position.route_id
    if manual_route_id is not None:
        route = await db.get(ProductionRoute, manual_route_id)
        if route is None:
            return ResolvedRouteInfo(
                route_id=None,
                route_name=None,
                source="manual",
                error="manual_route_not_found",
            )
        if not route.is_active:
            return ResolvedRouteInfo(
                route_id=route.id,
                route_name=route.name,
                source="manual",
                error="manual_route_inactive",
            )
        return ResolvedRouteInfo(
            route_id=route.id,
            route_name=route.name,
            source="manual",
            signature=signature_from_position(position),
        )

    signature = signature_from_position(position)
    if signature is None:
        return ResolvedRouteInfo(
            route_id=None,
            route_name=None,
            source="missing",
            error="route_signature_incomplete",
            signature=None,
            checked_rules=[],
        )

    route, checked_rules = await find_route(db, signature)
    if route is None:
        return ResolvedRouteInfo(
            route_id=None,
            route_name=None,
            source="missing",
            error="route_not_found",
            signature=signature,
            checked_rules=checked_rules,
        )
    return ResolvedRouteInfo(
        route_id=route.id,
        route_name=route.name,
        source="auto",
        error=None,
        signature=signature,
        checked_rules=checked_rules,
    )
