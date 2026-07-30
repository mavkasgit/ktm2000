from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import String, cast, exists, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func as sa_func

from app.api.deps import WRITER_ROLES, require_role, get_current_user
from app.core.database import get_db
from app.domain.dimensions import format_operation_summary
from app.models.production_plan import (
    PlanChangeItem,
    PlanChangeSet,
    PlanPosition,
    PlanPositionRouteOrigin,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    ProductionPlan,
)
from app.models.audit_log import AuditLog
from app.api.routes.audit_logs import AuditLogOut
from app.models.imports import ImportBatch
from app.models.product import Product
from app.models.release_batch import ReleaseBatchType
from app.models.route import ProductionRoute, RouteStage
from app.models.section import Section
from app.models.user import User
from app.services.plan_generation import create_release_batch
from app.services.production_plan_service import (
    apply_change_set,
    approve_plan_position,
    cancel_plan_position,
    get_plan_preview,
    restore_plan_position,
    rollback_change_set,
    soft_delete_cancelled_position,
)
from app.services.route_matcher import resolve_position_route, ResolvedRouteInfo, make_position_route_cache_key
from app.services.route_selection import select_route_for_payload
from app.services.route_validation import validate_route_match
from app.services.plan_validation import format_validation_error

router = APIRouter(prefix="/production-plans", tags=["production-plans"])


async def _delete_batch_and_orphan_file(db: AsyncSession, batch_id: int) -> bool:
    """Delete import batch and remove source file only when no other batch references it."""
    from app.models.imports import ImportBatch, ImportFile

    batch = await db.get(ImportBatch, batch_id)
    if batch is None:
        return False

    source_file_id = batch.source_file_id
    await db.delete(batch)
    await db.flush()

    if source_file_id:
        refs_count = (
            await db.execute(
                select(sa_func.count(ImportBatch.id)).where(ImportBatch.source_file_id == source_file_id)
            )
        ).scalar() or 0
        if refs_count == 0:
            import_file = await db.get(ImportFile, source_file_id)
            if import_file is not None:
                await db.delete(import_file)
                await db.flush()
    return True


class PlanSummaryOut(BaseModel):
    id: int
    plan_no: str
    name: str
    status: str
    period_start: str | None
    period_end: str | None
    total_positions: int
    draft_positions: int
    approved_positions: int
    released_positions: int
    created_at: str


@router.get("", response_model=list[PlanSummaryOut])
async def list_plans(db: AsyncSession = Depends(get_db)) -> list[PlanSummaryOut]:
    plans = (await db.execute(select(ProductionPlan).order_by(ProductionPlan.created_at.desc()))).scalars().all()
    result = []
    for plan in plans:
        counts = (
            await db.execute(
                select(PlanPosition.status, sa_func.count(PlanPosition.id))
                .where(PlanPosition.production_plan_id == plan.id)
                .group_by(PlanPosition.status)
            )
        ).all()
        status_map = {s.value: c for s, c in counts}
        total = (
            await db.execute(select(sa_func.count(PlanPosition.id)).where(PlanPosition.production_plan_id == plan.id))
        ).scalar() or 0
        result.append(
            PlanSummaryOut(
                id=plan.id,
                plan_no=plan.plan_no,
                name=plan.name,
                status=plan.status.value,
                period_start=plan.period_start.isoformat() if plan.period_start else None,
                period_end=plan.period_end.isoformat() if plan.period_end else None,
                total_positions=total,
                draft_positions=status_map.get("draft", 0),
                approved_positions=status_map.get("approved", 0),
                released_positions=status_map.get("released", 0),
                created_at=plan.created_at.isoformat(),
            )
        )
    return result


class ReleasePositionIn(BaseModel):
    plan_position_id: int
    release_quantity: Decimal | None = None


class ReleaseBatchCreateIn(BaseModel):
    name: str | None = None
    batch_type: ReleaseBatchType = ReleaseBatchType.manual
    positions: list[ReleasePositionIn] | None = None


class StatusActionIn(BaseModel):
    reason: str | None = None


class UpdatePositionQuantityIn(BaseModel):
    quantity: Decimal
    quantity_per_hanger: int | None = None


# Удален StatusHistoryOut, так как PositionStatusHistory удалена. История теперь читается через аудит-логи.


class RouteCheckOut(BaseModel):
    expected_signature: dict
    active_route_snapshot: dict | None
    match: bool
    issues: list[str]


class SectionTotalsLineOut(BaseModel):
    section_id: int
    section_code: str
    section_name: str
    section_type: str | None
    positions_count: int
    planned_input_quantity: str
    planned_output_quantity: str


class SectionTotalsOut(BaseModel):
    production_plan_id: int
    totals: list[SectionTotalsLineOut]


@router.get("/{production_plan_id}/preview")
async def preview_production_plan(production_plan_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await get_plan_preview(db, production_plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{production_plan_id}/change-sets/{change_set_id}/apply")
async def apply_plan_change_set(
    production_plan_id: int,
    change_set_id: int,
    skip_invalid: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    change_set = await db.get(PlanChangeSet, change_set_id)
    if change_set is None:
        raise HTTPException(status_code=404, detail="Change set not found")
    if change_set.production_plan_id != production_plan_id:
        raise HTTPException(status_code=400, detail="Change set does not belong to production plan")
    try:
        preview = await apply_change_set(db, change_set_id, skip_invalid=skip_invalid, changed_by=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return preview


@router.post("/{production_plan_id}/change-sets/{change_set_id}/rollback")
async def rollback_plan_change_set(
    production_plan_id: int,
    change_set_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    change_set = await db.get(PlanChangeSet, change_set_id)
    if change_set is None:
        raise HTTPException(status_code=404, detail="Change set not found")
    if change_set.production_plan_id != production_plan_id:
        raise HTTPException(status_code=400, detail="Change set does not belong to production plan")
    try:
        return await rollback_change_set(db, change_set_id, changed_by=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{production_plan_id}/change-sets/{change_set_id}")
async def discard_plan_change_set(
    production_plan_id: int,
    change_set_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Discard a change set: delete pending ones directly, rollback applied ones."""
    from sqlalchemy import delete

    change_set = await db.get(PlanChangeSet, change_set_id)
    if change_set is None:
        raise HTTPException(status_code=404, detail="Change set not found")
    if change_set.production_plan_id != production_plan_id:
        raise HTTPException(status_code=400, detail="Change set does not belong to production plan")

    # Запись лога аудита (отклонение импорта)
    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction, AuditEntityType
    await log_action(
        db,
        status="success",
        title="Импорт плана (отклонен)",
        message=f"Черновик пакета изменений импорта #{change_set_id} успешно отклонен и удален.",
        user=current_user,
        action=AuditAction.CANCEL,
        entity_type=AuditEntityType.IMPORT_BATCH,
        entity_id=batch_id,
    )

    batch_id = change_set.import_batch_id

    if change_set.status.value == "applied":
        await rollback_change_set(db, change_set_id)

    # Delete all change items
    await db.execute(delete(PlanChangeItem).where(PlanChangeItem.change_set_id == change_set_id))
    # Delete the change set and flush so follow-up queries see the real DB state.
    await db.delete(change_set)
    await db.flush()

    # If the batch has no other change sets, delete the batch and maybe file too.
    if batch_id:
        remaining_sets_count = (
            await db.execute(select(sa_func.count(PlanChangeSet.id)).where(PlanChangeSet.import_batch_id == batch_id))
        ).scalar() or 0
        if remaining_sets_count == 0:
            await _delete_batch_and_orphan_file(db, batch_id)

    await db.commit()

    return {"deleted": True, "change_set_id": change_set_id}


@router.delete("/{production_plan_id}/batches/{batch_id}")
async def delete_import_batch(
    production_plan_id: int,
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Rollback and delete an import batch along with all its positions, change sets, section plan lines, and work tasks."""
    from app.models.imports import ImportBatch
    from app.models.internal_plan import SectionPlanLine
    from app.models.work_task import WorkTask
    from sqlalchemy import delete

    batch = await db.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Import batch not found")

    # Rollback and delete all change sets for this batch
    change_sets = (
        await db.execute(select(PlanChangeSet).where(PlanChangeSet.import_batch_id == batch_id))
    ).scalars().all()

    for cs in change_sets:
        if cs.status.value == "applied":
            try:
                await rollback_change_set(db, cs.id)
            except ValueError:
                pass  # Ignore rollback errors, continue with deletion

        # Delete all change items
        await db.execute(delete(PlanChangeItem).where(PlanChangeItem.change_set_id == cs.id))
        # Delete the change set
        await db.delete(cs)

    # Find all plan positions for this batch to cascade delete related entities
    positions = (
        await db.execute(select(PlanPosition.id).where(PlanPosition.import_batch_id == batch_id))
    ).scalars().all()

    if positions:
        # Find all section plan lines for these positions
        section_plan_lines = (
            await db.execute(
                select(SectionPlanLine.id).where(SectionPlanLine.plan_position_id.in_(positions))
            )
        ).scalars().all()

        if section_plan_lines:
            from app.models.defect import Defect, DefectDecision, DefectItem, TransferDiscrepancyDefectItem
            from app.models.transfer import Transfer, TransferDiscrepancy

            # Find all work task IDs for these section plan lines
            task_ids = (
                await db.execute(
                    select(WorkTask.id).where(WorkTask.section_plan_line_id.in_(section_plan_lines))
                )
            ).scalars().all()

            if task_ids:
                # SpgRemainder/Movement cleanup removed — tables no longer exist.
                # Defects with movement_id/spg_remainder_id FK were cleaned up on migration.

                # Find affected transfers
                affected_transfer_ids = (
                    await db.execute(
                        select(Transfer.id).where(
                            (Transfer.from_task_id.in_(task_ids)) | (Transfer.to_task_id.in_(task_ids))
                        )
                    )
                ).scalars().all() or []

                # Handle transfers
                if affected_transfer_ids:
                    # Find discrepancies for these transfers
                    discrepancy_ids = (
                        await db.execute(
                            select(TransferDiscrepancy.id).where(
                                TransferDiscrepancy.transfer_id.in_(affected_transfer_ids)
                            )
                        )
                    ).scalars().all()

                    if discrepancy_ids:
                        # Delete defect items linked to discrepancies
                        await db.execute(
                            delete(TransferDiscrepancyDefectItem).where(
                                TransferDiscrepancyDefectItem.transfer_discrepancy_id.in_(discrepancy_ids)
                            )
                        )
                        # Delete the discrepancies
                        await db.execute(
                            delete(TransferDiscrepancy).where(
                                TransferDiscrepancy.id.in_(discrepancy_ids)
                            )
                        )

                    # Delete the transfers themselves
                    await db.execute(
                        delete(Transfer).where(
                            (Transfer.from_task_id.in_(task_ids)) | (Transfer.to_task_id.in_(task_ids))
                        )
                    )

                # Delete all work tasks linked via section plan lines for these positions
                await db.execute(delete(WorkTask).where(WorkTask.section_plan_line_id.in_(section_plan_lines)))

        # Delete all section plan lines for these positions
        await db.execute(delete(SectionPlanLine).where(SectionPlanLine.plan_position_id.in_(positions)))

    # Delete all plan positions created by this batch
    # Delete release batch positions linked to these plan positions
    if positions:
        from app.models.release_batch import ReleaseBatchPosition
        await db.execute(delete(ReleaseBatchPosition).where(ReleaseBatchPosition.plan_position_id.in_(positions)))
    await db.execute(delete(PlanPosition).where(PlanPosition.import_batch_id == batch_id))

    # Delete the batch and source file only when it is no longer referenced.
    await _delete_batch_and_orphan_file(db, batch_id)

    # Запись лога аудита
    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction, AuditEntityType
    await log_action(
        db,
        status="success",
        title="Удаление пакета импорта",
        message=f"Пакет импорта плана #{batch_id} успешно удален со всеми связанными позициями, задачами и движениями.",
        user=current_user,
        action=AuditAction.DELETE,
        entity_type=AuditEntityType.IMPORT_BATCH,
        entity_id=batch_id,
    )

    await db.commit()

    return {"deleted": True, "batch_id": batch_id}


@router.post("/{production_plan_id}/positions/{position_id}/approve")
async def approve_position(
    production_plan_id: int,
    position_id: int,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    import logging
    logger = logging.getLogger(__name__)
    try:
        position = await approve_plan_position(db, production_plan_id, position_id, force=force, changed_by=current_user.id)
    except ValueError as exc:
        logger.error("approve_position failed: %s (plan=%d, pos=%d, force=%s)", exc, production_plan_id, position_id, force)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": position.id,
        "production_plan_id": position.production_plan_id,
        "status": position.status.value,
        "validation_status": position.validation_status.value,
        "validation_errors": position.validation_errors,
    }


@router.post("/{production_plan_id}/positions/{position_id}/cancel")
async def cancel_position(
    production_plan_id: int,
    position_id: int,
    payload: StatusActionIn | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        position = await cancel_plan_position(
            db, production_plan_id, position_id, changed_by=current_user.id, reason=payload.reason if payload else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": position.id,
        "production_plan_id": position.production_plan_id,
        "status": position.status.value,
    }


@router.post("/{production_plan_id}/positions/{position_id}/restore")
async def restore_position(
    production_plan_id: int,
    position_id: int,
    payload: StatusActionIn | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        position = await restore_plan_position(
            db, production_plan_id, position_id, changed_by=current_user.id, reason=payload.reason if payload else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": position.id,
        "production_plan_id": position.production_plan_id,
        "status": position.status.value,
    }


@router.get("/{production_plan_id}/positions/{position_id}/history", response_model=list[AuditLogOut])
async def position_history(
    production_plan_id: int,
    position_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[AuditLogOut]:
    position = await db.get(PlanPosition, position_id)
    if position is None or position.production_plan_id != production_plan_id:
        raise HTTPException(status_code=404, detail="Position not found")

    # Получаем историю статусов из аудит-логов
    from app.models.audit_log import AuditEntityType
    logs = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.entity_type == AuditEntityType.PLAN_POSITION.value,
                AuditLog.entity_id == position_id,
            )
            .order_by(AuditLog.created_at.desc())
        )
    ).scalars().all()

    return [AuditLogOut.model_validate(log) for log in logs]


@router.delete("/{production_plan_id}/positions/{position_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_position(
    production_plan_id: int,
    position_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    position = await db.get(PlanPosition, position_id)
    if position is None or position.production_plan_id != production_plan_id:
        raise HTTPException(status_code=404, detail="Position not found")

    if position.status == PlanPositionStatus.cancelled:
        # Soft-delete cancelled positions
        await soft_delete_cancelled_position(
            db, production_plan_id, position_id, changed_by=current_user.id, reason="Удалена из списка"
        )
        await db.commit()
        return

    if position.deleted_at is not None:
        raise HTTPException(status_code=400, detail="Позиция уже удалена")

    if position.status in {PlanPositionStatus.approved, PlanPositionStatus.released}:
        raise HTTPException(status_code=400, detail="Нельзя удалить утверждённую или запущенную позицию. Используйте отмену.")

    # Delete related change items to avoid FK violation
    await db.execute(
        PlanChangeItem.__table__.delete().where(
            PlanChangeItem.plan_position_id == position_id
        )
    )

    # Запись лога аудита
    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction, AuditEntityType
    await log_action(
        db,
        status="success",
        title="Удаление позиции (жесткое)",
        message=f"Позиция плана #{position_id} (арт. {position.source_sku}) жестко удалена из системы.",
        user=current_user,
        product_sku=position.source_sku,
        action=AuditAction.DELETE,
        entity_type=AuditEntityType.PLAN_POSITION,
        entity_id=position_id,
        changes={"before": {"status": position.status.value}, "after": None},
    )

    # Hard delete for draft/invalid/valid
    await db.delete(position)
    await db.commit()


# --- Bulk action endpoints -------------------------------------------------


class BulkActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[int]
    reason: str | None = None
    force: bool = False


class BulkActionResultItem(BaseModel):
    id: int
    status: Literal["success", "failed", "skipped"]
    reason: str | None = None
    meta: dict | None = None


class BulkActionResponse(BaseModel):
    results: list[BulkActionResultItem]


@router.post(
    "/{production_plan_id}/positions/bulk-approve",
    response_model=BulkActionResponse,
    dependencies=[Depends(require_role(list(WRITER_ROLES)))],
)
async def bulk_approve_positions(
    production_plan_id: int,
    payload: BulkActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BulkActionResponse:
    """Approve multiple plan positions in a single request.

    Each position is processed in a savepoint so a single failure does
    not roll back the rest of the batch.
    """
    import logging
    logger = logging.getLogger(__name__)

    results: list[BulkActionResultItem] = []
    for position_id in payload.ids:
        try:
            async with db.begin_nested():
                position = await approve_plan_position(
                    db,
                    production_plan_id,
                    position_id,
                    force=payload.force,
                    changed_by=current_user.id,
                )
                results.append(
                    BulkActionResultItem(
                        id=position.id,
                        status="success",
                        meta={"production_plan_id": position.production_plan_id, "status": position.status.value},
                    )
                )
        except ValueError as exc:
            logger.warning(
                "bulk_approve_positions: position %s failed: %s", position_id, exc,
            )
            results.append(BulkActionResultItem(id=position_id, status="failed", reason=str(exc)))
        except Exception as exc:
            logger.exception("bulk_approve_positions: unexpected error for id %s", position_id)
            results.append(
                BulkActionResultItem(id=position_id, status="failed", reason="Внутренняя ошибка сервера")
            )
    return BulkActionResponse(results=results)


@router.post(
    "/{production_plan_id}/positions/bulk-delete",
    response_model=BulkActionResponse,
    dependencies=[Depends(require_role(list(WRITER_ROLES)))],
)
async def bulk_delete_positions(
    production_plan_id: int,
    payload: BulkActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BulkActionResponse:
    """Delete multiple plan positions in a single request.

    Cancelled positions are soft-deleted; all other eligible positions
    are hard-deleted together with their related ``PlanChangeItem`` rows.
    Each item runs in a savepoint.
    """
    import logging
    logger = logging.getLogger(__name__)

    results: list[BulkActionResultItem] = []
    for position_id in payload.ids:
        try:
            async with db.begin_nested():
                position = await db.get(PlanPosition, position_id)
                if position is None or position.production_plan_id != production_plan_id:
                    raise ValueError("Position not found")
                if position.deleted_at is not None:
                    results.append(
                        BulkActionResultItem(id=position_id, status="skipped", reason="Позиция уже удалена")
                    )
                    continue
                if position.status == PlanPositionStatus.cancelled:
                    await soft_delete_cancelled_position(
                        db,
                        production_plan_id,
                        position_id,
                        changed_by=current_user.id,
                        reason=payload.reason or "Удалена из списка",
                    )
                elif position.status in {PlanPositionStatus.approved, PlanPositionStatus.released}:
                    raise ValueError(
                        "Нельзя удалить утверждённую или запущенную позицию. Используйте отмену."
                    )
                else:
                    await db.execute(
                        PlanChangeItem.__table__.delete().where(
                            PlanChangeItem.plan_position_id == position_id
                        )
                    )
                    # Запись лога аудита (удаление позиции)
                    from app.services.audit_log_service import log_action
                    from app.models.audit_log import AuditAction, AuditEntityType
                    await log_action(
                        db,
                        status="success",
                        title="Удаление позиции (жесткое)",
                        message=f"Позиция плана #{position_id} (арт. {position.source_sku}) жестко удалена из системы.",
                        user=current_user,
                        product_sku=position.source_sku,
                        action=AuditAction.DELETE,
                        entity_type=AuditEntityType.PLAN_POSITION,
                        entity_id=position_id,
                        changes={"before": {"status": position.status.value}, "after": None},
                    )
                    await db.delete(position)
                results.append(BulkActionResultItem(id=position_id, status="success"))
        except ValueError as exc:
            logger.warning(
                "bulk_delete_positions: position %s failed: %s", position_id, exc,
            )
            results.append(BulkActionResultItem(id=position_id, status="failed", reason=str(exc)))
        except Exception as exc:
            logger.exception("bulk_delete_positions: unexpected error for id %s", position_id)
            results.append(
                BulkActionResultItem(id=position_id, status="failed", reason="Внутренняя ошибка сервера")
            )
    return BulkActionResponse(results=results)


@router.post("/{production_plan_id}/release-batches", status_code=status.HTTP_201_CREATED)
async def create_plan_release_batch(
    production_plan_id: int,
    payload: ReleaseBatchCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await create_release_batch(
            db,
            production_plan_id=production_plan_id,
            positions=[item.model_dump() for item in payload.positions] if payload.positions else None,
            batch_type=payload.batch_type,
            name=payload.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{production_plan_id}/positions/{position_id}/route-check")
async def route_check(
    production_plan_id: int,
    position_id: int,
    db: AsyncSession = Depends(get_db),
) -> RouteCheckOut:
    position = await db.get(PlanPosition, position_id)
    if position is None:
        raise HTTPException(status_code=404, detail="Position not found")
    if position.production_plan_id != production_plan_id:
        raise HTTPException(status_code=400, detail="Position does not belong to production plan")

    import_batch = await db.get(ImportBatch, position.import_batch_id) if position.import_batch_id is not None else None
    rule_profile_id = import_batch.rule_profile_id if import_batch is not None else None
    template_id = import_batch.template_id if import_batch is not None else None

    product = await db.get(Product, position.product_id) if position.product_id is not None else None
    selection = await select_route_for_payload(db, position.source_payload, product, profile_id=rule_profile_id)
    expected_signature = {
        "template_id": template_id,
        "rule_profile_id": rule_profile_id,
        "matched_rule_ids": selection.matched_rule_ids,
        "required_sections": selection.required_sections,
        "excluded_sections": selection.excluded_sections,
        "candidate_routes": [
            {
                "route_id": candidate.route_id,
                "route_name": candidate.route_name,
                "section_ids": candidate.section_ids,
                "section_codes": candidate.section_codes,
                "missing_required_section_ids": candidate.missing_required_section_ids,
                "excluded_present_section_ids": candidate.excluded_present_section_ids,
                "extra_controlled_sections_count": candidate.extra_controlled_sections_count,
                "matched": candidate.matched,
            }
            for candidate in selection.candidate_routes
        ],
        "selected_route_id": selection.route.id if selection.route else None,
        "route_match_reason": selection.route_match_reason,
        "condition_diagnostics": selection.condition_diagnostics,
        "excel_column_diagnostics": [
            diagnostic for diagnostic in selection.condition_diagnostics if diagnostic.get("source") == "excel"
        ],
    }

    issues = await validate_route_match(db, position)

    active_route_snapshot = None
    route_info = await resolve_position_route(db, position)
    if route_info.route_id is None:
        issues = [route_info.error or "route_not_found", *issues]
    if route_info.route_id:
        stages_result = await db.execute(
            select(RouteStage, Section)
            .join(Section, RouteStage.section_id == Section.id)
            .where(RouteStage.route_id == route_info.route_id)
            .order_by(RouteStage.sequence)
        )
        active_route_snapshot = {
            "route_id": route_info.route_id,
            "route_name": route_info.route_name,
            "route_source": route_info.source,
            "steps": [
                {
                    "sequence": stage.sequence,
                    "section_id": stage.section_id,
                    "section_code": section.code,
                    "section_name": section.name,
                    "section_type": section.type,
                    "operation_name": ", ".join(op.operation_name for op in stage.operations) if stage.operations else "",
                }
                for stage, section in stages_result.all()
            ],
            "diagnostic": {
                "error": route_info.error,
                "template_id": template_id,
                "rule_profile_id": rule_profile_id,
                "matched_rule_ids": route_info.checked_rules,
                "required_sections": route_info.required_sections,
                "excluded_sections": route_info.excluded_sections,
                "candidate_routes": [
                    {
                        "route_id": candidate.route_id,
                        "route_name": candidate.route_name,
                        "section_ids": candidate.section_ids,
                        "section_codes": candidate.section_codes,
                        "missing_required_section_ids": candidate.missing_required_section_ids,
                        "excluded_present_section_ids": candidate.excluded_present_section_ids,
                        "extra_controlled_sections_count": candidate.extra_controlled_sections_count,
                        "matched": candidate.matched,
                    }
                    for candidate in route_info.candidate_routes
                ],
                "selected_route_id": route_info.selected_route_id,
                "route_match_reason": route_info.route_match_reason,
                "condition_diagnostics": route_info.condition_diagnostics,
                "excel_column_diagnostics": [
                    diagnostic for diagnostic in route_info.condition_diagnostics if diagnostic.get("source") == "excel"
                ],
            },
        }

    return RouteCheckOut(
        expected_signature=expected_signature,
        active_route_snapshot=active_route_snapshot,
        match=len(issues) == 0,
        issues=issues,
    )


@router.get("/{production_plan_id}/section-totals")
async def section_totals(
    production_plan_id: int,
    db: AsyncSession = Depends(get_db),
) -> SectionTotalsOut:
    positions = (
        await db.execute(
            select(PlanPosition).where(PlanPosition.production_plan_id == production_plan_id)
        )
    ).scalars().all()

    if not positions:
        return SectionTotalsOut(production_plan_id=production_plan_id, totals=[])

    totals_by_section: dict[int, dict] = {}
    route_resolve_cache = {}
    route_stages_cache = {}

    for position in positions:
        if position.product_id is None:
            continue
        
        cache_key = make_position_route_cache_key(position)
        if cache_key in route_resolve_cache:
            route_info = route_resolve_cache[cache_key]
        else:
            route_info = await resolve_position_route(db, position)
            route_resolve_cache[cache_key] = route_info

        if route_info.route_id is None:
            continue

        if route_info.route_id in route_stages_cache:
            stages = route_stages_cache[route_info.route_id]
        else:
            stages = (
                await db.execute(
                    select(RouteStage, Section)
                    .join(Section, RouteStage.section_id == Section.id)
                    .where(RouteStage.route_id == route_info.route_id)
                    .order_by(RouteStage.sequence)
                )
            ).all()
            route_stages_cache[route_info.route_id] = stages

        for _, section in stages:
            bucket = totals_by_section.setdefault(
                section.id,
                {
                    "section_id": section.id,
                    "section_code": section.code,
                    "section_name": section.name,
                    "section_type": section.type,
                    "positions": set(),
                    "input": 0,
                    "output": 0,
                },
            )
            bucket["positions"].add(position.id)
            # MVP assumes 1:1 transformation on route step level.
            bucket["input"] += position.quantity
            bucket["output"] += position.quantity

    totals = [
        SectionTotalsLineOut(
            section_id=b["section_id"],
            section_code=b["section_code"],
            section_name=b["section_name"],
            section_type=b["section_type"],
            positions_count=len(b["positions"]),
            planned_input_quantity=str(b["input"]),
            planned_output_quantity=str(b["output"]),
        )
        for b in totals_by_section.values()
    ]
    totals.sort(key=lambda item: item.section_code)
    return SectionTotalsOut(production_plan_id=production_plan_id, totals=totals)


class PlanFileInfo(BaseModel):
    batch_id: int
    file_id: int
    filename: str
    extension: str
    size_bytes: int
    sheet_name: str
    total_rows: int
    parsed_rows: int
    status: str
    created_at: str


@router.get("/{production_plan_id}/files")
async def plan_files(production_plan_id: int, db: AsyncSession = Depends(get_db)) -> list[PlanFileInfo]:
    from app.models.imports import ImportBatch, ImportFile

    batches = (
        await db.execute(
            select(ImportBatch, ImportFile)
            .join(ImportFile, ImportBatch.source_file_id == ImportFile.id)
            .where(ImportBatch.production_plan_id == production_plan_id)
            .order_by(ImportBatch.created_at)
        )
    ).all()
    return [
        PlanFileInfo(
            batch_id=batch.id,
            file_id=file.id,
            filename=file.original_filename,
            extension=file.file_extension,
            size_bytes=file.size_bytes,
            sheet_name=batch.sheet_name,
            total_rows=batch.total_rows,
            parsed_rows=batch.parsed_rows,
            status=batch.status.value,
            created_at=batch.created_at.isoformat(),
        )
        for batch, file in batches
    ]


class PlanPositionOut(BaseModel):
    id: int
    production_plan_id: int
    source_sku: str
    source_name: str | None
    quantity: str
    status: str
    validation_status: str
    errors: list
    warnings: list
    source_row_number: int | None
    source_row_numbers: list[int] | None = None
    source_ref: str | None = None
    change_action: str | None = None
    product_id: int | None = None
    route_id: int | None = None
    route_profile_id: int | None = None
    route_name: str | None = None
    route_source: str | None = None  # compatibility: "manual" | "auto" | "legacy" | "missing"
    route_origin: str | None = None  # "manual_confirmed" | "auto" | "legacy"
    route_match_quality: str | None = None  # "exact" | "corrected" | "unknown"
    route_match_reason: str | None = None
    route_assigned_at: str | None = None
    route_manual_confirmed_at: str | None = None
    route_error: str | None = None
    raw_excel_row: dict | None = None
    payload: dict | None = None
    available_remainder_quantity: float | None = None
    # Операция группы строк (ADR-0003): один вход, 1..N выходов.
    input_quantity: str | None = None
    input_dimensions: dict | None = None
    outputs: list | None = None
    operation_summary: str | None = None


def _format_position_quantity(value) -> str:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    text_value = str(value)
    if "." in text_value:
        text_value = text_value.rstrip("0").rstrip(".")
    return text_value


def _position_operation_fields(position: PlanPosition) -> dict:
    """Поля операции группы для PlanPositionOut, включая сводку вида
    «150 шт × 2,7 м → 150 × 0,9 м + 150 × 1,8 м» (ADR-0003)."""
    outputs = list(position.outputs or [])
    input_quantity = (
        _format_position_quantity(position.input_quantity)
        if position.input_quantity is not None
        else None
    )
    summary = format_operation_summary(
        position.input_quantity, position.input_dimensions, outputs
    )
    return {
        "input_quantity": input_quantity,
        "input_dimensions": position.input_dimensions,
        "outputs": outputs or None,
        "operation_summary": summary,
    }


def _source_row_numbers_from_position(position: PlanPosition) -> list[int] | None:
    payload = position.source_payload or {}
    raw_row_numbers = payload.get("row_numbers")
    if isinstance(raw_row_numbers, list):
        result: list[int] = []
        for value in raw_row_numbers:
            try:
                result.append(int(value))
            except (TypeError, ValueError):
                continue
        if result:
            return result
    if position.source_row_number is not None:
        return [position.source_row_number]
    return None


async def _compute_available_remainder_for_positions(
    db: AsyncSession,
    positions: list[PlanPosition],
    route_info_by_id: dict[int, ResolvedRouteInfo],
) -> dict[int, float]:
    """Считает available_remainder_quantity для списка позиций плана.

    Для каждой позиции: резолвит effective_product_id, загружает route_remainder_steps
    (один раз на route_id), вызывает compute_available_remainder_quantity.
    Возвращает dict {position_id: available_remainder_quantity}.
    """
    from sqlalchemy.orm import selectinload

    from app.services.position_remainders import compute_available_remainder_quantities
    from app.services.production_planning_rows import _resolve_effective_product_id

    if not positions:
        return {}

    # Резолвим effective_product_id для каждой позиции (включая paired_techcard).
    effective_product_by_id: dict[int, int | None] = {}
    for p in positions:
        effective_product_by_id[p.id] = await _resolve_effective_product_id(db, p)

    # Собираем уникальные route_id'ы.
    unique_route_ids = {
        info.route_id
        for info in route_info_by_id.values()
        if info.route_id is not None
    }
    route_remainder_steps_by_route_id: dict[int, list[dict]] = {}
    if unique_route_ids:
        rows = (
            await db.execute(
                select(RouteStage, Section)
                .options(selectinload(RouteStage.operations))
                .join(Section, RouteStage.section_id == Section.id)
                .where(RouteStage.route_id.in_(unique_route_ids))
                .where(Section.is_active == True)
                .order_by(RouteStage.route_id, RouteStage.sequence)
            )
        ).all()
        for stage, section in rows:
            route_remainder_steps_by_route_id.setdefault(stage.route_id, []).append(
                {
                    "sequence": stage.sequence,
                    "section_id": section.id,
                    "operation_codes": {op.operation_code for op in (stage.operations or [])},
                }
            )

    product_ids_for_remainders: set[int] = set()
    for p in positions:
        info = route_info_by_id.get(p.id)
        if info is None or info.route_id is None:
            continue
        if not route_remainder_steps_by_route_id.get(info.route_id):
            continue
        effective_id = effective_product_by_id.get(p.id)
        if effective_id is not None:
            product_ids_for_remainders.add(effective_id)

    available_by_product = await compute_available_remainder_quantities(
        db,
        product_ids_for_remainders,
    )

    result: dict[int, float] = {}
    for p in positions:
        info = route_info_by_id.get(p.id)
        if info is None or info.route_id is None:
            result[p.id] = 0.0
            continue
        steps = route_remainder_steps_by_route_id.get(info.route_id) or []
        if not steps:
            result[p.id] = 0.0
            continue
        effective_id = effective_product_by_id.get(p.id)
        result[p.id] = available_by_product.get(effective_id, 0.0) if effective_id is not None else 0.0
    return result


ALL_POSITIONS_PLANNING_STATUSES = (
    PlanPositionStatus.draft,
    PlanPositionStatus.invalid,
    PlanPositionStatus.valid,
)

ALL_POSITIONS_SORT_FIELDS = frozenset({
    "source_row_number",
    "source_sku",
    "quantity",
    "status",
    "validation_status",
    "period_start",
})


class AllPlanPositionsListResponse(BaseModel):
    positions: list[PlanPositionOut]
    total: int
    limit: int
    offset: int


def _apply_all_positions_filters(
    stmt,
    *,
    search: str | None,
    status: str | None,
    validation_status: str | None,
    source_sku: str | None,
    source_name: str | None,
    has_route: str | None,
    has_errors: str | None,
    has_warnings: str | None,
):
    stmt = stmt.where(
        PlanPosition.status.in_(ALL_POSITIONS_PLANNING_STATUSES),
        PlanPosition.deleted_at.is_(None),
    )

    if status:
        try:
            status_enum = PlanPositionStatus(status)
        except ValueError:
            status_enum = None
        if status_enum in ALL_POSITIONS_PLANNING_STATUSES:
            stmt = stmt.where(PlanPosition.status == status_enum)

    if validation_status:
        try:
            validation_enum = PlanPositionValidationStatus(validation_status)
        except ValueError:
            validation_enum = None
        if validation_enum is not None:
            stmt = stmt.where(PlanPosition.validation_status == validation_enum)

    if source_sku:
        stmt = stmt.where(PlanPosition.source_sku.ilike(f"%{source_sku}%"))
    if source_name:
        stmt = stmt.where(PlanPosition.source_name.ilike(f"%{source_name}%"))

    if has_route == "yes":
        stmt = stmt.where(PlanPosition.route_id.is_not(None))
    elif has_route == "no":
        stmt = stmt.where(PlanPosition.route_id.is_(None))

    errors_len = sa_func.coalesce(sa_func.jsonb_array_length(PlanPosition.validation_errors), 0)
    if has_errors == "yes":
        stmt = stmt.where(errors_len > 0)
    elif has_errors == "no":
        stmt = stmt.where(errors_len == 0)

    if has_warnings in {"yes", "no"}:
        warnings_exists = (
            select(PlanChangeItem.id)
            .where(PlanChangeItem.plan_position_id == PlanPosition.id)
            .where(sa_func.coalesce(sa_func.jsonb_array_length(PlanChangeItem.warnings), 0) > 0)
            .correlate(PlanPosition)
        )
        if has_warnings == "yes":
            stmt = stmt.where(exists(warnings_exists))
        else:
            stmt = stmt.where(~exists(warnings_exists))

    if search:
        search_like = f"%{search}%"
        stmt = stmt.outerjoin(Product, Product.id == PlanPosition.product_id)
        stmt = stmt.where(
            or_(
                PlanPosition.source_sku.ilike(search_like),
                PlanPosition.source_name.ilike(search_like),
                Product.sku.ilike(search_like),
                Product.name.ilike(search_like),
            )
        )

    return stmt


def _all_positions_order_columns(sort_by: str, sort_order: str):
    resolved_sort_by = sort_by if sort_by in ALL_POSITIONS_SORT_FIELDS else "source_row_number"
    if sort_order not in ("asc", "desc"):
        sort_order = "asc"

    if resolved_sort_by == "source_sku":
        order_column = PlanPosition.source_sku
    elif resolved_sort_by == "quantity":
        order_column = PlanPosition.quantity
    elif resolved_sort_by == "status":
        order_column = cast(PlanPosition.status, String)
    elif resolved_sort_by == "validation_status":
        order_column = cast(PlanPosition.validation_status, String)
    elif resolved_sort_by == "period_start":
        order_column = PlanPosition.period_start
    else:
        order_column = PlanPosition.source_row_number

    if sort_order == "asc":
        return order_column.asc(), PlanPosition.id.asc()
    return order_column.desc(), PlanPosition.id.desc()


async def _serialize_plan_positions(
    db: AsyncSession,
    positions: list[PlanPosition],
) -> list[PlanPositionOut]:
    from app.models.production_plan import PlanChangeItem

    if not positions:
        return []

    change_items = (
        await db.execute(
            select(PlanChangeItem).where(
                PlanChangeItem.plan_position_id.in_([p.id for p in positions])
            )
        )
    ).scalars().all()
    warnings_by_position = {ci.plan_position_id: ci.warnings for ci in change_items if ci.plan_position_id}

    route_resolve_cache: dict[tuple, ResolvedRouteInfo] = {}
    route_info_by_id: dict[int, ResolvedRouteInfo] = {}

    for p in positions:
        cache_key = make_position_route_cache_key(p)
        if cache_key in route_resolve_cache:
            route_info = route_resolve_cache[cache_key]
        else:
            route_info = await resolve_position_route(db, p)
            route_resolve_cache[cache_key] = route_info
        route_info_by_id[p.id] = route_info

    available_remainder_by_id = await _compute_available_remainder_for_positions(
        db, positions, route_info_by_id
    )

    result: list[PlanPositionOut] = []
    for p in positions:
        route_info = route_info_by_id[p.id]
        result.append(
            PlanPositionOut(
                id=p.id,
                production_plan_id=p.production_plan_id,
                source_sku=p.source_sku,
                source_name=p.source_name,
                quantity=str(p.quantity),
                status=p.status.value,
                validation_status=p.validation_status.value,
                errors=[format_validation_error(e) for e in (p.validation_errors or [])],
                source_row_number=p.source_row_number,
                source_row_numbers=_source_row_numbers_from_position(p),
                source_ref=p.source_ref,
                warnings=warnings_by_position.get(p.id, []) or [],
                product_id=p.product_id,
                route_id=route_info.route_id,
                route_profile_id=p.route_profile_id,
                route_name=route_info.route_name,
                route_source=route_info.source,
                route_origin=route_info.route_origin,
                route_match_quality=route_info.route_match_quality,
                route_match_reason=route_info.route_match_reason,
                route_assigned_at=route_info.route_assigned_at.isoformat() if route_info.route_assigned_at else None,
                route_manual_confirmed_at=(
                    route_info.route_manual_confirmed_at.isoformat() if route_info.route_manual_confirmed_at else None
                ),
                route_error=route_info.error,
                raw_excel_row=(p.source_payload or {}).get("raw_excel_row"),
                payload=p.source_payload,
                available_remainder_quantity=round(available_remainder_by_id.get(p.id, 0.0), 3),
                **_position_operation_fields(p),
            )
        )
    return result


@router.get("/all-files", response_model=list[PlanFileInfo])
async def all_plan_files(db: AsyncSession = Depends(get_db)) -> list[PlanFileInfo]:
    """Return files from all production plans."""
    from app.models.imports import ImportBatch, ImportFile

    batches = (
        await db.execute(
            select(ImportBatch, ImportFile)
            .join(ImportFile, ImportBatch.source_file_id == ImportFile.id)
            .order_by(ImportBatch.created_at.desc())
        )
    ).all()
    return [
        PlanFileInfo(
            batch_id=batch.id,
            file_id=file.id,
            filename=file.original_filename,
            extension=file.file_extension,
            size_bytes=file.size_bytes,
            sheet_name=batch.sheet_name,
            total_rows=batch.total_rows,
            parsed_rows=batch.parsed_rows,
            status=batch.status.value,
            created_at=batch.created_at.isoformat(),
        )
        for batch, file in batches
    ]


@router.get("/all-positions", response_model=AllPlanPositionsListResponse)
async def all_plan_positions(
    search: str | None = Query(default=None, description="Поиск по source_sku, source_name, product sku/name"),
    status: str | None = Query(default=None, description="Фильтр статуса: draft, valid, invalid"),
    validation_status: str | None = Query(default=None, description="Фильтр validation_status"),
    source_sku: str | None = Query(default=None, description="Column filter: ILIKE по source_sku"),
    source_name: str | None = Query(default=None, description="Column filter: ILIKE по source_name"),
    has_route: str | None = Query(default=None, description="Фильтр маршрута: yes | no"),
    has_errors: str | None = Query(default=None, description="Фильтр ошибок валидации: yes | no"),
    has_warnings: str | None = Query(default=None, description="Фильтр предупреждений импорта: yes | no"),
    sort_by: str = Query(default="source_row_number"),
    sort_order: str = Query(default="asc"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> AllPlanPositionsListResponse:
    """Return paginated positions from all production plans in planning stage (draft/invalid/valid)."""
    stmt = select(PlanPosition)
    stmt = _apply_all_positions_filters(
        stmt,
        search=search,
        status=status,
        validation_status=validation_status,
        source_sku=source_sku,
        source_name=source_name,
        has_route=has_route,
        has_errors=has_errors,
        has_warnings=has_warnings,
    )

    count_stmt = select(sa_func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    primary_order, tiebreaker_order = _all_positions_order_columns(sort_by, sort_order)
    positions = (
        await db.execute(
            stmt.order_by(primary_order, tiebreaker_order).limit(limit).offset(offset)
        )
    ).scalars().all()

    serialized = await _serialize_plan_positions(db, positions)
    return AllPlanPositionsListResponse(
        positions=serialized,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/cancelled-positions", response_model=list[PlanPositionOut])
async def cancelled_positions(db: AsyncSession = Depends(get_db)) -> list[PlanPositionOut]:
    """Return cancelled positions (for execution history/audit view)."""
    from app.models.production_plan import PlanChangeItem

    positions = (
        await db.execute(
            select(PlanPosition)
            .where(PlanPosition.status == PlanPositionStatus.cancelled)
            .where(PlanPosition.deleted_at.is_(None))
            .order_by(PlanPosition.source_row_number, PlanPosition.id)
        )
    ).scalars().all()

    change_items = (
        await db.execute(
            select(PlanChangeItem).where(
                PlanChangeItem.plan_position_id.in_([p.id for p in positions])
            )
        )
    ).scalars().all()
    warnings_by_position = {ci.plan_position_id: ci.warnings for ci in change_items if ci.plan_position_id}

    route_resolve_cache: dict[tuple, ResolvedRouteInfo] = {}
    route_info_by_id: dict[int, ResolvedRouteInfo] = {}

    for p in positions:
        cache_key = make_position_route_cache_key(p)
        if cache_key in route_resolve_cache:
            route_info = route_resolve_cache[cache_key]
        else:
            route_info = await resolve_position_route(db, p)
            route_resolve_cache[cache_key] = route_info
        route_info_by_id[p.id] = route_info

    available_remainder_by_id = await _compute_available_remainder_for_positions(
        db, positions, route_info_by_id
    )

    result = []
    for p in positions:
        route_info = route_info_by_id[p.id]
        result.append(
            PlanPositionOut(
                id=p.id,
                production_plan_id=p.production_plan_id,
                source_sku=p.source_sku,
                source_name=p.source_name,
                quantity=str(p.quantity),
                status=p.status.value,
                validation_status=p.validation_status.value,
                errors=[format_validation_error(e) for e in (p.validation_errors or [])],
                source_row_number=p.source_row_number,
                source_row_numbers=_source_row_numbers_from_position(p),
                source_ref=p.source_ref,
                warnings=warnings_by_position.get(p.id, []) or [],
                product_id=p.product_id,
                route_id=route_info.route_id,
                route_profile_id=p.route_profile_id,
                route_name=route_info.route_name,
                route_source=route_info.source,
                route_origin=route_info.route_origin,
                route_match_quality=route_info.route_match_quality,
                route_match_reason=route_info.route_match_reason,
                route_assigned_at=route_info.route_assigned_at.isoformat() if route_info.route_assigned_at else None,
                route_manual_confirmed_at=(
                    route_info.route_manual_confirmed_at.isoformat() if route_info.route_manual_confirmed_at else None
                ),
                route_error=route_info.error,
                raw_excel_row=(p.source_payload or {}).get("raw_excel_row"),
                payload=p.source_payload,
                available_remainder_quantity=round(available_remainder_by_id.get(p.id, 0.0), 3),
                **_position_operation_fields(p),
            )
        )

    return result


@router.get("/{production_plan_id}/all-positions")
async def all_positions(production_plan_id: int, db: AsyncSession = Depends(get_db)) -> list[PlanPositionOut]:
    from app.models.production_plan import PlanChangeItem

    positions = (
        await db.execute(
            select(PlanPosition)
            .where(PlanPosition.production_plan_id == production_plan_id)
            .where(PlanPosition.status.in_([PlanPositionStatus.draft, PlanPositionStatus.invalid, PlanPositionStatus.valid]))
            .where(PlanPosition.deleted_at.is_(None))
            .order_by(PlanPosition.source_row_number, PlanPosition.id)
        )
    ).scalars().all()

    # Gather warnings from change items
    change_items = (
        await db.execute(
            select(PlanChangeItem).where(
                PlanChangeItem.plan_position_id.in_([p.id for p in positions])
            )
        )
    ).scalars().all()
    warnings_by_position = {ci.plan_position_id: ci.warnings for ci in change_items if ci.plan_position_id}

    # Cache resolved routes
    route_resolve_cache: dict[tuple, ResolvedRouteInfo] = {}
    route_info_by_id: dict[int, ResolvedRouteInfo] = {}

    for p in positions:
        cache_key = make_position_route_cache_key(p)
        if cache_key in route_resolve_cache:
            route_info = route_resolve_cache[cache_key]
        else:
            route_info = await resolve_position_route(db, p)
            route_resolve_cache[cache_key] = route_info
        route_info_by_id[p.id] = route_info

    available_remainder_by_id = await _compute_available_remainder_for_positions(
        db, positions, route_info_by_id
    )

    result = []
    for p in positions:
        route_info = route_info_by_id[p.id]
        result.append(
            PlanPositionOut(
                id=p.id,
                production_plan_id=p.production_plan_id,
                source_sku=p.source_sku,
                source_name=p.source_name,
                quantity=str(p.quantity),
                status=p.status.value,
                validation_status=p.validation_status.value,
                errors=[format_validation_error(e) for e in (p.validation_errors or [])],
                source_row_number=p.source_row_number,
                source_row_numbers=_source_row_numbers_from_position(p),
                source_ref=p.source_ref,
                warnings=warnings_by_position.get(p.id, []) or [],
                product_id=p.product_id,
                route_id=route_info.route_id,
                route_profile_id=p.route_profile_id,
                route_name=route_info.route_name,
                route_source=route_info.source,
                route_origin=route_info.route_origin,
                route_match_quality=route_info.route_match_quality,
                route_match_reason=route_info.route_match_reason,
                route_assigned_at=route_info.route_assigned_at.isoformat() if route_info.route_assigned_at else None,
                route_manual_confirmed_at=(
                    route_info.route_manual_confirmed_at.isoformat() if route_info.route_manual_confirmed_at else None
                ),
                route_error=route_info.error,
                raw_excel_row=(p.source_payload or {}).get("raw_excel_row"),
                payload=p.source_payload,
                available_remainder_quantity=round(available_remainder_by_id.get(p.id, 0.0), 3),
                **_position_operation_fields(p),
            )
        )

    return result


class BatchAssignRouteIn(BaseModel):
    position_ids: list[int]
    route_id: int | None


class BatchAssignRouteOut(BaseModel):
    updated_count: int
    route_id: int | None
    route_name: str | None


@router.post("/positions/batch-assign-route", response_model=BatchAssignRouteOut)
async def batch_assign_route_global(
    payload: BatchAssignRouteIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BatchAssignRouteOut:
    """Assign route to positions by their IDs, regardless of which plan they belong to."""
    if not payload.position_ids:
        raise HTTPException(status_code=400, detail="position_ids must not be empty")

    route_name = None
    if payload.route_id is not None:
        route = await db.get(ProductionRoute, payload.route_id)
        if route is None:
            raise HTTPException(status_code=404, detail="Route not found")
        if not route.is_active:
            raise HTTPException(status_code=400, detail="Route is not active")
        route_name = route.name

    positions = (
        await db.execute(
            select(PlanPosition).where(
                PlanPosition.id.in_(payload.position_ids),
            )
        )
    ).scalars().all()

    for pos in positions:
        pos.route_id = payload.route_id
        if payload.route_id is None:
            pos.route_origin = None
            pos.route_match_quality = None
            pos.route_match_reason = None
            pos.route_assigned_at = None
            pos.route_manual_confirmed_at = None
        else:
            now = datetime.now(UTC)
            pos.route_origin = PlanPositionRouteOrigin.manual_confirmed
            pos.route_match_quality = None
            pos.route_match_reason = None
            pos.route_assigned_at = now
            pos.route_manual_confirmed_at = now

    # Запись лога аудита (назначение маршрута)
    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction, AuditEntityType
    route_details = f"маршрут '{route_name}'" if route_name else "автоматический маршрут (сброшен)"
    
    # Для группового действия логируем изменения для каждой позиции
    changes_dict = {}
    for pos in positions:
        changes_dict[str(pos.id)] = {"before": {"route_id": pos.route_id}, "after": {"route_id": payload.route_id}}
        
    await log_action(
        db,
        status="success",
        title="Назначение маршрута",
        message=f"Позициям плана [{', '.join(map(str, payload.position_ids))}] назначен {route_details}.",
        user=current_user,
        action=AuditAction.UPDATE,
        entity_type=AuditEntityType.PLAN_POSITION,
        changes=changes_dict,
    )

    await db.commit()

    return BatchAssignRouteOut(
        updated_count=len(positions),
        route_id=payload.route_id,
        route_name=route_name,
    )


@router.post("/{production_plan_id}/positions/batch-assign-route", response_model=BatchAssignRouteOut)
async def batch_assign_route(
    production_plan_id: int,
    payload: BatchAssignRouteIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BatchAssignRouteOut:
    print(f"DEBUG batch_assign_route: plan_id={production_plan_id}, position_ids={payload.position_ids}, route_id={payload.route_id}")

    plan = await db.get(ProductionPlan, production_plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Production plan not found")

    if not payload.position_ids:
        raise HTTPException(status_code=400, detail="position_ids must not be empty")

    route_name = None
    if payload.route_id is not None:
        route = await db.get(ProductionRoute, payload.route_id)
        if route is None:
            raise HTTPException(status_code=404, detail="Route not found")
        if not route.is_active:
            raise HTTPException(status_code=400, detail="Route is not active")
        route_name = route.name

    positions = (
        await db.execute(
            select(PlanPosition).where(
                PlanPosition.id.in_(payload.position_ids),
                PlanPosition.production_plan_id == production_plan_id,
            )
        )
    ).scalars().all()

    if len(positions) != len(payload.position_ids):
        raise HTTPException(status_code=400, detail="Some positions not found or belong to a different plan")

    for pos in positions:
        pos.route_id = payload.route_id
        if payload.route_id is None:
            pos.route_origin = None
            pos.route_match_quality = None
            pos.route_match_reason = None
            pos.route_assigned_at = None
            pos.route_manual_confirmed_at = None
        else:
            now = datetime.now(UTC)
            pos.route_origin = PlanPositionRouteOrigin.manual_confirmed
            pos.route_match_quality = None
            pos.route_match_reason = None
            pos.route_assigned_at = now
            pos.route_manual_confirmed_at = now

    # Запись лога аудита (назначение маршрута)
    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction, AuditEntityType
    route_details = f"маршрут '{route_name}'" if route_name else "автоматический маршрут (сброшен)"
    
    changes_dict = {}
    for pos in positions:
        changes_dict[str(pos.id)] = {"before": {"route_id": pos.route_id}, "after": {"route_id": payload.route_id}}

    await log_action(
        db,
        status="success",
        title="Назначение маршрута",
        message=f"Позициям плана [{', '.join(map(str, payload.position_ids))}] назначен {route_details} в плане #{production_plan_id}.",
        user=current_user,
        action=AuditAction.UPDATE,
        entity_type=AuditEntityType.PLAN_POSITION,
        changes=changes_dict,
    )

    await db.commit()

    return BatchAssignRouteOut(
        updated_count=len(positions),
        route_id=payload.route_id,
        route_name=route_name,
    )


class DuplicateGroup(BaseModel):
    source_fingerprint: str
    positions: list[dict]


@router.get("/{production_plan_id}/duplicates", response_model=list[DuplicateGroup])
async def find_plan_duplicates(production_plan_id: int, db: AsyncSession = Depends(get_db)) -> list[DuplicateGroup]:
    """Find duplicate positions by unique Excel row fingerprint within a production plan."""
    positions = (
        await db.execute(
            select(PlanPosition)
            .where(
                PlanPosition.production_plan_id == production_plan_id,
                PlanPosition.status != PlanPositionStatus.cancelled,
                PlanPosition.deleted_at.is_(None),
            )
            .order_by(PlanPosition.source_sku, PlanPosition.source_row_number)
        )
    ).scalars().all()

    from collections import defaultdict

    groups: dict[str, list[dict]] = defaultdict(list)

    for p in positions:
        key = p.source_fingerprint or p.source_row_hash or f"id:{p.id}"
        groups[key].append({
            "id": p.id,
            "source_sku": p.source_sku,
            "source_name": p.source_name,
            "quantity": str(p.quantity),
            "source_row_number": p.source_row_number,
            "status": p.status.value,
            "validation_errors": p.validation_errors or [],
            "source_fingerprint": p.source_fingerprint,
            "source_row_hash": p.source_row_hash,
        })

    result = []
    for fp, positions_list in groups.items():
        if len(positions_list) > 1:
            result.append(
                DuplicateGroup(
                    source_fingerprint=fp,
                    positions=positions_list,
                )
            )

    return result


@router.get("/{production_plan_id}/batches/{batch_id}/preview")
async def batch_preview(production_plan_id: int, batch_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    from app.models.production_plan import PlanChangeItem

    change_set = (
        await db.execute(
            select(PlanChangeSet).where(
                PlanChangeSet.production_plan_id == production_plan_id,
                PlanChangeSet.import_batch_id == batch_id,
            )
        )
    ).scalar_one_or_none()
    if change_set is None:
        raise HTTPException(status_code=404, detail="Change set for batch not found")

    items = (
        await db.execute(
            select(PlanChangeItem).where(PlanChangeItem.change_set_id == change_set.id).order_by(PlanChangeItem.source_row_number)
        )
    ).scalars().all()
    return {
        "batch_id": batch_id,
        "change_set_id": change_set.id,
        "items": [
            {
                "id": item.id,
                "change_action": item.change_action.value,
                "source_sku": (item.after_data or {}).get("source_sku", ""),
                "source_name": (item.after_data or {}).get("source_name", ""),
                "quantity": (item.after_data or {}).get("quantity", ""),
                "status": item.status.value,
                "errors": item.errors or [],
                "warnings": item.warnings or [],
                "source_payload": (item.after_data or {}).get("source_payload"),
                "after_data": item.after_data,
            }
            for item in items
        ],
    }


@router.post("/reset-all", status_code=status.HTTP_204_NO_CONTENT)
async def reset_all_plans(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Удалить все производственные планы, связанные данные и справочники (маршруты, правила, импорты)."""
    await db.execute(text("""
        TRUNCATE TABLE
            defect_items, defect_decisions, transfer_discrepancy_defect_items,
            defects, rework_tasks, stock_balances, stock_transactions, transfers,
            work_tasks, section_plan_lines, internal_plans,
            release_batch_positions, release_batches,
            plan_change_items, plan_change_sets,
            plan_positions, import_batches, import_files,
            production_plans,
            route_selection_rules, route_rule_profiles, production_routes,
            route_stages, route_operations, route_matching_rules, route_rule_conditions,
            import_templates
        CASCADE
    """))

    # Запись лога аудита (полный сброс системы)
    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction
    await log_action(
        db,
        status="success",
        title="Сброс системы",
        message="Все производственные планы, связанные данные, справочники, маршруты и импорты были полностью удалены (TRUNCATE CASCADE).",
        user=current_user,
        action=AuditAction.DELETE,
    )

    await db.commit()


@router.patch("/{production_plan_id}/positions/{position_id}/quantity")
async def update_position_quantity(
    production_plan_id: int,
    position_id: int,
    payload: UpdatePositionQuantityIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlanPositionOut:
    """Update position quantity and optionally quantity_per_hanger in source_payload."""
    from app.services.plan_validation import validate_plan_position
    from app.models.production_plan import PlanPositionValidationStatus

    position = await db.get(PlanPosition, position_id)
    if position is None or position.production_plan_id != production_plan_id:
        raise HTTPException(status_code=404, detail="Position not found")

    if position.status not in (PlanPositionStatus.draft, PlanPositionStatus.invalid, PlanPositionStatus.valid):
        raise HTTPException(status_code=400, detail="Можно менять только черновики")

    if position.deleted_at is not None:
        raise HTTPException(status_code=400, detail="Позиция удалена")

    old_qty = position.quantity
    position.quantity = payload.quantity

    source_payload = position.source_payload or {}

    # Store original_quantity on first edit
    if "original_quantity" not in source_payload:
        source_payload["original_quantity"] = str(old_qty)

    if payload.quantity_per_hanger is not None:
        source_payload["quantity_per_hanger"] = payload.quantity_per_hanger
    position.source_payload = source_payload

    position.validation_errors = await validate_plan_position(db, position)
    position.validation_status = (
        PlanPositionValidationStatus.valid
        if not position.validation_errors
        else PlanPositionValidationStatus.invalid
    )

    # Запись лога аудита (изменение количества)
    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction, AuditEntityType
    await log_action(
        db,
        status="success",
        title="Изменение количества",
        message=f"Количество в позиции плана #{position_id} (арт. {position.source_sku}) изменено с {old_qty} на {payload.quantity}.",
        user=current_user,
        product_sku=position.source_sku,
        qty_text=f"{old_qty} -> {payload.quantity}",
        action=AuditAction.UPDATE,
        entity_type=AuditEntityType.PLAN_POSITION,
        entity_id=position_id,
        changes={"before": {"quantity": str(old_qty)}, "after": {"quantity": str(payload.quantity)}},
    )

    await db.commit()
    await db.refresh(position)

    route_info = await resolve_position_route(db, position)

    return PlanPositionOut(
        id=position.id,
        production_plan_id=position.production_plan_id,
        source_sku=position.source_sku,
        source_name=position.source_name,
        quantity=str(position.quantity),
        status=position.status.value,
        validation_status=position.validation_status.value,
        errors=[format_validation_error(e) for e in (position.validation_errors or [])],
        warnings=[],
        source_row_number=position.source_row_number,
        source_row_numbers=_source_row_numbers_from_position(position),
        source_ref=position.source_ref,
        product_id=position.product_id,
        route_id=route_info.route_id,
        route_profile_id=position.route_profile_id,
        route_name=route_info.route_name,
        route_source=route_info.source,
        route_origin=route_info.route_origin,
        route_match_quality=route_info.route_match_quality,
        route_match_reason=route_info.route_match_reason,
        route_assigned_at=route_info.route_assigned_at.isoformat() if route_info.route_assigned_at else None,
        route_manual_confirmed_at=(
            route_info.route_manual_confirmed_at.isoformat() if route_info.route_manual_confirmed_at else None
        ),
        route_error=route_info.error,
        raw_excel_row=(position.source_payload or {}).get("raw_excel_row"),
        payload=position.source_payload,
        **_position_operation_fields(position),
    )
