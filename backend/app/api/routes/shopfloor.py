from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import READER_ROLES, WRITER_ROLES, require_role
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.defect import DefectDecisionType
from app.models.entity_comment import EntityType
from app.models.route import SectionOperation
from app.models.transfer import Transfer
from app.models.user import User
from app.models.work_task import WorkTask
from app.services.shopfloor_service import (
    add_defect_item,
    complete_task,
    consume_remainder,
    create_attachment,
    create_comment,
    create_defect,
    defect_decide,
    final_release,
    get_defect_details,
    get_route_stage_aggregates_for_plan_position,
    get_section_board,
    get_section_daily_stats,
    get_section_payload_keys,
    get_sections_summary,
    get_task_details,
    get_warehouse_remainders,
    issue_to_work,
    link_attachment,
    prepare_section_task,
    return_remainder_to_stock,
    rework_create,
)
from app.transfers.queries import get_section_incoming_transfers, get_transfer_details
from app.transfers.services import (
    resolve_transfer_discrepancy_link,
    transfer_receive,
    transfer_send,
)
from app.services.shopfloor_service import (
    get_rework_details,
    list_entity_comments,
    list_entity_attachments,
)

router = APIRouter(prefix="/shopfloor", tags=["sections-operations"])
LOCKED_SECTION_ERROR = "Section is locked to single-window context"


def get_single_window_locked_section_id(
    x_shopfloor_single_section_id: int | None = Header(default=None, alias="X-Shopfloor-Single-Section-Id"),
) -> int | None:
    return x_shopfloor_single_section_id


def _ensure_section_lock(section_id: int, locked_section_id: int | None) -> None:
    if locked_section_id is not None and section_id != locked_section_id:
        raise HTTPException(status_code=403, detail=LOCKED_SECTION_ERROR)


async def _ensure_task_lock(db: AsyncSession, task_id: int, locked_section_id: int | None) -> None:
    if locked_section_id is None:
        return
    task_section_id = await db.scalar(select(WorkTask.section_id).where(WorkTask.id == task_id))
    if task_section_id is not None and task_section_id != locked_section_id:
        raise HTTPException(status_code=403, detail=LOCKED_SECTION_ERROR)


async def _ensure_transfer_target_lock(db: AsyncSession, transfer_id: int, locked_section_id: int | None) -> None:
    if locked_section_id is None:
        return
    transfer_target_section_id = await db.scalar(select(Transfer.to_section_id).where(Transfer.id == transfer_id))
    if transfer_target_section_id is not None and transfer_target_section_id != locked_section_id:
        raise HTTPException(status_code=403, detail=LOCKED_SECTION_ERROR)


class PatchOperationPayload(BaseModel):
    operation_code: str


class IssuePayload(BaseModel):
    quantity: Decimal
    comment: str | None = None
    reason: str | None = None
    source_ref: str | None = None
    idempotency_key: str | None = None
    executor_user_id: int | None = None
    performed_at: datetime | None = None
    accounted_at: datetime | None = None


class CompletePayload(BaseModel):
    good_quantity: Decimal = Decimal("0")
    defect_quantity: Decimal = Decimal("0")
    defect_reason: str | None = None
    comment: str | None = None
    idempotency_key: str | None = None
    executor_user_id: int | None = None
    performed_at: datetime | None = None
    accounted_at: datetime | None = None


class CreateTransferPayload(BaseModel):
    from_task_id: int
    to_task_id: int | None = None
    quantity: Decimal
    comment: str | None = None
    idempotency_key: str | None = None
    executor_user_id: int | None = None
    performed_at: datetime | None = None
    accounted_at: datetime | None = None


class AcceptTransferPayload(BaseModel):
    accepted_quantity: Decimal = Decimal("0")
    rejected_quantity: Decimal = Decimal("0")
    reason: str | None = None
    comment: str | None = None
    idempotency_key: str | None = None
    executor_user_id: int | None = None
    performed_at: datetime | None = None
    accounted_at: datetime | None = None


class ResolveDiscrepancyPayload(BaseModel):
    defect_item_id: int
    quantity: Decimal
    comment: str | None = None


class FinalReleasePayload(BaseModel):
    quantity: Decimal
    comment: str | None = None
    idempotency_key: str | None = None
    executor_user_id: int | None = None
    performed_at: datetime | None = None
    accounted_at: datetime | None = None


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
    task_id: int
    quantity: Decimal
    reason: str | None = None
    comment: str | None = None
    idempotency_key: str | None = None


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


@router.post("/tasks/{task_id}/issue", dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def issue_task(
    task_id: int,
    payload: IssuePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    await _ensure_task_lock(db, task_id, locked_section_id)
    try:
        return await issue_to_work(
            db,
            task_id=task_id,
            quantity=payload.quantity,
            actor_id=current_user.id,
            comment=payload.comment,
            source_ref=payload.source_ref,
            idempotency_key=payload.idempotency_key,
            executor_user_id=payload.executor_user_id,
            performed_at=payload.performed_at,
            accounted_at=payload.accounted_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/complete", dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def complete_task_endpoint(
    task_id: int,
    payload: CompletePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    await _ensure_task_lock(db, task_id, locked_section_id)
    try:
        return await complete_task(
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
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@router.post("/transfers", dependencies=[Depends(require_role(list(WRITER_ROLES)))])
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
    await _ensure_task_lock(db, payload.from_task_id, locked_section_id)
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
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/transfers/{transfer_id}/accept", dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def accept_transfer(
    transfer_id: int,
    payload: AcceptTransferPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    await _ensure_transfer_target_lock(db, transfer_id, locked_section_id)
    try:
        return await transfer_receive(
            db,
            transfer_id=transfer_id,
            accepted_quantity=payload.accepted_quantity,
            rejected_quantity=payload.rejected_quantity,
            actor_id=current_user.id,
            reason=payload.reason,
            comment=payload.comment,
            idempotency_key=payload.idempotency_key,
            executor_user_id=payload.executor_user_id,
            performed_at=payload.performed_at,
            accounted_at=payload.accounted_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/transfers/{transfer_id}/discrepancies/{discrepancy_id}/resolve-link")
async def resolve_discrepancy(
    transfer_id: int,
    discrepancy_id: int,
    payload: ResolveDiscrepancyPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        return await resolve_transfer_discrepancy_link(
            db,
            transfer_id=transfer_id,
            discrepancy_id=discrepancy_id,
            defect_item_id=payload.defect_item_id,
            quantity=payload.quantity,
            actor_id=current_user.id,
            comment=payload.comment,
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


@router.post("/comments")
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


@router.post("/attachments")
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


@router.post("/attachments/{attachment_id}/link")
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
    db: AsyncSession = Depends(get_db),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    _ensure_section_lock(section_id, locked_section_id)
    return await get_section_board(
        db,
        section_id=section_id,
        date_from=date_from,
        date_to=date_to,
        status=status,
    )


@router.get("/sections/{section_id}/payload-keys", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def section_payload_keys(
    section_id: int,
    db: AsyncSession = Depends(get_db),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    _ensure_section_lock(section_id, locked_section_id)
    return await get_section_payload_keys(db, section_id=section_id)


@router.get("/sections/{section_id}/daily-stats", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def section_daily_stats(
    section_id: int,
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    _ensure_section_lock(section_id, locked_section_id)
    from datetime import datetime as dt, time

    now = dt.now()
    d_from = date_from or dt.combine(now.date(), time.min)
    d_to = date_to or dt.combine(now.date(), time.max)
    return await get_section_daily_stats(
        db,
        section_id=section_id,
        date_from=d_from,
        date_to=d_to,
    )


@router.get("/remainders", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def list_warehouse_remainders(
    section_id: int | None = Query(None),
    plan_position_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List active warehouse remainders (surplus returned to stock).

    If ``plan_position_id`` is provided, only returns remainders that are
    either unreserved or reserved for this specific plan position.
    """
    return await get_warehouse_remainders(db, section_id=section_id, plan_position_id=plan_position_id)


@router.post("/remainders/return", dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def return_remainder(
    payload: ReturnRemainderPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    """Manually return excess quantity from a task to warehouse stock."""
    await _ensure_task_lock(db, payload.task_id, locked_section_id)
    try:
        return await return_remainder_to_stock(
            db,
            task_id=payload.task_id,
            quantity=payload.quantity,
            actor_id=current_user.id,
            comment=payload.comment,
            idempotency_key=payload.idempotency_key,
            executor_user_id=payload.executor_user_id,
            performed_at=payload.performed_at,
            accounted_at=payload.accounted_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/remainders/consume", dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def consume_remainder_endpoint(
    payload: ConsumeRemainderPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    """Use a warehouse remainder for issuing to work on a task."""
    await _ensure_task_lock(db, payload.task_id, locked_section_id)
    try:
        return await consume_remainder(
            db,
            remainder_id=payload.remainder_id,
            task_id=payload.task_id,
            quantity=payload.quantity,
            actor_id=current_user.id,
            comment=payload.comment,
            idempotency_key=payload.idempotency_key,
            executor_user_id=payload.executor_user_id,
            performed_at=payload.performed_at,
            accounted_at=payload.accounted_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ─── SPG Available for Task ──────────────────────────────────────────────────


@router.get("/tasks/{task_id}/spg-available")
async def task_spg_available(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return available remainders in the SPG for a task's product + section."""
    from app.models.spg import SpgSection, StorageProductionGroup
    from app.models.spg_remainder import SpgRemainder
    from sqlalchemy import func

    task = await db.get(WorkTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    # Find SPG for this task's section
    spg_section = await db.scalar(
        select(SpgSection).where(SpgSection.section_id == task.section_id)
    )
    if spg_section is None:
        return {"spg_available": 0, "spg_id": None, "spg_name": None, "spg_code": None}

    spg = await db.get(StorageProductionGroup, spg_section.spg_id)
    if spg is None:
        return {"spg_available": 0, "spg_id": None, "spg_name": None, "spg_code": None}

    available = await db.scalar(
        select(func.coalesce(func.sum(SpgRemainder.remainder_quantity), 0))
        .where(
            SpgRemainder.product_id == task.product_id,
            SpgRemainder.spg_id == spg.id,
            SpgRemainder.consumed_at.is_(None),
            SpgRemainder.remainder_quantity > 0,
        )
    )

    return {
        "spg_available": float(available or 0),
        "spg_id": spg.id,
        "spg_name": spg.name,
        "spg_code": spg.code,
    }
