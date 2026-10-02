from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import (
    READER_ROLES,
    TRANSFER_WRITER_ROLES,
    WRITER_ROLES,
    _ensure_section_lock,
    _ensure_task_lock,
    get_current_user,
    get_single_window_locked_section_id,
    require_role,
)
from app.core.database import get_db

# Единый словарь стратегий недостачи (#134) — канон в домене, route-enum
# удалён; FastAPI декодирует wire-строку прямо в ShortageStrategy.
from app.domain.shortage import DEFAULT_SHORTAGE_STRATEGY, ShortageStrategy
from app.models.defect import DefectDecisionType
from app.models.entity_comment import EntityType
from app.models.route import SectionOperation
from app.models.user import User
from app.models.work_task import WorkTask
from app.seeds.canon.dependencies import get_plant_config
from app.seeds.canon.models import PlantConfig
from app.services.action_journal_service import action_journal_service
from app.services.audit_log_service import log_action
from app.services.shopfloor.common import _get_user_snapshot_name, _require_mutable_task
from app.services.shopfloor_service import (
    BOARD_COLUMN_VALUE_FIELDS,
    add_defect_item,
    complete_task,
    create_attachment,
    create_comment,
    create_defect,
    defect_decide,
    final_release,
    get_defect_details,
    get_rework_details,
    get_route_stage_aggregates_for_plan_position,
    get_section_board,
    get_section_board_column_values,
    get_section_daily_stats,
    get_sections_summary,
    get_task_details,
    link_attachment,
    list_entity_attachments,
    list_entity_comments,
    prepare_section_task,
    rework_create,
)
from app.transfers.queries import get_section_incoming_transfers, get_transfer_details
from app.transfers.schemas import CreateTransferPayload
from app.transfers.services import transfer_send

router = APIRouter(prefix="/shopfloor", tags=["sections-operations"])


def _naive_as_utc(value: datetime) -> datetime:
    """Трактует наивную метку клиента как UTC, не трогая aware.

    Ось дат продукта — UTC (прод-контейнеры живут в ``TZ=UTC``,
    docs/deployment.md), поэтому наивный вход без зоны (так его шлёт
    фронт, ``YYYY-MM-DDTHH:MM:SS``) читается как UTC, а не как
    host-local время процесса. Значение со своей зоной уже несёт шкалу —
    не переводим, чтобы не сдвинуть его дважды.
    """
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class PatchOperationPayload(BaseModel):
    operation_code: str


class CompletePayload(BaseModel):
    good_quantity: Decimal = Decimal(0)
    defect_quantity: Decimal = Decimal(0)
    defect_reason: str | None = None
    comment: str | None = None
    idempotency_key: str | None = None
    executor_user_id: int | None = None
    performed_at: datetime | None = None
    accounted_at: datetime | None = None
    # Дефолт fail (#133): оператор, нажавший «Завершить» не глядя, получает
    # внятную ошибку с доступным количеством, а не тихий уход участка в минус.
    shortage_strategy: ShortageStrategy = DEFAULT_SHORTAGE_STRATEGY
    auto_transfer_next: bool = False


class FinalReleasePayload(BaseModel):
    quantity: Decimal
    comment: str | None = None
    idempotency_key: str | None = None
    executor_user_id: int | None = None
    performed_at: datetime | None = None
    accounted_at: datetime | None = None
    # Габарит выпуска (ADR-0001): на трансформирующем финальном этапе —
    # один из выходных размеров задания. На обычном — опционален.
    dimensions: dict | None = None


class PrepareTaskPayload(BaseModel):
    plan_position_id: int
    section_id: int
    quantity: Decimal
    idempotency_key: str | None = None


class ReturnRemainderPayload(BaseModel):
    task_id: int
    quantity: Decimal
    comment: str | None = None
    idempotency_key: str | None = None
    executor_user_id: int | None = None
    performed_at: datetime | None = None
    accounted_at: datetime | None = None


class ConsumeRemainderPayload(BaseModel):
    remainder_id: int
    task_id: int
    quantity: Decimal
    comment: str | None = None
    idempotency_key: str | None = None
    executor_user_id: int | None = None
    performed_at: datetime | None = None
    accounted_at: datetime | None = None


class CreateDefectPayload(BaseModel):
    task_id: int | None = None
    product_id: int | None = None
    section_id: int | None = None
    route_stage_id: int | None = None
    quantity: Decimal
    reason: str | None = None
    comment: str | None = None
    idempotency_key: str | None = None


class DefectTypeOut(BaseModel):
    id: int
    code: str
    name: str
    category: str | None = None
    severity: int
    requires_quality_decision: bool
    description: str | None = None

    model_config = {"from_attributes": True}


class AddDefectItemPayload(BaseModel):
    quantity: Decimal
    defect_type_id: int | None = None
    subtype_code: str | None = None
    reason_code: str | None = None
    description: str | None = None


class DefectDecisionPayload(BaseModel):
    decision_type: DefectDecisionType
    quantity: Decimal
    target_section_id: int | None = None
    reason: str | None = None
    comment: str | None = None
    idempotency_key: str | None = None


class ReworkCreatePayload(BaseModel):
    defect_id: int
    source_task_id: int
    section_id: int
    quantity: Decimal
    idempotency_key: str | None = None


class CommentPayload(BaseModel):
    entity_type: EntityType
    entity_id: int
    body: str
    comment_type: str = "note"
    is_internal: bool = False
    idempotency_key: str | None = None


class CreateAttachmentPayload(BaseModel):
    original_filename: str
    stored_path: str
    size_bytes: int
    content_type: str | None = None
    file_sha256: str | None = None
    metadata_json: dict | None = None
    idempotency_key: str | None = None


class LinkAttachmentPayload(BaseModel):
    entity_type: EntityType
    entity_id: int
    caption: str | None = None


@router.post("/tasks/{task_id}/complete", dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def complete_task_endpoint(
    task_id: int,
    payload: CompletePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
    plant_config: PlantConfig = Depends(get_plant_config),
) -> dict:
    await _ensure_task_lock(db, task_id, locked_section_id)
    try:
        res = await complete_task(
            db,
            task_id=task_id,
            good_quantity=payload.good_quantity,
            defect_quantity=payload.defect_quantity,
            actor_id=current_user.id,
            defect_reason=payload.defect_reason,
            comment=payload.comment,
            idempotency_key=payload.idempotency_key,
            executor_user_id=payload.executor_user_id,
            performed_at=payload.performed_at,
            accounted_at=payload.accounted_at,
            shortage_strategy=payload.shortage_strategy,
            auto_transfer_next=payload.auto_transfer_next,
            scrap_policy=plant_config.production.scrap_policy,
        )

        # Запись лога аудита
        task = await db.get(WorkTask, task_id)
        if task:
            from app.models.product import Product
            from app.models.route import RouteStage
            from app.models.section import Section
            section = await db.get(Section, task.section_id)
            product = await db.get(Product, task.product_id)
            route_stage = await db.get(RouteStage, task.route_stage_id)
            op_name = ", ".join(op.operation_name for op in route_stage.operations) if (route_stage and route_stage.operations) else "Операция"
            
            section_info = f"на участке \"{section.name}\" ({section.code})" if section else ""
            task_info = f"для операции \"{op_name}\" (арт. {product.sku})" if product else ""
            message = f"Успешно подтверждено выполнение {task_info} {section_info}. Введено: годные = {payload.good_quantity} шт., брак = {payload.defect_quantity} шт."
            if payload.comment:
                message += f" (комментарий: \"{payload.comment}\")"
            
            from app.models.audit_log import AuditAction, AuditEntityType
            await log_action(
                db,
                status="success",
                title="Факт подтвержден",
                message=message,
                user=current_user,
                section_id=task.section_id,
                section_name=section.name if section else None,
                section_code=section.code if section else None,
                task_ids=[task_id],
                product_sku=product.sku if product else None,
                operation_name=op_name,
                qty_text=f"годн: {payload.good_quantity}, брак: {payload.defect_quantity}",
                comment=payload.comment,
                action=AuditAction.UPDATE,
                entity_type=AuditEntityType.WORK_TASK,
                entity_id=task_id,
                changes={
                    "before": {"status": "in_progress"},
                    "after": {
                        "status": "completed" if task.status == "completed" else task.status,
                        "good_quantity": str(payload.good_quantity),
                        "defect_quantity": str(payload.defect_quantity),
                    }
                },
            )

        return res
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- Bulk action endpoints (savepoint-isolated) -----------------------------


class BulkCompleteEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: int
    good_quantity: Decimal = Decimal(0)
    defect_quantity: Decimal = Decimal(0)
    defect_reason: str | None = None
    comment: str | None = None
    idempotency_key: str | None = None
    executor_user_id: int | None = None
    performed_at: datetime | None = None
    accounted_at: datetime | None = None
    # Дефолт fail (#133) — как в одиночном CompletePayload.
    shortage_strategy: ShortageStrategy = DEFAULT_SHORTAGE_STRATEGY
    auto_transfer_next: bool = False


class BulkActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[dict]


class BulkActionResultItem(BaseModel):
    id: int
    status: Literal["success", "failed", "skipped"]
    reason: str | None = None
    meta: dict | None = None


class BulkActionResponse(BaseModel):
    results: list[BulkActionResultItem]


@router.post(
    "/tasks/bulk-complete",
    response_model=BulkActionResponse,
    dependencies=[Depends(require_role(list(WRITER_ROLES)))],
)
async def bulk_complete_tasks(
    payload: BulkActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
    plant_config: PlantConfig = Depends(get_plant_config),
) -> BulkActionResponse:
    """Complete many tasks in a single request with savepoint isolation per item."""
    import logging
    logger = logging.getLogger(__name__)

    results: list[BulkActionResultItem] = []
    for raw in payload.entries:
        try:
            entry = BulkCompleteEntry.model_validate(raw)
        except ValidationError as exc:
            results.append(
                BulkActionResultItem(id=0, status="failed", reason=f"Invalid entry: {exc}")
            )
            continue
        try:
            async with db.begin_nested():
                await _ensure_task_lock(db, entry.task_id, locked_section_id)
                await complete_task(
                    db,
                    task_id=entry.task_id,
                    good_quantity=entry.good_quantity,
                    defect_quantity=entry.defect_quantity,
                    actor_id=current_user.id,
                    defect_reason=entry.defect_reason,
                    comment=entry.comment,
                    idempotency_key=entry.idempotency_key,
                    executor_user_id=entry.executor_user_id,
                    performed_at=entry.performed_at,
                    accounted_at=entry.accounted_at,
                    shortage_strategy=entry.shortage_strategy,
                    auto_transfer_next=entry.auto_transfer_next,
                    scrap_policy=plant_config.production.scrap_policy,
                )
            results.append(BulkActionResultItem(id=entry.task_id, status="success"))
        except HTTPException as exc:
            results.append(
                BulkActionResultItem(id=entry.task_id, status="failed", reason=str(exc.detail))
            )
        except ValueError as exc:
            results.append(
                BulkActionResultItem(id=entry.task_id, status="failed", reason=str(exc))
            )
        except Exception:
            logger.exception("bulk_complete_tasks: unexpected error for task %s", entry.task_id)
            results.append(
                BulkActionResultItem(id=entry.task_id, status="failed", reason="Внутренняя ошибка сервера")
            )

    # Запись лога аудита
    success_entries = [r for r in results if r.status == "success"]
    failed_ids = [r.id for r in results if r.status == "failed"]
    if success_entries:
        total_good = Decimal(0)
        total_defect = Decimal(0)
        task_ids = []
        product_skus = set()
        operation_names = set()
        
        for raw in payload.entries:
            try:
                entry = BulkCompleteEntry.model_validate(raw)
                if entry.task_id in [s.id for s in success_entries]:
                    total_good += entry.good_quantity
                    total_defect += entry.defect_quantity
                    task_ids.append(entry.task_id)
            except ValidationError:
                # Валидация уже прошла в первом проходе; сюда попадают те же
                # невалидные записи — пропускаем их, агрегат считается по
                # успешно завершённым (success_entries).
                continue

        if task_ids:
            from app.models.product import Product
            from app.models.route import RouteStage
            from app.models.section import Section

            # Справочники для аудита — по одному запросу на список (#294):
            # раньше на каждую задачу шли db.get(WorkTask), db.get(Product) и
            # db.get(RouteStage) с подгрузкой операций, то есть три-четыре
            # запроса на строку батча — и то же самое во втором проходе.
            tasks_by_id = {
                row.id: row
                for row in (
                    await db.execute(select(WorkTask).where(WorkTask.id.in_(task_ids)))
                ).scalars().all()
            }
            product_ids = {
                task.product_id
                for task in tasks_by_id.values()
                if task.product_id is not None
            }
            products_by_id = (
                {
                    row.id: row
                    for row in (
                        await db.execute(select(Product).where(Product.id.in_(product_ids)))
                    ).scalars().all()
                }
                if product_ids
                else {}
            )
            stage_ids = {
                task.route_stage_id
                for task in tasks_by_id.values()
                if task.route_stage_id is not None
            }
            stages_by_id = (
                {
                    row.id: row
                    for row in (
                        await db.execute(
                            select(RouteStage)
                            .where(RouteStage.id.in_(stage_ids))
                            .options(selectinload(RouteStage.operations))
                        )
                    ).scalars().all()
                }
                if stage_ids
                else {}
            )

            first_task = tasks_by_id.get(task_ids[0])
            if first_task:
                section = await db.get(Section, first_task.section_id)

                for tid in task_ids:
                    t = tasks_by_id.get(tid)
                    if t:
                        p = products_by_id.get(t.product_id) if t.product_id is not None else None
                        if p:
                            product_skus.add(p.sku)
                        rs = stages_by_id.get(t.route_stage_id) if t.route_stage_id is not None else None
                        if rs and rs.operations:
                            for op in rs.operations:
                                operation_names.add(op.operation_name)
                
                skus_str = ", ".join(product_skus)
                ops_str = ", ".join(operation_names)
                section_info = f"на участке \"{section.name}\" ({section.code})" if section else ""
                task_info = f"для операций: {ops_str}" if ops_str else ""
                
                status_text = "success" if not failed_ids else "info"
                title_text = "Группа подтверждена" if not failed_ids else "Групповое подтверждение (частично)"
                message_text = f"Группа из {len(success_entries)} задач успешно подтверждена {section_info} {task_info}. Подтверждено всего: годные = {total_good} шт., брак = {total_defect} шт."
                if failed_ids:
                    message_text += f" Не удалось завершить задач: {len(failed_ids)}."
                
                from app.models.audit_log import AuditAction, AuditEntityType
                
                changes_dict = {}
                for raw in payload.entries:
                    try:
                        entry = BulkCompleteEntry.model_validate(raw)
                        if entry.task_id in [s.id for s in success_entries]:
                            changes_dict[str(entry.task_id)] = {
                                "before": {"status": "in_progress"},
                                "after": {"status": "completed", "good_quantity": str(entry.good_quantity), "defect_quantity": str(entry.defect_quantity)}
                            }
                    except ValidationError:
                        # Тот же набор невалидных записей, что и в агрегате выше.
                        continue

                await log_action(
                    db,
                    status=status_text,
                    title=title_text,
                    message=message_text,
                    user=current_user,
                    section_id=first_task.section_id,
                    section_name=section.name if section else None,
                    section_code=section.code if section else None,
                    task_ids=task_ids,
                    product_sku=skus_str or None,
                    operation_name=ops_str or None,
                    qty_text=f"годн: {total_good}, брак: {total_defect}",
                    action=AuditAction.UPDATE,
                    entity_type=AuditEntityType.WORK_TASK,
                    changes=changes_dict,
                )

    return BulkActionResponse(results=results)


@router.patch("/tasks/{task_id}/operation", dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def patch_task_operation(
    task_id: int,
    payload: PatchOperationPayload,
    db: AsyncSession = Depends(get_db),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    await _ensure_task_lock(db, task_id, locked_section_id)
    task = await db.get(WorkTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    await _require_mutable_task(db, task)

    # Validate that the operation exists for this task's section
    op = await db.scalar(
        select(SectionOperation).where(
            SectionOperation.section_id == task.section_id,
            SectionOperation.operation_code == payload.operation_code,
        )
    )
    if not op:
        raise HTTPException(
            status_code=400,
            detail=f"Operation '{payload.operation_code}' not found for section {task.section_id}",
        )

    task.selected_operation_code = payload.operation_code
    await db.commit()
    await db.refresh(task)

    return {
        "task_id": task.id,
        "operation_code": task.selected_operation_code,
        "operation_name": op.operation_name,
    }


@router.post("/transfers", dependencies=[Depends(require_role(list(TRANSFER_WRITER_ROLES)))])
async def create_transfer(
    payload: CreateTransferPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    """Deprecated: thin proxy for ``POST /api/transfers``.

    Kept so external clients that still hit
    ``/api/shopfloor/transfers`` keep working.  New code MUST call
    ``/api/transfers`` directly.
    """
    await _ensure_task_lock(db, payload.from_task_id, locked_section_id, current_user)
    try:
        return await transfer_send(
            db,
            from_task_id=payload.from_task_id,
            to_task_id=payload.to_task_id,
            quantity=payload.quantity,
            actor_id=current_user.id,
            comment=payload.comment,
            idempotency_key=payload.idempotency_key,
            executor_user_id=payload.executor_user_id,
            performed_at=payload.performed_at,
            accounted_at=payload.accounted_at,
            post_factum=payload.post_factum,
            allow_over_plan=payload.allow_over_plan,
            physical_handover_at=payload.physical_handover_at,
            dimensions=payload.dimensions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/final-release", dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def final_release_endpoint(
    task_id: int,
    payload: FinalReleasePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        task = await db.get(WorkTask, task_id)
        if task is None:
            raise ValueError("Task not found")
        await _require_mutable_task(db, task)
        return await final_release(
            db,
            task_id=task_id,
            quantity=payload.quantity,
            actor_id=current_user.id,
            comment=payload.comment,
            idempotency_key=payload.idempotency_key,
            executor_user_id=payload.executor_user_id,
            performed_at=payload.performed_at,
            accounted_at=payload.accounted_at,
            dimensions=payload.dimensions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/defects")
async def create_defect_endpoint(
    payload: CreateDefectPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        return await create_defect(
            db,
            task_id=payload.task_id,
            product_id=payload.product_id,
            section_id=payload.section_id,
            route_stage_id=payload.route_stage_id,
            quantity=payload.quantity,
            actor_id=current_user.id,
            reason=payload.reason,
            comment=payload.comment,
            idempotency_key=payload.idempotency_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/defects/{defect_id}/items")
async def add_defect_item_endpoint(
    defect_id: int,
    payload: AddDefectItemPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        return await add_defect_item(
            db,
            defect_id=defect_id,
            quantity=payload.quantity,
            actor_id=current_user.id,
            defect_type_id=payload.defect_type_id,
            subtype_code=payload.subtype_code,
            reason_code=payload.reason_code,
            description=payload.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/defects/{defect_id}/decisions")
async def defect_decision_endpoint(
    defect_id: int,
    payload: DefectDecisionPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    plant_config: PlantConfig = Depends(get_plant_config),
) -> dict:
    try:
        return await defect_decide(
            db,
            defect_id=defect_id,
            decision_type=payload.decision_type,
            quantity=payload.quantity,
            actor_id=current_user.id,
            target_section_id=payload.target_section_id,
            reason=payload.reason,
            comment=payload.comment,
            idempotency_key=payload.idempotency_key,
            defect_decision_map=plant_config.quality.defect_decision_map.mapping,
            scrap_policy=plant_config.production.scrap_policy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/rework-tasks")
async def create_rework_task(
    payload: ReworkCreatePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        return await rework_create(
            db,
            defect_id=payload.defect_id,
            source_task_id=payload.source_task_id,
            section_id=payload.section_id,
            quantity=payload.quantity,
            actor_id=current_user.id,
            idempotency_key=payload.idempotency_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/comments", status_code=status.HTTP_201_CREATED)
async def create_comment_endpoint(
    payload: CommentPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        return await create_comment(
            db,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            body=payload.body,
            actor_id=current_user.id,
            comment_type=payload.comment_type,
            is_internal=payload.is_internal,
            idempotency_key=payload.idempotency_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/attachments", status_code=status.HTTP_201_CREATED)
async def create_attachment_endpoint(
    payload: CreateAttachmentPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        return await create_attachment(
            db,
            original_filename=payload.original_filename,
            stored_path=payload.stored_path,
            size_bytes=payload.size_bytes,
            actor_id=current_user.id,
            content_type=payload.content_type,
            file_sha256=payload.file_sha256,
            metadata_json=payload.metadata_json,
            idempotency_key=payload.idempotency_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/attachments/{attachment_id}/link", status_code=status.HTTP_201_CREATED)
async def link_attachment_endpoint(
    attachment_id: int,
    payload: LinkAttachmentPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        return await link_attachment(
            db,
            attachment_id=attachment_id,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            actor_id=current_user.id,
            caption=payload.caption,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tasks/{task_id}", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def task_details(task_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await get_task_details(db, task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/transfers/{transfer_id}", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def transfer_details(transfer_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await get_transfer_details(db, transfer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/defects/{defect_id}", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def defect_details(defect_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await get_defect_details(db, defect_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/defect-types", response_model=list[DefectTypeOut], dependencies=[Depends(require_role(list(READER_ROLES)))])
async def list_defect_types(
    db: AsyncSession = Depends(get_db),
) -> list[DefectTypeOut]:
    from app.models.defect import DefectType
    stmt = select(DefectType).where(DefectType.is_active == True).order_by(DefectType.category, DefectType.name)
    items = (await db.execute(stmt)).scalars().all()
    return items


@router.get("/plan-positions/{plan_position_id}/route-stage-aggregates", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def route_stage_aggregates(plan_position_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    return await get_route_stage_aggregates_for_plan_position(db, plan_position_id)


@router.get("/rework-tasks/{rework_task_id}", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def rework_task_details(rework_task_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await get_rework_details(db, rework_task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/entities/{entity_type}/{entity_id}/comments", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def entity_comments(
    entity_type: EntityType,
    entity_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {"comments": await list_entity_comments(db, entity_type, entity_id)}


@router.get("/entities/{entity_type}/{entity_id}/attachments", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def entity_attachments(
    entity_type: EntityType,
    entity_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {"attachments": await list_entity_attachments(db, entity_type, entity_id)}


@router.post("/section-tasks/prepare", dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def prepare_task(
    payload: PrepareTaskPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        return await prepare_section_task(
            db,
            plan_position_id=payload.plan_position_id,
            section_id=payload.section_id,
            quantity=payload.quantity,
            actor_id=current_user.id,
            idempotency_key=payload.idempotency_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sections/summary", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def sections_summary(
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await get_sections_summary(db)


@router.get("/sections/{section_id}/incoming-transfers", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def incoming_transfers(
    section_id: int,
    db: AsyncSession = Depends(get_db),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    _ensure_section_lock(section_id, locked_section_id)
    return await get_section_incoming_transfers(db, section_id=section_id)


@router.get("/sections/{section_id}/board", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def section_board(
    section_id: int,
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None, description="ILIKE: product_sku, task id, operation_name"),
    product_sku: str | None = Query(None, description="Column filter: ILIKE on product/source/output sku"),
    dimensions: str | None = Query(None, description="Column filter: exact JSON match on task dimensions, e.g. {\"length_mm\":2700} or null"),
    sort: str | None = Query(
        default=None,
        description="Comma-separated sort rules: field:asc|desc, e.g. sequence:asc,due_date:asc",
    ),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    _ensure_section_lock(section_id, locked_section_id)
    from app.domain.dimensions import DimensionsValidationError, parse_dimensions_filter

    try:
        parse_dimensions_filter(dimensions)
    except DimensionsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Ось дат доски — UTC, как в daily-stats (#259): фронт шлёт наивные
    # `YYYY-MM-DDTHH:MM:SS`, и без нормализации asyncpg читал бы их как
    # host-local, уводя окно от `WorkTask.created_at` (timestamptz).
    # `None` — «фильтра нет», окном дня его не подменяем.
    date_from = _naive_as_utc(date_from) if date_from is not None else None
    date_to = _naive_as_utc(date_to) if date_to is not None else None
    return await get_section_board(
        db,
        section_id=section_id,
        date_from=date_from,
        date_to=date_to,
        status=status,
        search=search,
        product_sku=product_sku,
        dimensions=dimensions,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.get("/sections/{section_id}/board/column-values", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def section_board_column_values(
    section_id: int,
    column: str = Query(..., description="Серверная колонка доски, напр. product_sku"),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None, description="ILIKE: product_sku, task id, operation_name"),
    product_sku: str | None = Query(None, description="Column filter: ILIKE on product/source/output sku"),
    dimensions: str | None = Query(None, description="Column filter: exact JSON match on task dimensions"),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    """Справочник значений серверной колонки доски (#211).

    Значения не зависят от текущей страницы доски; фильтр самой колонки
    отбрасывается, чтобы список не схлопывался к выбранному значению.
    """
    _ensure_section_lock(section_id, locked_section_id)
    if column not in BOARD_COLUMN_VALUE_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"колонка {column!r} не отдаёт справочник значений",
        )
    return await get_section_board_column_values(
        db,
        section_id=section_id,
        column=column,
        date_from=_naive_as_utc(date_from) if date_from is not None else None,
        date_to=_naive_as_utc(date_to) if date_to is not None else None,
        status=status,
        search=search,
        product_sku=product_sku,
        dimensions=dimensions,
        limit=limit,
    )


@router.get("/sections/{section_id}/daily-stats", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def section_daily_stats(
    section_id: int,
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    _ensure_section_lock(section_id, locked_section_id)
    now = datetime.now(UTC)
    d_from = _naive_as_utc(date_from) if date_from else datetime.combine(now.date(), time.min, tzinfo=UTC)
    d_to = _naive_as_utc(date_to) if date_to else datetime.combine(now.date(), time.max, tzinfo=UTC)
    return await get_section_daily_stats(
        db,
        section_id=section_id,
        date_from=d_from,
        date_to=d_to,
    )


@router.post("/remainders/return", dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def return_remainder(
    payload: ReturnRemainderPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    """Return excess quantity from a task to warehouse stock.

    Writes StockTransaction(RETURN_TO_STOCK). Checks that quantity
    does not exceed what is available for return on the task.
    """
    from app.models.work_task import WorkTask
    from app.stock import Reason, StockCommand, StockCommandService

    await _ensure_task_lock(db, payload.task_id, locked_section_id)
    try:
        quantity = Decimal(str(payload.quantity))
        if quantity <= 0:
            raise ValueError("Quantity must be > 0")

        task = await db.get(WorkTask, payload.task_id)
        if task is None:
            raise ValueError("Task not found")
        await _require_mutable_task(db, task)

        # Available for return = issued - completed - transferred
        from app.stock.services import StockProjectionManager
        pm = StockProjectionManager()
        cache = await pm.get_task_cache(db, task.id)
        available_for_return = cache["issued_quantity"] - cache["completed_quantity"] - cache["transferred_quantity"]
        if available_for_return <= 0:
            raise ValueError("No excess quantity available for return")
        if quantity > available_for_return:
            raise ValueError(f"Return quantity ({quantity}) exceeds available for return ({available_for_return})")

        now = datetime.now(UTC)
        svc = StockCommandService()
        # Журнал действий (#116): Action по цепочке задачи; actor —
        # снимок имени пользователя, как в complete_task/defect_decide.
        action = await action_journal_service.log_task_action(
            db,
            action_type="return_to_stock",
            ref_id=task.id,
            actor=await _get_user_snapshot_name(db, current_user.id),
        )
        # Признак «пройденные операции» (ADR-0043): возвращается в запас
        # необработанный остаток задания, поэтому он несёт операции до
        # ПРЕДЫДУЩЕГО этапа, а не пройденные операции своего.
        from app.services.material_operations import (
            completed_operations_for_task,
            previous_stage_sequence,
        )

        previous_sequence = await previous_stage_sequence(db, task)
        through_previous = await completed_operations_for_task(
            db, task, through_sequence=previous_sequence or 0
        )
        # return_to_stock: material removed from section (to_location=None for now)
        tx = await svc.record(db, StockCommand(
            product_id=task.product_id,
            from_location_id=task.section_id,
            to_location_id=None,
            quantity=quantity,
            reason=Reason.RETURN_TO_STOCK,
            task_id=task.id,
            completed_operations=through_previous,
            comment=payload.comment,
            idempotency_key=payload.idempotency_key,
            created_by=current_user.id,
            executor_user_id=payload.executor_user_id or current_user.id,
            performed_at=payload.performed_at or now,
            accounted_at=payload.accounted_at or now,
            action_id=action.id,
        ))

        return {"transaction_id": tx.id, "task_id": task.id}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ─── SPG Available for Task ──────────────────────────────────────────────────


@router.get("/tasks/{task_id}/spg-available")
async def task_spg_available(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Available stock of the task's input group at the storage feeding its section.

    ``available`` — сумма по ОДНОЙ группе оси операций: материал на питающем
    складе лежит в группе своего этапа (ADR-0055 п.7) — ровно та группа,
    которую спишет ``TRANSFER_SEND`` со склада в это задание. Без фильтра по
    оси сумма складывала бы сырьё и подготовленный материал в одно число, а
    списание точное: нет строки с совпавшим признаком — расход невозможен,
    даже если участок суммарно полон (ADR-0055 п.3). Размер — вторая ось
    ключа, но здесь она не выбирается: размер задаёт конкретная передача
    (``task_transferable_lines`` даёт бюджет по каждому размеру), поэтому
    ``available`` — физический остаток группы по всем размерам.
    """
    from sqlalchemy import func

    from app.stock.models import QualityState, StockBalance
    from app.stock.services import completed_operations_match_clause

    task = await db.get(WorkTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    # Find stock locations that feed this task's section
    from app.services.shopfloor.operations_tasks import _get_stock_location
    stock_loc = await _get_stock_location(db, task.section_id)

    if stock_loc is None:
        return {
            "available": 0,
            "location_id": None,
            "location_name": None,
            "completed_operations": None,
            "source": "stock_balance",
        }

    from app.models import Section
    location = await db.get(Section, stock_loc)

    from app.services.material_operations import completed_operations_for_task
    from app.services.shopfloor.operations_transform import resolve_consume_operations

    if stock_loc == task.section_id:
        # Задание стоит на самой складской секции: материал у неё несёт признак
        # её собственного этапа — так его пишет её же TRANSFER_SEND.
        completed_operations = await completed_operations_for_task(db, task)
    else:
        # Материал на питающем складе несёт признак этапа склада — это группа
        # входа задания, её же читает потребление входа (ADR-0055 п.7).
        completed_operations = await resolve_consume_operations(db, task)

    available = await db.scalar(
        select(func.coalesce(func.sum(StockBalance.balance_qty), 0))
        .where(
            StockBalance.product_id == task.product_id,
            StockBalance.location_id == stock_loc,
            StockBalance.balance_qty > 0,
            StockBalance.quality_state == QualityState.GOOD,
            completed_operations_match_clause(
                StockBalance.completed_operations, completed_operations
            ),
        )
    ) or 0

    return {
        "available": float(available),
        "location_id": stock_loc,
        "location_name": location.name if location else None,
        "completed_operations": completed_operations,
        "source": "stock_balance",
    }
