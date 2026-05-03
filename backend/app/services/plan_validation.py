from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.techcard import Techcard, TechcardLine
from app.models.product import Product
from app.models.production_plan import PlanPosition, PlanPositionStatus
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section


async def validate_plan_position(db: AsyncSession, position: PlanPosition) -> list[str]:
    errors: list[str] = []
    if position.product_id is None:
        errors.append("product_not_found")
        return errors
    if position.quantity <= 0:
        errors.append("quantity_must_be_positive")

    product = await db.get(Product, position.product_id)
    if product is None or not product.is_active:
        errors.append("product_inactive")

    techcard = await db.scalar(select(Techcard).where(Techcard.product_id == position.product_id, Techcard.is_active.is_(True)))
    if techcard is None:
        errors.append("active_techcard_not_found")
    else:
        line = await db.scalar(select(TechcardLine).where(TechcardLine.techcard_id == techcard.id).limit(1))
        if line is None:
            errors.append("active_techcard_has_no_lines")

    route = await db.scalar(
        select(ProductionRoute).where(ProductionRoute.product_id == position.product_id, ProductionRoute.is_active.is_(True))
    )
    if route is None:
        errors.append("active_route_not_found")
    else:
        steps = (
            await db.execute(select(RouteStep).where(RouteStep.route_id == route.id).order_by(RouteStep.sequence))
        ).scalars().all()
        if not steps:
            errors.append("active_route_has_no_steps")
        previous = 0
        for step in steps:
            if step.sequence <= previous:
                errors.append("route_sequence_invalid")
                break
            previous = step.sequence
            section = await db.get(Section, step.section_id)
            if section is None or not section.is_active:
                errors.append("route_contains_inactive_section")
                break

    duplicate_stmt = (
        select(PlanPosition)
        .where(
            PlanPosition.production_plan_id == position.production_plan_id,
            PlanPosition.source_sku == position.source_sku,
            PlanPosition.due_date == position.due_date,
            PlanPosition.status != PlanPositionStatus.cancelled,
        )
    )
    if position.id is not None:
        duplicate_stmt = duplicate_stmt.where(PlanPosition.id != position.id)
    duplicate = await db.scalar(duplicate_stmt)
    if duplicate is not None:
        errors.append("duplicate_sku_due_date")

    from app.services.route_validation import validate_route_match

    route_errors = await validate_route_match(db, position)
    errors.extend(route_errors)

    return errors
