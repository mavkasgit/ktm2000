from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bom import BOM, BOMLine
from app.models.imports import ImportBatchStatus
from app.models.production_plan import (
    PlanChangeItem,
    PlanChangeItemStatus,
    PlanChangeSet,
    PlanChangeSetStatus,
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section


async def apply_change_set(db: AsyncSession, change_set_id: int) -> dict:
    change_set = await db.get(PlanChangeSet, change_set_id)
    if change_set is None:
        raise ValueError("Change set not found")
    if change_set.status == PlanChangeSetStatus.applied:
        return await get_plan_preview(db, change_set.production_plan_id)

    items = (
        await db.execute(select(PlanChangeItem).where(PlanChangeItem.change_set_id == change_set_id).order_by(PlanChangeItem.id))
    ).scalars().all()

    created = 0
    for item in items:
        if item.status == PlanChangeItemStatus.applied:
            continue
        after = item.after_data
        validation_errors = list(item.errors or [])
        if not after.get("product_id") and "product_not_found" not in validation_errors:
            validation_errors.append("product_not_found")

        position = PlanPosition(
            production_plan_id=change_set.production_plan_id,
            product_id=after.get("product_id"),
            source_type=PlanSourceType.excel_import,
            source_system="excel",
            source_ref=after.get("source_ref"),
            source_fingerprint=after.get("source_fingerprint"),
            source_row_hash=after.get("source_row_hash"),
            import_batch_id=change_set.import_batch_id,
            source_sku=after["source_sku"],
            source_name=after.get("source_name"),
            quantity=after["quantity"],
            source_payload=after.get("source_payload") or {},
            period_start=_date_from_payload(after, "period_start"),
            period_end=_date_from_payload(after, "period_end"),
            source_row_number=(after.get("source_row_numbers") or [item.source_row_number])[0],
            status=PlanPositionStatus.invalid if validation_errors else PlanPositionStatus.valid,
            validation_status=PlanPositionValidationStatus.invalid if validation_errors else PlanPositionValidationStatus.valid,
            validation_errors=validation_errors,
        )
        db.add(position)
        await db.flush()
        item.plan_position_id = position.id
        item.status = PlanChangeItemStatus.applied
        created += 1

    change_set.status = PlanChangeSetStatus.applied
    if change_set.import_batch_id:
        from app.models.imports import ImportBatch

        batch = await db.get(ImportBatch, change_set.import_batch_id)
        if batch is not None:
            batch.status = ImportBatchStatus.applied

    return await get_plan_preview(db, change_set.production_plan_id, extra={"created_positions": created})


async def approve_plan_position(db: AsyncSession, production_plan_id: int, position_id: int) -> PlanPosition:
    position = await db.get(PlanPosition, position_id)
    if position is None or position.production_plan_id != production_plan_id:
        raise ValueError("Plan position not found")
    if position.status == PlanPositionStatus.released:
        raise ValueError("Released position cannot be approved again")

    errors = await validate_plan_position(db, position)
    position.validation_errors = errors
    position.validation_status = PlanPositionValidationStatus.invalid if errors else PlanPositionValidationStatus.valid
    if errors:
        position.status = PlanPositionStatus.invalid
        raise ValueError("; ".join(errors))

    position.status = PlanPositionStatus.approved
    plan = await db.get(ProductionPlan, production_plan_id)
    if plan is not None and plan.status in {ProductionPlanStatus.draft, ProductionPlanStatus.validated}:
        plan.status = ProductionPlanStatus.approved
    await db.flush()
    return position


async def validate_plan_position(db: AsyncSession, position: PlanPosition) -> list[str]:
    errors: list[str] = []
    if position.product_id is None:
        errors.append("product_not_found")
        return errors
    if position.quantity <= 0:
        errors.append("quantity_must_be_positive")

    bom = await db.scalar(select(BOM).where(BOM.product_id == position.product_id, BOM.is_active.is_(True)))
    if bom is None:
        errors.append("active_bom_not_found")
    else:
        line = await db.scalar(select(BOMLine).where(BOMLine.bom_id == bom.id).limit(1))
        if line is None:
            errors.append("active_bom_has_no_lines")

    route = await db.scalar(select(ProductionRoute).where(ProductionRoute.product_id == position.product_id, ProductionRoute.is_active.is_(True)))
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
    return errors


async def get_plan_preview(db: AsyncSession, production_plan_id: int, extra: dict | None = None) -> dict:
    plan = await db.get(ProductionPlan, production_plan_id)
    if plan is None:
        raise ValueError("Production plan not found")
    positions = (
        await db.execute(select(PlanPosition).where(PlanPosition.production_plan_id == production_plan_id).order_by(PlanPosition.id))
    ).scalars().all()
    status_counts = Counter(position.status.value for position in positions)
    validation_counts = Counter(position.validation_status.value for position in positions)
    payload = {
        "production_plan_id": plan.id,
        "plan_no": plan.plan_no,
        "status": plan.status.value,
        "positions_total": len(positions),
        "status_counts": dict(status_counts),
        "validation_counts": dict(validation_counts),
        "positions": [
            {
                "id": position.id,
                "product_id": position.product_id,
                "source_sku": position.source_sku,
                "source_name": position.source_name,
                "quantity": str(position.quantity),
                "status": position.status.value,
                "validation_status": position.validation_status.value,
                "validation_errors": position.validation_errors,
            }
            for position in positions
        ],
    }
    if extra:
        payload.update(extra)
    return payload


def _date_from_payload(after: dict, key: str):
    from datetime import date

    value = (after.get("source_payload") or {}).get(key)
    return date.fromisoformat(value) if value else None
