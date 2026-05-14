import pytest

from app.models.production_plan import (
    PlanPosition,
    PlanPositionRouteOrigin,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
)
from app.models.route import ProductionRoute, RouteSelectionRule, RouteStep
from app.models.section import Section
from app.services.route_matcher import resolve_position_route
from app.services.route_selection import _condition_match, select_route_for_payload


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ({"source": "excel", "field_path": "Пробивка/сверловка", "operator": "contains", "value": "сверл"}, True),
        ({"source": "payload", "field_path": "output_kind", "operator": "equals", "value": "finished_good"}, True),
        ({"source": "payload", "field_path": "output_kind", "operator": "not_equals", "value": "semi_finished_shipment"}, True),
        ({"source": "payload", "field_path": "operation", "operator": "not_contains", "value": "окн"}, True),
        ({"source": "payload", "field_path": "output_kind", "operator": "in", "value": ["finished_good"]}, True),
        ({"source": "payload", "field_path": "output_kind", "operator": "not_in", "value": ["semi_finished_shipment"]}, True),
        ({"source": "payload", "field_path": "missing", "operator": "empty", "value": None}, True),
        ({"source": "payload", "field_path": "operation", "operator": "not_empty", "value": None}, True),
        ({"source": "product", "field_path": "skip_shot_blast", "operator": "equals", "value": True}, True),
        ({"source": "payload", "field_path": "operation", "operator": "regex", "value": "св[её]рл"}, True),
    ],
)
def test_rule_condition_operators(condition, expected) -> None:
    context = {
        "excel": {"Пробивка/сверловка": "Сверловка"},
        "payload": {"operation": "сверловка", "output_kind": "finished_good"},
        "product": {"skip_shot_blast": True},
    }

    assert _condition_match(context, condition) is expected


@pytest.mark.asyncio
async def test_route_rule_conflict_returns_error(session) -> None:
    section = Section(code="DRILL", name="Drill", kind="production", is_active=True)
    session.add(section)
    await session.flush()
    session.add(
        RouteSelectionRule(
            code="conflict",
            name="Conflict",
            priority=100,
            is_active=True,
            conditions=[],
            actions=[
                {"action": "require_section", "section_id": section.id},
                {"action": "exclude_section", "section_id": section.id},
            ],
        )
    )
    await session.flush()

    result = await select_route_for_payload(session, {})

    assert result.route is None
    assert result.error == "route_rule_conflict"


@pytest.mark.asyncio
async def test_select_route_scores_by_extra_sections_sort_order_then_id(session) -> None:
    required = Section(code="DRILL", name="Drill", kind="production", is_active=True)
    extra = Section(code="PRESS", name="Press", kind="production", is_active=True)
    session.add_all([required, extra])
    await session.flush()

    route_extra = ProductionRoute(name="Extra", is_active=True, sort_order=0)
    route_late = ProductionRoute(name="Late", is_active=True, sort_order=20)
    route_best = ProductionRoute(name="Best", is_active=True, sort_order=10)
    session.add_all([route_extra, route_late, route_best])
    await session.flush()
    session.add_all(
        [
            RouteStep(route_id=route_extra.id, sequence=1, section_id=required.id, operation_name="DRILL"),
            RouteStep(route_id=route_extra.id, sequence=2, section_id=extra.id, operation_name="PRESS"),
            RouteStep(route_id=route_late.id, sequence=1, section_id=required.id, operation_name="DRILL"),
            RouteStep(route_id=route_best.id, sequence=1, section_id=required.id, operation_name="DRILL"),
            RouteSelectionRule(
                code="need-drill",
                name="Need drill",
                priority=100,
                is_active=True,
                conditions=[],
                actions=[{"action": "require_section", "section_id": required.id}],
            ),
            RouteSelectionRule(
                code="press-if-window",
                name="Press if window",
                priority=90,
                is_active=True,
                conditions=[{"source": "payload", "field_path": "operation", "operator": "contains", "value": "окн", "case_sensitive": False}],
                actions=[{"action": "require_section", "section_id": extra.id}],
            ),
        ]
    )
    await session.flush()

    result = await select_route_for_payload(session, {"operation": "сверл"})

    assert result.route is not None
    assert result.route.id == route_best.id
    assert result.route_match_quality == "exact"


@pytest.mark.asyncio
async def test_select_route_returns_no_candidate_without_fallback(session) -> None:
    required = Section(code="DRILL", name="Drill", kind="production", is_active=True)
    other = Section(code="PRESS", name="Press", kind="production", is_active=True)
    session.add_all([required, other])
    await session.flush()
    route = ProductionRoute(name="Fallback must not be used", is_active=True, sort_order=0)
    session.add(route)
    await session.flush()
    session.add_all(
        [
            RouteStep(route_id=route.id, sequence=1, section_id=other.id, operation_name="PRESS"),
            RouteSelectionRule(
                code="need-drill",
                name="Need drill",
                priority=100,
                is_active=True,
                conditions=[],
                actions=[{"action": "require_section", "section_id": required.id}],
            ),
        ]
    )
    await session.flush()

    result = await select_route_for_payload(session, {})

    assert result.route is None
    assert result.error == "no_route_candidate"


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
        route_origin=PlanPositionRouteOrigin.manual_confirmed,
    )
    result = await resolve_position_route(session, pos)
    assert result.source == "manual"
    assert result.route_id == route.id
    assert result.error is None
