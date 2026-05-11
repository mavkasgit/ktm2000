import pytest

from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
)
from app.models.route import ProductionRoute, RouteSignatureRule
from app.models.routing import RouteOperationFamily, RouteOutputKind
from app.services.route_matcher import RouteSignature, find_route, resolve_position_route


@pytest.mark.asyncio
async def test_find_route_prefers_exact_over_wildcard(session) -> None:
    route_exact = ProductionRoute(name="Exact route", is_active=True)
    route_wildcard = ProductionRoute(name="Wildcard route", is_active=True)
    session.add_all([route_exact, route_wildcard])
    await session.flush()

    session.add_all(
        [
            RouteSignatureRule(
                route_id=route_wildcard.id,
                operation_family=RouteOperationFamily.PRESS,
                output_kind=RouteOutputKind.finished_good,
                has_pack_ops=None,
                priority=100,
                is_active=True,
            ),
            RouteSignatureRule(
                route_id=route_exact.id,
                operation_family=RouteOperationFamily.PRESS,
                output_kind=RouteOutputKind.finished_good,
                has_pack_ops=True,
                priority=10,
                is_active=True,
            ),
        ]
    )
    await session.flush()

    route, checked = await find_route(
        session,
        RouteSignature(
            operation_family=RouteOperationFamily.PRESS,
            output_kind=RouteOutputKind.finished_good,
            has_pack_ops=True,
        ),
    )
    assert route is not None
    assert route.id == route_exact.id
    assert len(checked) == 2


@pytest.mark.asyncio
async def test_find_route_uses_priority_then_id(session) -> None:
    route_low = ProductionRoute(name="Low", is_active=True)
    route_high = ProductionRoute(name="High", is_active=True)
    session.add_all([route_low, route_high])
    await session.flush()

    session.add_all(
        [
            RouteSignatureRule(
                route_id=route_low.id,
                operation_family=RouteOperationFamily.DRILL,
                output_kind=RouteOutputKind.finished_good,
                has_pack_ops=False,
                priority=1,
                is_active=True,
            ),
            RouteSignatureRule(
                route_id=route_high.id,
                operation_family=RouteOperationFamily.DRILL,
                output_kind=RouteOutputKind.finished_good,
                has_pack_ops=False,
                priority=50,
                is_active=True,
            ),
        ]
    )
    await session.flush()

    route, _ = await find_route(
        session,
        RouteSignature(
            operation_family=RouteOperationFamily.DRILL,
            output_kind=RouteOutputKind.finished_good,
            has_pack_ops=False,
        ),
    )
    assert route is not None
    assert route.id == route_high.id


@pytest.mark.asyncio
async def test_semi_finished_wildcard_has_pack_ops(session) -> None:
    route_sf = ProductionRoute(name="Semi-finished", is_active=True)
    session.add(route_sf)
    await session.flush()

    session.add(
        RouteSignatureRule(
            route_id=route_sf.id,
            operation_family=RouteOperationFamily.PACK,
            output_kind=RouteOutputKind.semi_finished_shipment,
            has_pack_ops=None,
            priority=20,
            is_active=True,
        )
    )
    await session.flush()

    route_true, _ = await find_route(
        session,
        RouteSignature(
            operation_family=RouteOperationFamily.PACK,
            output_kind=RouteOutputKind.semi_finished_shipment,
            has_pack_ops=True,
        ),
    )
    route_false, _ = await find_route(
        session,
        RouteSignature(
            operation_family=RouteOperationFamily.PACK,
            output_kind=RouteOutputKind.semi_finished_shipment,
            has_pack_ops=False,
        ),
    )
    assert route_true is not None
    assert route_false is not None
    assert route_true.id == route_sf.id
    assert route_false.id == route_sf.id


@pytest.mark.asyncio
async def test_resolve_position_route_manual_has_priority(session) -> None:
    route = ProductionRoute(name="Manual route", is_active=True)
    session.add(route)
    await session.flush()

    pos = PlanPosition(
        production_plan_id=1,
        product_id=None,
        source_type=PlanSourceType.excel_import,
        source_sku="SKU",
        quantity=1,
        source_payload={},
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
        route_id=route.id,
        operation_family=RouteOperationFamily.NONE,
        output_kind=RouteOutputKind.finished_good,
        has_pack_ops=False,
    )
    result = await resolve_position_route(session, pos)
    assert result.source == "manual"
    assert result.route_id == route.id
    assert result.error is None


@pytest.mark.asyncio
async def test_resolve_position_route_no_match_returns_route_not_found(session) -> None:
    pos = PlanPosition(
        production_plan_id=1,
        product_id=None,
        source_type=PlanSourceType.excel_import,
        source_sku="SKU",
        quantity=1,
        source_payload={},
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
        route_id=None,
        operation_family=RouteOperationFamily.DRILL,
        output_kind=RouteOutputKind.finished_good,
        has_pack_ops=False,
    )
    result = await resolve_position_route(session, pos)
    assert result.source == "missing"
    assert result.route_id is None
    assert result.error == "route_not_found"
