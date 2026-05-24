from __future__ import annotations

from collections import Counter
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.imports import ImportBatchStatus
from app.models.production_plan import (
    PlanChangeAction,
    PlanChangeItem,
    PlanChangeItemStatus,
    PlanChangeSet,
    PlanChangeSetStatus,
    PlanPosition,
    PlanPositionRouteMatchQuality,
    PlanPositionRouteMatchReason,
    PlanPositionRouteOrigin,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    PositionStatusHistory,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.routing import RouteOperationFamily, RouteOutputKind
from app.services.plan_validation import validate_plan_position


def _enrich_source_payload(
    source_payload: dict | None,
    after_data: dict,
) -> dict:
    """Copy original_quantity and quantity_per_hanger from after_data into source_payload."""
    payload = dict(source_payload) if source_payload else {}
    if "original_quantity" in after_data:
        payload["original_quantity"] = after_data["original_quantity"]
    if "quantity_per_hanger" in after_data:
        payload["quantity_per_hanger"] = after_data["quantity_per_hanger"]
    return payload


ALLOWED_TRANSITIONS = {
    (PlanPositionStatus.approved, PlanPositionStatus.cancelled),
    (PlanPositionStatus.released, PlanPositionStatus.cancelled),
    (PlanPositionStatus.cancelled, PlanPositionStatus.approved),
    (PlanPositionStatus.cancelled, PlanPositionStatus.released),
}


def record_status_change(
    db: AsyncSession,
    position_id: int,
    from_status: str,
    to_status: str,
    changed_by: int | None = None,
    reason: str | None = None,
) -> None:
    history = PositionStatusHistory(
        plan_position_id=position_id,
        from_status=from_status,
        to_status=to_status,
        changed_by=changed_by,
        reason=reason,
    )
    db.add(history)


async def apply_change_set(db: AsyncSession, change_set_id: int, *, skip_invalid: bool = False) -> dict:
    change_set = await db.get(PlanChangeSet, change_set_id)
    if change_set is None:
        raise ValueError("Change set not found")
    if change_set.status == PlanChangeSetStatus.applied:
        return await get_plan_preview(db, change_set.production_plan_id)

    items = (
        await db.execute(select(PlanChangeItem).where(PlanChangeItem.change_set_id == change_set_id).order_by(PlanChangeItem.id))
    ).scalars().all()

    created = 0
    updated = 0
    ignored = 0
    cancelled = 0
    skipped_invalid = 0
    for item in items:
        if item.status == PlanChangeItemStatus.applied:
            continue

        # Optional mode: apply only rows without errors.
        if skip_invalid and item.errors:
            item.status = PlanChangeItemStatus.applied
            skipped_invalid += 1
            continue

        if item.change_action == PlanChangeAction.ignore_unchanged:
            item.status = PlanChangeItemStatus.applied
            ignored += 1
            continue

        if item.change_action == PlanChangeAction.mark_possible_duplicate:
            item.status = PlanChangeItemStatus.applied
            continue

        if item.change_action == PlanChangeAction.cancel_draft_position:
            if item.plan_position_id:
                position = await db.get(PlanPosition, item.plan_position_id)
                if position is not None and position.status == PlanPositionStatus.draft:
                    position.status = PlanPositionStatus.cancelled
            item.status = PlanChangeItemStatus.applied
            cancelled += 1
            continue

        if item.change_action == PlanChangeAction.update_draft_position:
            if item.plan_position_id:
                position = await db.get(PlanPosition, item.plan_position_id)
                if position is not None and position.status == PlanPositionStatus.draft:
                    after = item.after_data
                    position.product_id = after.get("product_id")
                    position.source_sku = after["source_sku"]
                    position.source_name = after.get("source_name")
                    qty = after["quantity"]
                    position.quantity = Decimal(str(qty)) if not isinstance(qty, Decimal) else qty
                    position.source_payload = after.get("source_payload") or {}
                    position.source_ref = after.get("source_ref")
                    position.source_fingerprint = after.get("source_fingerprint")
                    position.source_row_hash = after.get("source_row_hash")
                    position.import_batch_id = change_set.import_batch_id
                    position.source_row_number = (after.get("source_row_numbers") or [item.source_row_number])[0]
                    position.period_start = _date_from_payload(after, "period_start")
                    position.period_end = _date_from_payload(after, "period_end")
                    position.operation_family = _operation_family_from_after(after)
                    position.output_kind = _output_kind_from_after(after)
                    position.has_pack_ops = _bool_or_none(after.get("has_pack_ops"))
                    position.route_id = after.get("route_id")
                    position.route_origin = _route_origin_from_after(after)
                    position.route_match_quality = _route_match_quality_from_after(after)
                    position.route_match_reason = _route_match_reason_from_after(after)
                    position.route_assigned_at = _datetime_from_after(after, "route_assigned_at")
                    position.route_manual_confirmed_at = _datetime_from_after(after, "route_manual_confirmed_at")

                    validation_errors = await validate_plan_position(db, position)
                    position.validation_errors = validation_errors
                    position.validation_status = (
                        PlanPositionValidationStatus.invalid if validation_errors else PlanPositionValidationStatus.valid
                    )
                    position.status = PlanPositionStatus.invalid if validation_errors else PlanPositionStatus.draft
                    await db.flush()
            item.status = PlanChangeItemStatus.applied
            updated += 1
            continue

        if item.change_action == PlanChangeAction.create_position:
            after = item.after_data
            validation_errors = list(item.errors or [])
            is_paired_profile = bool((after.get("source_payload") or {}).get("paired_profile"))
            if not is_paired_profile and not after.get("product_id") and "product_not_found" not in validation_errors:
                validation_errors.append("product_not_found")

            qty = after["quantity"]
            qty_decimal = Decimal(str(qty)) if not isinstance(qty, Decimal) else qty

            position = PlanPosition(
                production_plan_id=change_set.production_plan_id,
                product_id=after.get("product_id"),
                route_id=after.get("route_id"),
                source_type=PlanSourceType.excel_import,
                source_system="excel",
                source_ref=after.get("source_ref"),
                source_fingerprint=after.get("source_fingerprint"),
                source_row_hash=after.get("source_row_hash"),
                import_batch_id=change_set.import_batch_id,
                source_sku=after["source_sku"],
                source_name=after.get("source_name"),
                quantity=qty_decimal,
                source_payload=_enrich_source_payload(after.get("source_payload"), after),
                period_start=_date_from_payload(after, "period_start"),
                period_end=_date_from_payload(after, "period_end"),
                source_row_number=(after.get("source_row_numbers") or [item.source_row_number])[0],
                operation_family=_operation_family_from_after(after),
                output_kind=_output_kind_from_after(after),
                has_pack_ops=_bool_or_none(after.get("has_pack_ops")),
                route_origin=_route_origin_from_after(after),
                route_match_quality=_route_match_quality_from_after(after),
                route_match_reason=_route_match_reason_from_after(after),
                route_assigned_at=_datetime_from_after(after, "route_assigned_at"),
                route_manual_confirmed_at=_datetime_from_after(after, "route_manual_confirmed_at"),
                status=PlanPositionStatus.invalid if validation_errors else PlanPositionStatus.draft,
                validation_status=PlanPositionValidationStatus.invalid if validation_errors else PlanPositionValidationStatus.valid,
                validation_errors=validation_errors,
            )
            db.add(position)
            await db.flush()
            item.plan_position_id = position.id
            item.status = PlanChangeItemStatus.applied
            created += 1
            continue

    change_set.status = PlanChangeSetStatus.applied
    if change_set.import_batch_id:
        from app.models.imports import ImportBatch

        batch = await db.get(ImportBatch, change_set.import_batch_id)
        if batch is not None:
            batch.status = ImportBatchStatus.applied

    extra = {
        "created_positions": created,
        "updated_positions": updated,
        "ignored_positions": ignored,
        "cancelled_positions": cancelled,
        "skipped_invalid_positions": skipped_invalid,
    }
    return await get_plan_preview(db, change_set.production_plan_id, extra=extra)


async def rollback_change_set(db: AsyncSession, change_set_id: int) -> dict:
    change_set = await db.get(PlanChangeSet, change_set_id)
    if change_set is None:
        raise ValueError("Change set not found")
    if change_set.status != PlanChangeSetStatus.applied:
        raise ValueError("Only applied change sets can be rolled back")

    items = (
        await db.execute(select(PlanChangeItem).where(PlanChangeItem.change_set_id == change_set_id))
    ).scalars().all()
    for item in items:
        if item.change_action == PlanChangeAction.create_position and item.plan_position_id:
            position = await db.get(PlanPosition, item.plan_position_id)
            if position and position.status == PlanPositionStatus.released:
                raise ValueError("Cannot rollback: position already released")
            if position:
                position.status = PlanPositionStatus.cancelled
        elif item.change_action == PlanChangeAction.update_draft_position and item.plan_position_id:
            position = await db.get(PlanPosition, item.plan_position_id)
            if position and item.before_data:
                position.quantity = Decimal(item.before_data.get("quantity", str(position.quantity)))
                position.source_payload = item.before_data.get("source_payload", position.source_payload)
                position.source_name = item.before_data.get("source_name", position.source_name)
                position.operation_family = _operation_family_from_after(item.before_data)
                position.output_kind = _output_kind_from_after(item.before_data)
                position.has_pack_ops = _bool_or_none(item.before_data.get("has_pack_ops"))
                position.status = PlanPositionStatus.draft
        elif item.change_action == PlanChangeAction.cancel_draft_position and item.plan_position_id:
            position = await db.get(PlanPosition, item.plan_position_id)
            if position:
                position.status = PlanPositionStatus.draft

    change_set.status = PlanChangeSetStatus.cancelled
    if change_set.import_batch_id:
        from app.models.imports import ImportBatch

        batch = await db.get(ImportBatch, change_set.import_batch_id)
        if batch:
            batch.status = ImportBatchStatus.cancelled

    await db.flush()
    return await get_plan_preview(db, change_set.production_plan_id)


async def approve_plan_position(
    db: AsyncSession,
    production_plan_id: int,
    position_id: int,
    force: bool = False,
    changed_by: int | None = None,
) -> PlanPosition:
    position = await db.get(PlanPosition, position_id)
    if position is None or position.production_plan_id != production_plan_id:
        raise ValueError("Plan position not found")
    if position.status in {PlanPositionStatus.released, PlanPositionStatus.approved}:
        raise ValueError(f"Position with status '{position.status.value}' cannot be approved")
    if position.status == PlanPositionStatus.invalid:
        raise ValueError("Сначала исправьте ошибки валидации")
    if position.route_id is None:
        raise ValueError("Сначала назначьте маршрут")

    errors = await validate_plan_position(db, position)
    position.validation_errors = errors
    position.validation_status = PlanPositionValidationStatus.invalid if errors else PlanPositionValidationStatus.valid
    if errors and not force:
        position.status = PlanPositionStatus.invalid
        raise ValueError("; ".join(errors))

    from_status = position.status.value
    position.status = PlanPositionStatus.approved
    record_status_change(db, position_id, from_status, PlanPositionStatus.approved.value, changed_by)
    plan = await db.get(ProductionPlan, production_plan_id)
    if plan is not None and plan.status in {ProductionPlanStatus.draft, ProductionPlanStatus.validated}:
        plan.status = ProductionPlanStatus.approved
    await db.flush()
    return position


async def cancel_plan_position(
    db: AsyncSession,
    production_plan_id: int,
    position_id: int,
    changed_by: int | None = None,
    reason: str | None = None,
) -> PlanPosition:
    """Cancel an approved or released position. Only positions with status approved/released can be cancelled."""
    position = await db.get(PlanPosition, position_id)
    if position is None or position.production_plan_id != production_plan_id:
        raise ValueError("Plan position not found")
    if position.status not in {PlanPositionStatus.approved, PlanPositionStatus.released}:
        raise ValueError(f"Нельзя отменить позицию со статусом '{position.status.value}'")

    from_status = position.status.value
    position.status = PlanPositionStatus.cancelled
    record_status_change(db, position_id, from_status, PlanPositionStatus.cancelled.value, changed_by, reason)
    await db.flush()
    return position


async def restore_plan_position(
    db: AsyncSession,
    production_plan_id: int,
    position_id: int,
    changed_by: int | None = None,
    reason: str | None = None,
) -> PlanPosition:
    """Restore a cancelled position to its previous status (approved or released) based on history."""
    position = await db.get(PlanPosition, position_id)
    if position is None or position.production_plan_id != production_plan_id:
        raise ValueError("Plan position not found")
    if position.status != PlanPositionStatus.cancelled:
        raise ValueError(f"Нельзя восстановить позицию со статусом '{position.status.value}'")

    # Find the last cancellation record in history
    last_cancel = (
        await db.execute(
            select(PositionStatusHistory)
            .where(
                PositionStatusHistory.plan_position_id == position_id,
                PositionStatusHistory.to_status == PlanPositionStatus.cancelled.value,
            )
            .order_by(PositionStatusHistory.changed_at.desc())
        )
    ).scalar_one_or_none()

    if last_cancel is None:
        raise ValueError("Нет истории отмены — восстановление невозможно")

    target_status_value = last_cancel.from_status
    if target_status_value not in {PlanPositionStatus.approved.value, PlanPositionStatus.released.value}:
        raise ValueError(f"Недопустимый статус для восстановления: '{target_status_value}'")

    target_status = PlanPositionStatus(target_status_value)
    position.status = target_status
    record_status_change(db, position_id, PlanPositionStatus.cancelled.value, target_status_value, changed_by, reason)
    await db.flush()
    return position


async def soft_delete_cancelled_position(
    db: AsyncSession,
    production_plan_id: int,
    position_id: int,
    changed_by: int | None = None,
    reason: str | None = None,
) -> PlanPosition:
    """Soft-delete a cancelled position. Hides it from all lists while preserving history."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.models.internal_plan import SectionPlanLine
    from app.models.work_task import WorkTask, WorkTaskStatus

    position = await db.get(PlanPosition, position_id)
    if position is None or position.production_plan_id != production_plan_id:
        raise ValueError("Plan position not found")
    if position.status != PlanPositionStatus.cancelled:
        raise ValueError(f"Можно скрыть только отменённую позицию (текущий статус: '{position.status.value}')")

    record_status_change(
        db, position_id, PlanPositionStatus.cancelled.value, "deleted", changed_by, reason or "Удалена из списка"
    )
    position.deleted_at = datetime.now(timezone.utc)
    position.deleted_by = changed_by
    position.delete_reason = reason
    await db.flush()

    # Cancel all active related WorkTasks so they disappear from shopfloor board
    line_ids_result = (
        await db.execute(
            select(SectionPlanLine.id).where(
                SectionPlanLine.plan_position_id == position_id
            )
        )
    ).scalars().all()

    if line_ids_result:
        await db.execute(
            WorkTask.__table__.update()
            .where(WorkTask.section_plan_line_id.in_(line_ids_result))
            .where(WorkTask.status.notin_([WorkTaskStatus.completed, WorkTaskStatus.cancelled]))
            .values(status=WorkTaskStatus.cancelled)
        )

    await db.flush()
    return position


async def get_plan_preview(db: AsyncSession, production_plan_id: int, extra: dict | None = None) -> dict:
    plan = await db.get(ProductionPlan, production_plan_id)
    if plan is None:
        raise ValueError("Production plan not found")
    positions = (
        await db.execute(
            select(PlanPosition)
            .where(PlanPosition.production_plan_id == production_plan_id, PlanPosition.status != PlanPositionStatus.cancelled)
            .order_by(PlanPosition.id)
        )
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


def _operation_family_from_after(after: dict) -> RouteOperationFamily | None:
    value = after.get("operation_family")
    if not value:
        return None
    try:
        return RouteOperationFamily(str(value))
    except ValueError:
        return None


def _output_kind_from_after(after: dict) -> RouteOutputKind | None:
    value = after.get("output_kind")
    if not value:
        return None
    try:
        return RouteOutputKind(str(value))
    except ValueError:
        return None


def _bool_or_none(value):
    if value is None:
        return None
    return bool(value)


def _datetime_from_after(after: dict, key: str):
    from datetime import datetime

    value = after.get(key)
    if not value:
        return None
    try:
        if isinstance(value, datetime):
            return value
        raw = str(value)
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _route_origin_from_after(after: dict) -> PlanPositionRouteOrigin | None:
    value = after.get("route_origin")
    if not value:
        return None
    try:
        return PlanPositionRouteOrigin(str(value))
    except ValueError:
        return None


def _route_match_quality_from_after(after: dict) -> PlanPositionRouteMatchQuality | None:
    value = after.get("route_match_quality")
    if not value:
        return None
    try:
        return PlanPositionRouteMatchQuality(str(value))
    except ValueError:
        return None


def _route_match_reason_from_after(after: dict) -> PlanPositionRouteMatchReason | None:
    value = after.get("route_match_reason")
    if not value:
        return None
    try:
        return PlanPositionRouteMatchReason(str(value))
    except ValueError:
        return None
