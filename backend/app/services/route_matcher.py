from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.route import ProductionRoute, RouteMatchingRule, RouteRuleCondition


async def find_route(db: AsyncSession, product: Product) -> ProductionRoute | None:
    """Find the best matching active route for a product using matching rules.

    Priority: higher priority rule wins.
    Route with NO rules = default fallback (matches everything, lowest priority).
    """
    # Load all active routes with their rules
    routes = (
        await db.execute(
            select(ProductionRoute)
            .where(ProductionRoute.is_active.is_(True))
            .order_by(ProductionRoute.id)
        )
    ).scalars().all()

    if not routes:
        return None

    best_route: ProductionRoute | None = None
    best_priority: int = -1  # routes without rules have priority -1 (default)

    for route in routes:
        # Load rules for this route
        rules = (
            await db.execute(
                select(RouteMatchingRule)
                .where(RouteMatchingRule.route_id == route.id)
                .order_by(RouteMatchingRule.priority.desc())
            )
        ).scalars().all()

        if not rules:
            # Default fallback — matches everything, but only if no specific rule matched
            if best_route is None:
                best_route = route
                best_priority = -1
            continue

        # Check rules in priority order (highest first)
        for rule in rules:
            conditions = (
                await db.execute(
                    select(RouteRuleCondition).where(RouteRuleCondition.rule_id == rule.id)
                )
            ).scalars().all()

            if not conditions:
                # Rule with no conditions = matches everything
                if rule.priority > best_priority:
                    best_route = route
                    best_priority = rule.priority
                break

            if _match_conditions(product, conditions):
                if rule.priority > best_priority:
                    best_route = route
                    best_priority = rule.priority
                break  # this route matched, no need to check lower-priority rules

    return best_route


def _match_conditions(product: Product, conditions: list[RouteRuleCondition]) -> bool:
    """Check if a product matches ALL conditions of a rule."""
    for cond in conditions:
        product_value = getattr(product, cond.field, None)

        # Normalize types for comparison
        if cond.field == "length_mm" and product_value is not None:
            product_value = float(product_value)
            try:
                cond_value = float(cond.value)
            except (ValueError, TypeError):
                return False
        elif cond.field == "quantity_per_hanger" and product_value is not None:
            product_value = int(product_value)
            try:
                cond_value = int(cond.value)
            except (ValueError, TypeError):
                return False
        else:
            cond_value = cond.value

        if cond.operator == "=":
            if str(product_value or "") != str(cond_value):
                return False
        elif cond.operator == "!=":
            if str(product_value or "") == str(cond_value):
                return False
        elif cond.operator == "in":
            # cond.value is comma-separated list
            allowed = [v.strip() for v in str(cond_value).split(",")]
            if str(product_value or "") not in allowed:
                return False
        elif cond.operator == "contains":
            if str(cond_value) not in str(product_value or ""):
                return False
        else:
            # Unknown operator — treat as no match
            return False

    return True
