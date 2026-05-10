from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.defect import DefectDecisionType
from app.models.entity_comment import EntityType
from app.models.user import User
from app.services.shopfloor_service import (
    add_defect_item,
    complete_task,
    create_attachment,
    create_comment,
    create_defect,
    defect_decide,
    final_release,
    get_defect_details,
    get_route_stage_aggregates_for_plan_position,
    get_task_details,
    get_transfer_details,
    issue_to_work,
    link_attachment,
    resolve_transfer_discrepancy_link,
    rework_create,
    transfer_receive,
    transfer_send,
)
from app.services.shopfloor_service import (
    get_rework_details,
    list_entity_comments,
    list_entity_attachments,
)

router = APIRouter(prefix="/shopfloor", tags=["shopfloor"])


class IssuePayload(BaseModel):
    quantity: Decimal
    comment: str | None = None
    reason: str | None = None
    source_ref: str | None = None
    idempotency_key: str | None = None


class CompletePayload(BaseModel):
    good_quantity: Decimal = Decimal("0")
    defect_quantity: Decimal = Decimal("0")
    defect_reason: str | None = None
    comment: str | None = None
    idempotency_key: str | None = None


class CreateTransferPayload(BaseModel):
    from_task_id: int
    to_task_id: int
    quantity: Decimal
    comment: str | None = None
    idempotency_key: str | None = None


class AcceptTransferPayload(BaseModel):
    accepted_quantity: Decimal = Decimal("0")
    rejected_quantity: Decimal = Decimal("0")
    reason: str | None = None
    comment: str | None = None
    idempotency_key: str | None = None


class ResolveDiscrepancyPayload(BaseModel):
    defect_item_id: int
    quantity: Decimal
    comment: str | None = None


class FinalReleasePayload(BaseModel):
    quantity: Decimal
    comment: str | None = None
    idempotency_key: str | None = None


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


@router.post("/tasks/{task_id}/issue")
async def issue_task(
    task_id: int,
    payload: IssuePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        return await issue_to_work(
            db,
            task_id=task_id,
            quantity=payload.quantity,
            actor_id=current_user.id,
            comment=payload.comment,
            source_ref=payload.source_ref,
            idempotency_key=payload.idempotency_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/complete")
async def complete_task_endpoint(
    task_id: int,
    payload: CompletePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
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
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/transfers")
async def create_transfer(
    payload: CreateTransferPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        return await transfer_send(
            db,
            from_task_id=payload.from_task_id,
            to_task_id=payload.to_task_id,
            quantity=payload.quantity,
            actor_id=current_user.id,
            comment=payload.comment,
            idempotency_key=payload.idempotency_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/transfers/{transfer_id}/accept")
async def accept_transfer(
    transfer_id: int,
    payload: AcceptTransferPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
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


@router.post("/tasks/{task_id}/final-release")
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


@router.get("/tasks/{task_id}")
async def task_details(task_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await get_task_details(db, task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/transfers/{transfer_id}")
async def transfer_details(transfer_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await get_transfer_details(db, transfer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/defects/{defect_id}")
async def defect_details(defect_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await get_defect_details(db, defect_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/plan-positions/{plan_position_id}/route-stage-aggregates")
async def route_stage_aggregates(plan_position_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    return await get_route_stage_aggregates_for_plan_position(db, plan_position_id)


@router.get("/rework-tasks/{rework_task_id}")
async def rework_task_details(rework_task_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await get_rework_details(db, rework_task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/entities/{entity_type}/{entity_id}/comments")
async def entity_comments(
    entity_type: EntityType,
    entity_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {"comments": await list_entity_comments(db, entity_type, entity_id)}


@router.get("/entities/{entity_type}/{entity_id}/attachments")
async def entity_attachments(
    entity_type: EntityType,
    entity_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {"attachments": await list_entity_attachments(db, entity_type, entity_id)}
