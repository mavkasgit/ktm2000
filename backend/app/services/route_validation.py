from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.imports import ImportBatch
from app.models.production_plan import PlanPosition
from app.models.route import RouteStage
from app.models.section import Section
from app.services.route_matcher import resolve_position_route
from app.services.route_selection import select_route_for_payload


ROUTE_ERROR_CODES = {
    "route_not_matching_import_signature",
    "route_missing_required_step",
    "route_missing_pack_additional_operation",
    "route_primary_operation_mismatch",
    "route_contains_excluded_step",
    "route_rule_conflict",
    "no_route_candidate",
}


async def validate_route_match(db: AsyncSession, position: PlanPosition) -> list[str]:
    if position.product_id is None:
        return []

    route_info = await resolve_position_route(db, position)
    if route_info.route_id is None:
        return []
    # Manual confirmation is an explicit override by user and should not be
    # blocked by auto-signature mismatch checks.
    if route_info.source == "manual" or route_info.route_origin == "manual_confirmed":
        return []

    import_batch = await db.get(ImportBatch, position.import_batch_id) if position.import_batch_id is not None else None
    rule_profile_id = import_batch.rule_profile_id if import_batch is not None else None
    
    # Get template column mapping from import batch for proper Excel column resolution
    template_column_mapping = None
    if import_batch and import_batch.template_id:
        from app.models.import_template import ImportTemplate
        template = await db.get(ImportTemplate, import_batch.template_id)
        if template:
            template_column_mapping = template.column_mapping

    product = await db.get(Product, position.product_id)
    selection = await select_route_for_payload(
        db, position.source_payload, product, 
        profile_id=rule_profile_id,
        template_column_mapping=template_column_mapping
    )
    if selection.error == "route_rule_conflict":
        return ["route_rule_conflict"]

    steps = (
        await db.execute(
            select(RouteStage)
            .where(RouteStage.route_id == route_info.route_id)
            .order_by(RouteStage.sequence)
        )
    ).scalars().all()
    if not steps:
        return []

    active_section_ids = {step.section_id for step in steps}
    required_ids = set(selection.required_section_ids)
    excluded_ids = set(selection.excluded_section_ids)
    issues: list[str] = []

    missing_required = sorted(required_ids - active_section_ids)
    excluded_present = sorted(excluded_ids & active_section_ids)
    if missing_required:
        issues.append("route_missing_required_step: " + ", ".join(await _section_codes(db, missing_required)))
    if excluded_present:
        issues.append("route_contains_excluded_step: " + ", ".join(await _section_codes(db, excluded_present)))

    return issues


async def _section_codes(db: AsyncSession, section_ids: list[int]) -> list[str]:
    sections = (await db.execute(select(Section).where(Section.id.in_(section_ids)))).scalars().all()
    by_id = {section.id: section.code for section in sections}
    return [by_id.get(section_id, str(section_id)) for section_id in section_ids]


