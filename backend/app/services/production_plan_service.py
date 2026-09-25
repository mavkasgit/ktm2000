from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, or_, select, update
from sqlalchemy import func as sa_func
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
    ProductionPlan,
    ProductionPlanStatus,
    require_current_length_model,
)
from app.models.audit_log import AuditAction, AuditEntityType, AuditLog
from app.services.plan_validation import validate_plan_position
from app.services.audit_log_service import log_action
from app.models.user import User


async def require_mutable_plan(db: AsyncSession, production_plan_id: int) -> ProductionPlan:
    """Load a plan and enforce the current normal/raw length model."""
    plan = await db.get(ProductionPlan, production_plan_id)
    if plan is None:
        raise ValueError("Production plan not found")
    require_current_length_model(plan)
    return plan


def _enrich_source_payload(
    source_payload: dict | None,
    after_data: dict,
) -> dict:
    """Copy original_quantity from after_data into source_payload.

    N на подвес в позиции не кэшируется: у одиночных он считается на лету по
    длине позиции, у пары — из снапшота ``product_pair``; в payload живёт
    только ручной override из PATCH (``quantity_per_hanger``). Импортная
    ``after_data.quantity_per_hanger`` (в т.ч. авторасчётная) сюда не
    копируется — иначе авто-норма читалась бы как manual-override.
    """
    payload = dict(source_payload) if source_payload else {}
    if "original_quantity" in after_data:
        payload["original_quantity"] = after_data["original_quantity"]
    return payload


ALLOWED_TRANSITIONS = {
    (PlanPositionStatus.approved, PlanPositionStatus.cancelled),
    (PlanPositionStatus.released, PlanPositionStatus.cancelled),
    (PlanPositionStatus.cancelled, PlanPositionStatus.approved),
    (PlanPositionStatus.cancelled, PlanPositionStatus.released),
}


def restore_item_applicable_status(item: PlanChangeItem) -> None:
    """Вернуть строку сета в состояние парсинга (спека §3): errors → invalid,
    warnings → warning, иначе pending; `mark_possible_duplicate` без ошибок —
    warning. Без этого повторный apply пропускает строки, оставшиеся `applied`.
    """
    from app.services.plan_import_service import plan_import_row_status

    item.status = plan_import_row_status(item.errors or [], item.warnings or [])
    if item.change_action == PlanChangeAction.mark_possible_duplicate and item.status == PlanChangeItemStatus.pending:
        item.status = PlanChangeItemStatus.warning


async def _cancelled_position_for_reapply(
    db: AsyncSession,
    item: PlanChangeItem,
    change_set: PlanChangeSet,
) -> PlanPosition | None:
    """Отменённая позиция этого же сета для повторного применения (#172).

    Уникальные ``(import_batch_id, source_row_number)`` и
    ``(import_batch_id, source_row_hash)`` держит в том числе отменённая строка,
    поэтому повторный apply после отката переиспользует её, а не вставляет
    дубль. Чужая позиция (другой батч) не переиспользуется: тогда поможет
    только явная ошибка уникальности.
    """
    if item.plan_position_id is None:
        return None
    position = await db.get(PlanPosition, item.plan_position_id)
    if position is None:
        return None
    if position.status != PlanPositionStatus.cancelled:
        return None
    if change_set.import_batch_id is not None and position.import_batch_id != change_set.import_batch_id:
        return None
    return position



async def apply_change_set(db: AsyncSession, change_set_id: int, *, skip_invalid: bool = False, changed_by: int | None = None) -> dict:
    change_set = await db.get(PlanChangeSet, change_set_id)
    if change_set is None:
        raise ValueError("Change set not found")
    await require_mutable_plan(db, change_set.production_plan_id)
    if change_set.status == PlanChangeSetStatus.applied:
        return await get_plan_preview(db, change_set.production_plan_id)

    items = (
        await db.execute(select(PlanChangeItem).where(PlanChangeItem.change_set_id == change_set_id).order_by(PlanChangeItem.id))
    ).scalars().all()

    if change_set.status == PlanChangeSetStatus.cancelled:
        # Сеты, откаченные до #172, держат строки в `applied` (прежний откат их
        # не сбрасывал), и первое же условие цикла пропустило бы всё: пересчёт
        # возвращает строки в состояние парсинга, включая правило дублей.
        for item in items:
            restore_item_applicable_status(item)

    # Кэши для устранения N+1 запросов при массовой валидации позиций.
    # Сущности Product/ProductionRoute кэшируются по id на время батча (§4.2).
    route_resolve_cache = {}
    select_route_cache = {}
    route_stages_cache = {}
    sections_cache = {}
    product_cache: dict = {}
    route_cache: dict = {}
    existing_fingerprints = set()
    existing_row_hashes = set()
    # Загружаем существующие fingerprints и row_hashes одним запросом
    existing_pos_data = (
        await db.execute(
            select(PlanPosition.source_fingerprint, PlanPosition.source_row_hash)
            .where(
                PlanPosition.production_plan_id == change_set.production_plan_id,
                PlanPosition.status != PlanPositionStatus.cancelled,
                PlanPosition.deleted_at.is_(None),
            )
        )
    ).all()
    for fp, rh in existing_pos_data:
        if fp:
            existing_fingerprints.add(fp)
        if rh:
            existing_row_hashes.add(rh)
    created = 0
    updated = 0
    ignored = 0
    cancelled = 0
    skipped_invalid = 0
    duplicates = 0
    pending_position_links: list = []
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
            duplicates += 1
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
                    position.input_quantity = _decimal_from_after(after.get("input_quantity"))
                    position.input_dimensions = after.get("input_dimensions")
                    position.outputs = after.get("outputs") or []
                    position.source_payload = after.get("source_payload") or {}
                    position.source_ref = after.get("source_ref")
                    position.source_fingerprint = after.get("source_fingerprint")
                    position.source_row_hash = after.get("source_row_hash")
                    position.import_batch_id = change_set.import_batch_id
                    position.source_row_number = (after.get("source_row_numbers") or [item.source_row_number])[0]
                    position.period_start = _date_from_payload(after, "period_start")
                    position.period_end = _date_from_payload(after, "period_end")
                    position.has_pack_ops = _bool_or_none(after.get("has_pack_ops"))
                    position.route_id = after.get("route_id")
                    position.route_profile_id = after.get("route_profile_id")
                    position.route_origin = _route_origin_from_after(after)
                    position.route_match_quality = _route_match_quality_from_after(after)
                    position.route_match_reason = _route_match_reason_from_after(after)
                    position.route_assigned_at = _datetime_from_after(after, "route_assigned_at")
                    position.route_manual_confirmed_at = _datetime_from_after(after, "route_manual_confirmed_at")

                    validation_errors = await validate_plan_position(
                        db, position,
                        route_resolve_cache=route_resolve_cache,
                        select_route_cache=select_route_cache,
                        route_stages_cache=route_stages_cache,
                        sections_cache=sections_cache,
                        existing_fingerprints=existing_fingerprints,
                        existing_row_hashes=existing_row_hashes,
                        product_cache=product_cache,
                        route_cache=route_cache,
                    )

                    position.validation_errors = validation_errors
                    position.validation_status = (
                        PlanPositionValidationStatus.invalid if validation_errors else PlanPositionValidationStatus.valid
                    )
                    position.status = PlanPositionStatus.invalid if validation_errors else PlanPositionStatus.draft
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

            position_fields = {
                "production_plan_id": change_set.production_plan_id,
                "product_id": after.get("product_id"),
                "route_id": after.get("route_id"),
                "route_profile_id": after.get("route_profile_id"),
                "source_type": PlanSourceType.excel_import,
                "source_system": "excel",
                "source_ref": after.get("source_ref"),
                "source_fingerprint": after.get("source_fingerprint"),
                "source_row_hash": after.get("source_row_hash"),
                "import_batch_id": change_set.import_batch_id,
                "source_sku": after["source_sku"],
                "source_name": after.get("source_name"),
                "quantity": qty_decimal,
                "input_quantity": _decimal_from_after(after.get("input_quantity")),
                "input_dimensions": after.get("input_dimensions"),
                "outputs": after.get("outputs") or [],
                "source_payload": _enrich_source_payload(after.get("source_payload"), after),
                "period_start": _date_from_payload(after, "period_start"),
                "period_end": _date_from_payload(after, "period_end"),
                "source_row_number": (after.get("source_row_numbers") or [item.source_row_number])[0],
                "has_pack_ops": _bool_or_none(after.get("has_pack_ops")),
                "route_origin": _route_origin_from_after(after),
                "route_match_quality": _route_match_quality_from_after(after),
                "route_match_reason": _route_match_reason_from_after(after),
                "route_assigned_at": _datetime_from_after(after, "route_assigned_at"),
                "route_manual_confirmed_at": _datetime_from_after(after, "route_manual_confirmed_at"),
                "status": PlanPositionStatus.invalid if validation_errors else PlanPositionStatus.draft,
                "validation_status": PlanPositionValidationStatus.invalid if validation_errors else PlanPositionValidationStatus.valid,
                "validation_errors": validation_errors,
            }
            # Повторный apply откаченного сета (#172): своя отменённая строка
            # переиспользуется, а не вставляется второй раз — пара
            # (import_batch_id, source_row_number) уникальна, и отменённая
            # позиция продолжает её занимать.
            position = await _cancelled_position_for_reapply(db, item, change_set)
            if position is None:
                position = PlanPosition(**position_fields)
                db.add(position)
                pending_position_links.append((item, position))
            else:
                for field, value in position_fields.items():
                    setattr(position, field, value)
                # Позиция возвращается в план как новая строка импорта:
                # снимаем следы отмены/скрытия и прежнего утверждения.
                position.approved_by = None
                position.approved_at = None
                position.released_at = None
                position.deleted_at = None
                position.deleted_by = None
                position.delete_reason = None
            item.status = PlanChangeItemStatus.applied
            created += 1
            continue

    # Один flush на весь батч (§4.2): все INSERT/UPDATE выше копятся в сессии.
    # Связки item → новая позиция разрешаются после flush по выданным PK;
    # их UPDATE увозят flush внутри log_action ниже и финальный commit.
    await db.flush()
    for linked_item, linked_position in pending_position_links:
        linked_item.plan_position_id = linked_position.id
    change_set.status = PlanChangeSetStatus.applied
    change_set.applied_at = datetime.now(timezone.utc)
    if change_set.import_batch_id:
        from app.models.imports import ImportBatch

        batch = await db.get(ImportBatch, change_set.import_batch_id)
        if batch is not None:
            batch.status = ImportBatchStatus.applied

    # Запись лога аудита (применение импорта)
    user = await db.get(User, changed_by) if changed_by else None
    await log_action(
        db,
        status="success",
        title="Импорт плана (применен)",
        message=f"Пакет изменений импорта #{change_set_id} успешно применен. Создано: {created}, обновлено: {updated}, отменено черновиков: {cancelled}, пропущено: {ignored}, пропущено невалидных: {skipped_invalid}, дублей: {duplicates}.",
        user=user,
        action=AuditAction.IMPORT,
        entity_type=AuditEntityType.IMPORT_BATCH,
        entity_id=change_set.import_batch_id,
        changes={"created": created, "updated": updated, "cancelled": cancelled, "ignored": ignored, "skipped_invalid": skipped_invalid, "duplicates": duplicates},
    )

    extra = {
        "created_positions": created,
        "updated_positions": updated,
        "ignored_positions": ignored,
        "cancelled_positions": cancelled,
        "skipped_invalid_positions": skipped_invalid,
        # `duplicates` — буква спеки §4.2; `duplicates_positions` — алиас под конвенцию *_positions.
        "duplicates": duplicates,
        "duplicates_positions": duplicates,
    }
    return await get_plan_preview(db, change_set.production_plan_id, extra=extra)


async def rollback_change_set(db: AsyncSession, change_set_id: int, changed_by: int | None = None) -> dict:
    change_set = await db.get(PlanChangeSet, change_set_id)
    if change_set is None:
        raise ValueError("Change set not found")
    await require_mutable_plan(db, change_set.production_plan_id)
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
                position.has_pack_ops = _bool_or_none(item.before_data.get("has_pack_ops"))
                position.status = PlanPositionStatus.draft
        elif item.change_action == PlanChangeAction.cancel_draft_position and item.plan_position_id:
            position = await db.get(PlanPosition, item.plan_position_id)
            if position:
                position.status = PlanPositionStatus.draft

        restore_item_applicable_status(item)

    change_set.status = PlanChangeSetStatus.cancelled
    change_set.applied_at = None
    if change_set.import_batch_id:
        from app.models.imports import ImportBatch

        batch = await db.get(ImportBatch, change_set.import_batch_id)
        if batch:
            batch.status = ImportBatchStatus.cancelled

    # Запись лога аудита (откат импорта)
    user = await db.get(User, changed_by) if changed_by else None
    await log_action(
        db,
        status="success",
        title="Импорт плана (откат)",
        message=f"Выполнен откат пакета изменений импорта #{change_set_id}.",
        user=user,
        action=AuditAction.CANCEL,
        entity_type=AuditEntityType.IMPORT_BATCH,
        entity_id=change_set.import_batch_id,
    )

    await db.flush()
    return await get_plan_preview(db, change_set.production_plan_id)


async def _delete_batch_and_orphan_file(db: AsyncSession, batch_id: int) -> bool:
#: Удалить батч импорта и файл-источник, если на него больше никто не ссылается.
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


#: Удаление батча импорта (спека docs/plan-import-spec.md §4.4, тикет #167):
#: при живых downstream-данных полное удаление запрещено — 409 с blockers.
BATCH_DELETE_SAFE_ACTION = "delete_drafts_only"
BATCH_DELETE_BLOCK_RELEASED = "batch_has_released_positions"
BATCH_DELETE_BLOCK_TRANSFERS = "downstream_transfers_exist"


class BatchDeleteBlocked(Exception):
#: Полное удаление батча заблокировано живыми данными. Маршрут маппит в 409
#: {code, blockers, safe_action, drafts}; «Удалить всё» при блокерах запрещён.
    def __init__(self, code: str, blockers: list[dict], drafts: int) -> None:
        super().__init__(code)
        self.code = code
        self.blockers = blockers
        self.drafts = drafts


async def _safely_deletable_position_ids(db: AsyncSession, batch_id: int) -> set[int]:
#: Единственный источник правды «что safe-режим реально удалит»: позиции батча
#: с ТЕКУЩИМ статусом draft и без SectionPlanLine (линия = попадание в
#: производство, живой downstream). Используется и для drafts в 409, и для
#: deletable_ids в delete_import_batch — число на кнопке равно deleted_drafts.
    from app.models.internal_plan import SectionPlanLine

    draft_rows = (
        await db.execute(
            select(PlanPosition.id).where(
                PlanPosition.import_batch_id == batch_id,
                PlanPosition.status == PlanPositionStatus.draft,
            )
        )
    ).scalars().all()
    if not draft_rows:
        return set()
    ids_with_lines = set(
        (
            await db.execute(
                select(SectionPlanLine.plan_position_id).where(
                    SectionPlanLine.plan_position_id.in_(list(draft_rows))
                )
            )
        ).scalars().all()
    )
    return set(draft_rows) - ids_with_lines


async def get_batch_delete_blockers(db: AsyncSession, batch_id: int) -> dict:
#: Блокеры удаления батча: released-позиции и позиции с передачами вниз по
#: цепочке (линии → задачи → передачи). drafts — число безопасно-удаляемых
#: черновиков (см. _safely_deletable_position_ids) для кнопки
#: «Удалить только черновики (n)».
    from app.models.internal_plan import SectionPlanLine
    from app.models.transfer import Transfer
    from app.models.work_task import WorkTask

    positions = (
        await db.execute(
            select(PlanPosition.id, PlanPosition.status).where(PlanPosition.import_batch_id == batch_id)
        )
    ).all()
    pos_status = {position_id: st for position_id, st in positions}
    blockers = [
        {"position_id": position_id, "reason": "released"}
        for position_id, st in sorted(pos_status.items())
        if st == PlanPositionStatus.released
    ]
    position_ids = list(pos_status)
    if position_ids:
        line_rows = (
            await db.execute(
                select(SectionPlanLine.id, SectionPlanLine.plan_position_id).where(
                    SectionPlanLine.plan_position_id.in_(position_ids)
                )
            )
        ).all()
        line_pos = {line_id: pid for line_id, pid in line_rows}
        task_to_pos: dict[int, int] = {}
        transfer_rows = []
        if line_pos:
            task_rows = (
                await db.execute(
                    select(WorkTask.id, WorkTask.section_plan_line_id).where(
                        WorkTask.section_plan_line_id.in_(list(line_pos))
                    )
                )
            ).all()
            task_to_pos = {task_id: line_pos[line_id] for task_id, line_id in task_rows}
            if task_to_pos:
                transfer_rows = (
                    await db.execute(
                        select(
                            Transfer.transfer_no, Transfer.from_task_id, Transfer.to_task_id
                        )
                        .where(
                            or_(
                                Transfer.from_task_id.in_(list(task_to_pos)),
                                Transfer.to_task_id.in_(list(task_to_pos)),
                            )
                        )
                        .order_by(Transfer.id)
                    )
                ).all()
        seen: set[tuple[int, str]] = set()
        for transfer_no, from_task_id, to_task_id in transfer_rows:
            for task_id in (from_task_id, to_task_id):
                pid = task_to_pos.get(task_id)
                if pid is not None and (pid, transfer_no) not in seen:
                    seen.add((pid, transfer_no))
                    blockers.append({"position_id": pid, "reason": f"transfer №{transfer_no}"})
    blockers.sort(key=lambda b: (b["position_id"], b["reason"]))
    has_released = any(b["reason"] == "released" for b in blockers)
    code = (
        BATCH_DELETE_BLOCK_RELEASED
        if has_released
        else BATCH_DELETE_BLOCK_TRANSFERS if blockers else None
    )
    drafts = len(await _safely_deletable_position_ids(db, batch_id))
    return {"code": code, "blockers": blockers, "safe_action": BATCH_DELETE_SAFE_ACTION, "drafts": drafts}


async def _delete_change_set_records(db: AsyncSession, change_set_id: int) -> None:
#: Удалить записи чендж-сета (items + set) без отката — для черновиков и
#: уже откаченных сетов.
    await db.execute(delete(PlanChangeItem).where(PlanChangeItem.change_set_id == change_set_id))
    change_set = await db.get(PlanChangeSet, change_set_id)
    if change_set is not None:
        await db.delete(change_set)


async def _cascade_delete_positions(db: AsyncSession, position_ids: list[int]) -> None:
#: Каскад позиций батча: задачи/передачи (только своих позиций), линии,
#: позиции релиз-батчей, сами позиции. Вызывать только для позиций без живых
#: данных вне удаляемого множества (проверено вызывающим через blockers).
    from app.models.defect import TransferDiscrepancyDefectItem
    from app.models.internal_plan import SectionPlanLine
    from app.models.production_plan import PositionStatusHistory
    from app.models.release_batch import ReleaseBatchPosition
    from app.models.transfer import Transfer, TransferDiscrepancy
    from app.models.work_task import WorkTask

    if not position_ids:
        return
    section_plan_lines = (
        await db.execute(
            select(SectionPlanLine.id).where(SectionPlanLine.plan_position_id.in_(position_ids))
        )
    ).scalars().all()
    if section_plan_lines:
        task_ids = (
            await db.execute(
                select(WorkTask.id).where(WorkTask.section_plan_line_id.in_(section_plan_lines))
            )
        ).scalars().all()
        if task_ids:
            discrepancy_ids = (
                await db.execute(
                    select(TransferDiscrepancy.id).where(
                        or_(
                            TransferDiscrepancy.transfer_id.in_(
                                select(Transfer.id).where(
                                    or_(
                                        Transfer.from_task_id.in_(task_ids),
                                        Transfer.to_task_id.in_(task_ids),
                                    )
                                )
                            ),
                        )
                    )
                )
            ).scalars().all() or []
            if discrepancy_ids:
                await db.execute(
                    delete(TransferDiscrepancyDefectItem).where(
                        TransferDiscrepancyDefectItem.transfer_discrepancy_id.in_(discrepancy_ids)
                    )
                )
                await db.execute(
                    delete(TransferDiscrepancy).where(TransferDiscrepancy.id.in_(discrepancy_ids))
                )
            await db.execute(
                delete(Transfer).where(
                    or_(Transfer.from_task_id.in_(task_ids), Transfer.to_task_id.in_(task_ids))
                )
            )
            await db.execute(delete(WorkTask).where(WorkTask.section_plan_line_id.in_(section_plan_lines)))
        await db.execute(delete(SectionPlanLine).where(SectionPlanLine.plan_position_id.in_(position_ids)))
    await db.execute(delete(ReleaseBatchPosition).where(ReleaseBatchPosition.plan_position_id.in_(position_ids)))
#: FK position_status_history.plan_position_id — без ondelete (миграция 005): чистим
#: историю до удаления позиций, иначе будущие писатели истории сломают удаление.
    await db.execute(
        delete(PositionStatusHistory).where(PositionStatusHistory.plan_position_id.in_(position_ids))
    )
    await db.execute(delete(PlanPosition).where(PlanPosition.id.in_(position_ids)))


async def delete_import_batch(
    db: AsyncSession, batch_id: int, *, delete_drafts_only: bool = False, changed_by: int | None = None
) -> dict:
    from app.models.imports import ImportBatch
    batch = await db.get(ImportBatch, batch_id)
    if batch is None:
        raise ValueError("Import batch not found")
    await require_mutable_plan(db, batch.production_plan_id)

    info = await get_batch_delete_blockers(db, batch_id)
    user = await db.get(User, changed_by) if changed_by else None
    if info["code"] is not None and not delete_drafts_only:
        raise BatchDeleteBlocked(info["code"], info["blockers"], info["drafts"])
#: Явный safe-флаг НЕ сводим к полному удалению даже без блокеров: у батча без
#: released/передач могут быть approved/valid-позиции, и safe обязан их сохранить.
#: Полное удаление — только явный DELETE без флага.
    if not delete_drafts_only:
        change_sets = (
            await db.execute(select(PlanChangeSet).where(PlanChangeSet.import_batch_id == batch_id))
        ).scalars().all()
        for cs in change_sets:
            if cs.status == PlanChangeSetStatus.applied:
                await rollback_change_set(db, cs.id, changed_by=changed_by)
            await _delete_change_set_records(db, cs.id)
        position_ids = (
            await db.execute(select(PlanPosition.id).where(PlanPosition.import_batch_id == batch_id))
        ).scalars().all()
        await _cascade_delete_positions(db, list(position_ids))
        await _delete_batch_and_orphan_file(db, batch_id)
        await log_action(
            db,
            status="success",
            title="Удаление пакета импорта",
            message=f"Пакет импорта плана #{batch_id} успешно удален со всеми связанными позициями, задачами и движениями.",
            user=user,
            action=AuditAction.DELETE,
            entity_type=AuditEntityType.IMPORT_BATCH,
            entity_id=batch_id,
        )
        await db.commit()
        return {"deleted": True, "batch_id": batch_id}
#: Множество безопасно-удаляемых позиций — тот же источник, что дал drafts в
#: 409: кнопка «Удалить только черновики (n)» обещает ровно это множество.
    deletable_ids = await _safely_deletable_position_ids(db, batch_id)
    kept_set_ids: set[int] = set()
    change_sets = (
        await db.execute(select(PlanChangeSet).where(PlanChangeSet.import_batch_id == batch_id))
    ).scalars().all()
    for cs in change_sets:
        if cs.status == PlanChangeSetStatus.applied:
            touched_ids = set(
                (
                    await db.execute(
                        select(PlanChangeItem.plan_position_id).where(
                            PlanChangeItem.change_set_id == cs.id,
                            PlanChangeItem.plan_position_id.is_not(None),
                        )
                    )
                ).scalars().all()
            )
#: Сет откатывается и удаляется, только если ВСЕ затронутые им позиции
#: безопасно-удаляемы (draft без линии). Иначе сет неприкосновенен: откат
#: create_position перевёл бы approved/valid в cancelled, а удаление снесло бы
#: живые данные под кнопкой «только черновики». Часть его items всё же может
#: указывать на удаляемые черновики — их отвяжем ниже.
            if not touched_ids <= deletable_ids:
                kept_set_ids.add(cs.id)
                continue
            await rollback_change_set(db, cs.id, changed_by=changed_by)
        await _delete_change_set_records(db, cs.id)
    if kept_set_ids and deletable_ids:
#: Пропущенный applied-сет остаётся (откат невозможен из-за блокеров), но его
#: items отвязываются от сносимых черновиков: after_data хранит историю,
#: FK на удаляемые позиции быть не должно. Откат такого сета и так невозможен
#: (rollback_change_set падает на released), история не теряет смысла.

        await db.execute(
            update(PlanChangeItem)
            .where(
                PlanChangeItem.change_set_id.in_(list(kept_set_ids)),
                PlanChangeItem.plan_position_id.in_(sorted(deletable_ids)),
            )
            .values(plan_position_id=None)
        )
    await _cascade_delete_positions(db, sorted(deletable_ids))
    remaining_sets = (
        await db.execute(
            select(PlanChangeSet.id).where(PlanChangeSet.import_batch_id == batch_id)
        )
    ).scalars().all()
    remaining_positions = (
        await db.execute(select(PlanPosition.id).where(PlanPosition.import_batch_id == batch_id))
    ).scalars().all()
    deleted_batch = False
    if not remaining_sets and not remaining_positions:
        await _delete_batch_and_orphan_file(db, batch_id)
        deleted_batch = True
    await log_action(
        db,
        status="success",
        title="Удаление черновиков пакета импорта",
        message=(
            f"Из пакета импорта плана #{batch_id} удалено черновиков: {len(deletable_ids)}. "
            f"Released-позиции, задачи и передачи не тронуты."
        ),
        user=user,
        action=AuditAction.DELETE,
        entity_type=AuditEntityType.IMPORT_BATCH,
        entity_id=batch_id,
    )
    await db.commit()
    return {
        "deleted": deleted_batch,
        "batch_id": batch_id,
        "mode": BATCH_DELETE_SAFE_ACTION,
        "deleted_drafts": len(deletable_ids),
        "blockers": info["blockers"],
    }


async def approve_plan_position(
    db: AsyncSession,
    production_plan_id: int,
    position_id: int,
    force: bool = False,
    changed_by: int | None = None,
) -> PlanPosition:
    position = (
        await db.execute(
            select(PlanPosition)
            .where(PlanPosition.id == position_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if position is None or position.production_plan_id != production_plan_id:
        raise ValueError("Plan position not found")
    await require_mutable_plan(db, production_plan_id)
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
    plan = await db.get(ProductionPlan, production_plan_id)
    if plan is not None and plan.status in {ProductionPlanStatus.draft, ProductionPlanStatus.validated}:
        plan.status = ProductionPlanStatus.approved
    
    # Запись лога аудита
    user = await db.get(User, changed_by) if changed_by else None
    await log_action(
        db,
        status="success",
        title="Утверждение позиции",
        message=f"Позиция плана #{position_id} (арт. {position.source_sku}) успешно утверждена.",
        user=user,
        product_sku=position.source_sku,
        qty_text=str(position.quantity),
        action=AuditAction.APPROVE,
        entity_type=AuditEntityType.PLAN_POSITION,
        entity_id=position_id,
        changes={"before": {"status": from_status}, "after": {"status": PlanPositionStatus.approved.value}},
    )

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
    await require_mutable_plan(db, production_plan_id)
    if position.status not in {PlanPositionStatus.approved, PlanPositionStatus.released}:
        raise ValueError(f"Нельзя отменить позицию со статусом '{position.status.value}'")

    from_status = position.status.value
    position.status = PlanPositionStatus.cancelled
    await _refresh_plan_status(db, production_plan_id)

    # Запись лога аудита
    user = await db.get(User, changed_by) if changed_by else None
    await log_action(
        db,
        status="success",
        title="Отмена позиции",
        message=f"Позиция плана #{position_id} (арт. {position.source_sku}) отменена. Причина: {reason or '—'}",
        user=user,
        product_sku=position.source_sku,
        comment=reason,
        action=AuditAction.CANCEL,
        entity_type=AuditEntityType.PLAN_POSITION,
        entity_id=position_id,
        changes={"before": {"status": from_status}, "after": {"status": PlanPositionStatus.cancelled.value, "reason": reason}},
    )

    await db.flush()
    return position


async def refresh_plan_status(db: AsyncSession, production_plan_id: int) -> None:
    """Recompute the production plan status from its active positions.

    This is the single source of truth for plan status derivation. Use it
    after any operation that mutates PlanPosition.status (approve, release,
    cancel, restore, delete) to keep the plan in sync.

    Transition rules (active = approved | released):

    - no active positions, all positions are draft  -> ``draft``
    - no active positions, no draft positions         -> ``validated``
    - all active positions are released               -> ``released``
    - some active positions are released              -> ``partially_released``
    - no released positions, only approved           -> ``approved``
    - empty plan                                     -> ``draft``
    """
    plan = await db.get(ProductionPlan, production_plan_id)
    if plan is None:
        return

    positions = (
        await db.execute(
            select(PlanPosition).where(
                PlanPosition.production_plan_id == production_plan_id,
                PlanPosition.deleted_at.is_(None),
            )
        )
    ).scalars().all()

    if not positions:
        plan.status = ProductionPlanStatus.draft
        return

    status_counts = Counter(pos.status for pos in positions)
    released_count = status_counts.get(PlanPositionStatus.released, 0)
    approved_count = status_counts.get(PlanPositionStatus.approved, 0)

    active_count = approved_count + released_count

    if active_count == 0:
        if status_counts.get(PlanPositionStatus.draft, 0) > 0:
            plan.status = ProductionPlanStatus.draft
        else:
            plan.status = ProductionPlanStatus.validated
    elif released_count == 0:
        plan.status = ProductionPlanStatus.approved
    elif released_count == active_count:
        plan.status = ProductionPlanStatus.released
    else:
        plan.status = ProductionPlanStatus.partially_released


async def _refresh_plan_status(db: AsyncSession, production_plan_id: int) -> None:
    """Deprecated private alias; use :func:`refresh_plan_status`."""
    await refresh_plan_status(db, production_plan_id)


async def restore_plan_position(
    db: AsyncSession,
    production_plan_id: int,
    position_id: int,
    changed_by: int | None = None,
    reason: str | None = None,
) -> PlanPosition:
    """Restore a cancelled plan position."""
    position = await db.get(PlanPosition, position_id)
    if position is None or position.production_plan_id != production_plan_id:
        raise ValueError("Plan position not found")
    await require_mutable_plan(db, production_plan_id)
    if position.status != PlanPositionStatus.cancelled:
        raise ValueError(f"Нельзя восстановить позицию со статусом '{position.status.value}'")

    # Find the last cancellation record in audit_logs
    last_cancel = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.entity_type == AuditEntityType.PLAN_POSITION.value,
                AuditLog.entity_id == position_id,
                AuditLog.action == AuditAction.CANCEL.value,
            )
            .order_by(AuditLog.created_at.desc())
        )
    ).scalars().first()

    if last_cancel is None or last_cancel.changes is None or "before" not in last_cancel.changes:
        raise ValueError("Нет истории отмены в логах аудита — восстановление невозможно")

    target_status_value = last_cancel.changes["before"].get("status")
    if target_status_value not in {PlanPositionStatus.approved.value, PlanPositionStatus.released.value}:
        raise ValueError(f"Недопустимый статус для восстановления: '{target_status_value}'")

    target_status = PlanPositionStatus(target_status_value)
    position.status = target_status
    await _refresh_plan_status(db, production_plan_id)

    # Запись лога аудита
    user = await db.get(User, changed_by) if changed_by else None
    await log_action(
        db,
        status="success",
        title="Восстановление позиции",
        message=f"Позиция плана #{position_id} (арт. {position.source_sku}) восстановлена до статуса '{target_status_value}'.",
        user=user,
        product_sku=position.source_sku,
        action=AuditAction.RESTORE,
        entity_type=AuditEntityType.PLAN_POSITION,
        entity_id=position_id,
        changes={"before": {"status": PlanPositionStatus.cancelled.value}, "after": {"status": target_status_value}},
    )

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
    await require_mutable_plan(db, production_plan_id)
    if position.status != PlanPositionStatus.cancelled:
        raise ValueError(f"Можно скрыть только отменённую позицию (текущий статус: '{position.status.value}')")

    position.deleted_at = datetime.now(timezone.utc)
    position.deleted_by = changed_by
    position.delete_reason = reason

    # Запись лога аудита
    user = await db.get(User, changed_by) if changed_by else None
    await log_action(
        db,
        status="success",
        title="Удаление позиции (скрытие)",
        message=f"Позиция плана #{position_id} (арт. {position.source_sku}) скрыта из плана. Причина: {reason or 'Удалена из списка'}",
        user=user,
        product_sku=position.source_sku,
        comment=reason,
        action=AuditAction.DELETE,
        entity_type=AuditEntityType.PLAN_POSITION,
        entity_id=position_id,
        changes={"before": {"status": PlanPositionStatus.cancelled.value}, "after": {"status": "deleted", "reason": reason}},
    )

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
        "length_model_version": plan.length_model_version,
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


def _bool_or_none(value):
    if value is None:
        return None
    return bool(value)


def _decimal_from_after(value):
    if value is None or value == "":
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


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
