import pytest

from app.models.product import Product, ProductType
from app.models.route import ProductionRoute, RouteMatchingRule, RouteRuleCondition
from app.services.route_matcher import find_route, _match_conditions


@pytest.mark.asyncio
async def test_default_route_matches_when_no_rules(session) -> None:
    """A route with no rules acts as default fallback and matches any product."""
    route = ProductionRoute(name="Default", is_active=True)
    session.add(route)
    await session.flush()

    product = Product(sku="TEST-1", name="Test", type=ProductType.finished_good, unit="pcs")
    session.add(product)
    await session.flush()

    result = await find_route(session, product)
    assert result is not None
    assert result.name == "Default"


@pytest.mark.asyncio
async def test_rule_exact_match(session) -> None:
    """A rule with conditions matches product with matching field."""
    route = ProductionRoute(name="Box route", is_active=True)
    session.add(route)
    await session.flush()

    rule = RouteMatchingRule(route_id=route.id, priority=10)
    session.add(rule)
    await session.flush()

    session.add(RouteRuleCondition(rule_id=rule.id, field="profile_type", operator="=", value="универсальный профиль"))
    await session.flush()

    product = Product(sku="BOX-1", name="Box", type=ProductType.finished_good, unit="pcs", profile_type="универсальный профиль")
    session.add(product)
    await session.flush()

    result = await find_route(session, product)
    assert result is not None
    assert result.name == "Box route"


@pytest.mark.asyncio
async def test_no_match_returns_default(session) -> None:
    """When no rule matches, the default route (no rules) is returned."""
    default_route = ProductionRoute(name="Default", is_active=True)
    specific_route = ProductionRoute(name="Specific", is_active=True)
    session.add_all([default_route, specific_route])
    await session.flush()

    rule = RouteMatchingRule(route_id=specific_route.id, priority=10)
    session.add(rule)
    await session.flush()
    session.add(RouteRuleCondition(rule_id=rule.id, field="alloy", operator="=", value="АД31"))
    await session.flush()

    # Product with different alloy
    product = Product(sku="NM-1", name="No Match", type=ProductType.finished_good, unit="pcs", alloy="АД0")
    session.add(product)
    await session.flush()

    result = await find_route(session, product)
    assert result is not None
    assert result.name == "Default"


@pytest.mark.asyncio
async def test_higher_priority_rule_wins(session) -> None:
    """When multiple rules match, the one with higher priority wins."""
    default_route = ProductionRoute(name="Default", is_active=True)
    general_route = ProductionRoute(name="General aluminum", is_active=True)
    specific_route = ProductionRoute(name="Specific alloy", is_active=True)
    session.add_all([default_route, general_route, specific_route])
    await session.flush()

    # General rule: profile_type = универсальный профиль (priority 5)
    general_rule = RouteMatchingRule(route_id=general_route.id, priority=5)
    session.add(general_rule)
    await session.flush()
    session.add(RouteRuleCondition(rule_id=general_rule.id, field="profile_type", operator="=", value="универсальный профиль"))

    # Specific rule: alloy = АД31 (priority 20)
    specific_rule = RouteMatchingRule(route_id=specific_route.id, priority=20)
    session.add(specific_rule)
    await session.flush()
    session.add(RouteRuleCondition(rule_id=specific_rule.id, field="alloy", operator="=", value="АД31"))

    await session.flush()

    product = Product(
        sku="HP-1", name="High Priority", type=ProductType.finished_good, unit="pcs",
        profile_type="универсальный профиль", alloy="АД31"
    )
    session.add(product)
    await session.flush()

    result = await find_route(session, product)
    assert result is not None
    assert result.name == "Specific alloy"  # higher priority wins


@pytest.mark.asyncio
async def test_no_routes_returns_none(session) -> None:
    product = Product(sku="NONE-1", name="None", type=ProductType.finished_good, unit="pcs")
    session.add(product)
    await session.flush()

    result = await find_route(session, product)
    assert result is None


# --- _match_conditions unit tests ---

def _make_product(**kwargs) -> Product:
    defaults = dict(
        sku="T-1", name="Test", type=ProductType.finished_good, unit="pcs",
        profile_type=None, alloy=None, color=None, anod_type=None,
        length_mm=None, quantity_per_hanger=None,
    )
    defaults.update(kwargs)
    return Product(**defaults)


def _make_condition(field: str, operator: str, value: str) -> RouteRuleCondition:
    return RouteRuleCondition(field=field, operator=operator, value=value)


def test_match_equals() -> None:
    product = _make_product(profile_type="универсальный профиль")
    cond = _make_condition("profile_type", "=", "универсальный профиль")
    assert _match_conditions(product, [cond]) is True
    cond2 = _make_condition("profile_type", "=", "другой")
    assert _match_conditions(product, [cond2]) is False


def test_match_not_equals() -> None:
    product = _make_product(alloy="АД31")
    cond = _make_condition("alloy", "!=", "АД0")
    assert _match_conditions(product, [cond]) is True
    cond2 = _make_condition("alloy", "!=", "АД31")
    assert _match_conditions(product, [cond2]) is False


def test_match_in_list() -> None:
    product = _make_product(color="черный")
    cond = _make_condition("color", "in", "черный, серебро, белый")
    assert _match_conditions(product, [cond]) is True
    cond2 = _make_condition("color", "in", "серебро, белый")
    assert _match_conditions(product, [cond2]) is False


def test_match_contains() -> None:
    product = _make_product(profile_type="анодированный трубный")
    cond = _make_condition("profile_type", "contains", "трубный")
    assert _match_conditions(product, [cond]) is True
    cond2 = _make_condition("profile_type", "contains", "короб")
    assert _match_conditions(product, [cond2]) is False


def test_multiple_conditions_all_must_match() -> None:
    product = _make_product(profile_type="универсальный профиль", alloy="АД31")
    conds = [
        _make_condition("profile_type", "=", "универсальный профиль"),
        _make_condition("alloy", "=", "АД31"),
    ]
    assert _match_conditions(product, conds) is True

    conds2 = [
        _make_condition("profile_type", "=", "универсальный профиль"),
        _make_condition("alloy", "=", "АД0"),
    ]
    assert _match_conditions(product, conds2) is False
