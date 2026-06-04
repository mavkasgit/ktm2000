from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment, AttachmentLink
from app.models.defect import DefectDecision, DefectItem
from app.models.entity_comment import EntityComment, EntityType
from app.models.internal_plan import SectionPlanLine
from app.models.movement import Movement
from app.models.rework_task import ReworkTask
from app.models.route import RouteStage
from app.models.section import Section

from .cache import _compute_available_from_balances
from .common import _get_defect, _get_task, _to_decimal

async def get_task_details(db: AsyncSession, task_id: int) -> dict:
    task = await _get_task(db, task_id)
    stage = await db.get(RouteStage, task.route_stage_id)
    movements = (
        await db.execute(select(Movement).where(Movement.task_id == task.id).order_by(Movement.created_at, Movement.id))
    ).scalars().all()
    is_first_stage = bool(stage and stage.sequence == 1)
    available = _compute_available_from_balances(
        planned_quantity=_to_decimal(task.planned_quantity),
        received_quantity=_to_decimal(task.cached_received_quantity),
        issued_quantity=_to_decimal(task.cached_issued_quantity),
        is_first_stage=is_first_stage,
    )
    return {
        "id": task.id,
        "status": task.status.value,
        "planned_quantity": str(task.planned_quantity),
        "cache": {
            "available_quantity": str(available),
            "issued_quantity": str(task.cached_issued_quantity),
            "in_work_quantity": str(task.cached_in_work_quantity),
            "completed_quantity": str(task.cached_completed_quantity),
            "transferred_quantity": str(task.cached_transferred_quantity),
            "received_quantity": str(task.cached_received_quantity),
            "rejected_quantity": str(task.cached_rejected_quantity),
            "remaining_quantity": str(task.cached_remaining_quantity),
        },
        "route_step": {
            "id": stage.id if stage else None,
            "sequence": stage.sequence if stage else None,
            "operation_code": stage.operations[0].operation_code if stage and stage.operations else None,
            "operation_name": ", ".join(op.operation_name for op in stage.operations) if stage and stage.operations else None,
            "is_final": stage.is_final if stage else None,
        },
        "movements": [
            {
                "id": m.id,
                "movement_type": m.movement_type.value,
                "quantity": str(m.quantity),
                "from_section_id": m.from_section_id,
                "to_section_id": m.to_section_id,
                "transfer_id": m.transfer_id,
                "reason": m.reason,
                "comment": m.comment,
                "created_by": m.created_by,
                "executor_user_id": m.executor_user_id,
                "performed_at": m.performed_at.isoformat() if m.performed_at else None,
                "accounted_at": m.accounted_at.isoformat() if m.accounted_at else None,
                "created_at": m.created_at.isoformat(),
            }
            for m in movements
        ],
    }

async def get_transfer_details(db: AsyncSession, transfer_id: int) -> dict:
    """Transfer details with discrepancies.

    Moved to :mod:`app.transfers.queries`.  Kept here as a thin
    re-export for backward compatibility with the legacy
    ``from app.services.shopfloor.queries_details import
    get_transfer_details`` import path.
    """
    from app.transfers.queries import get_transfer_details as _impl

    return await _impl(db, transfer_id)

async def get_defect_details(db: AsyncSession, defect_id: int) -> dict:
    defect = await _get_defect(db, defect_id)
    items = (
        await db.execute(select(DefectItem).where(DefectItem.defect_id == defect.id).order_by(DefectItem.id))
    ).scalars().all()
    decisions = (
        await db.execute(select(DefectDecision).where(DefectDecision.defect_id == defect.id).order_by(DefectDecision.id))
    ).scalars().all()
    comments = (
        await db.execute(
            select(EntityComment)
            .where(EntityComment.entity_type == EntityType.defect, EntityComment.entity_id == defect.id)
            .order_by(EntityComment.id)
        )
    ).scalars().all()
    attachments = (
        await db.execute(
            select(AttachmentLink, Attachment)
            .join(Attachment, Attachment.id == AttachmentLink.attachment_id)
            .where(AttachmentLink.entity_type == EntityType.defect, AttachmentLink.entity_id == defect.id)
            .order_by(AttachmentLink.id)
        )
    ).all()
    return {
        "id": defect.id,
        "status": defect.status.value,
        "product_id": defect.product_id,
        "section_id": defect.section_id,
        "task_id": defect.task_id,
        "responsible_section_id": defect.responsible_section_id,
        "comment": defect.comment,
        "items": [
            {
                "id": item.id,
                "defect_type_id": item.defect_type_id,
                "defect_type_code_snapshot": item.defect_type_code_snapshot,
                "defect_type_name_snapshot": item.defect_type_name_snapshot,
                "subtype_code": item.subtype_code,
                "reason_code": item.reason_code,
                "quantity": str(item.quantity),
                "description": item.description,
            }
            for item in items
        ],
        "decisions": [
            {
                "id": decision.id,
                "decision_type": decision.decision_type.value,
                "quantity": str(decision.quantity),
                "target_section_id": decision.target_section_id,
                "reason": decision.reason,
                "comment": decision.comment,
                "decided_by": decision.decided_by,
                "decided_at": decision.decided_at.isoformat(),
            }
            for decision in decisions
        ],
        "comments": [
            {
                "id": comment.id,
                "body": comment.body,
                "comment_type": comment.comment_type,
                "is_internal": comment.is_internal,
                "author_id": comment.author_id,
                "created_at": comment.created_at.isoformat(),
            }
            for comment in comments
        ],
        "attachments": [
            {
                "attachment_link_id": link.id,
                "attachment_id": attachment.id,
                "original_filename": attachment.original_filename,
                "stored_path": attachment.stored_path,
                "caption": link.caption,
            }
            for link, attachment in attachments
        ],
    }

async def get_route_stage_aggregates_for_plan_position(db: AsyncSession, plan_position_id: int) -> dict:
    lines = (
        await db.execute(
            select(SectionPlanLine, RouteStage, Section)
            .join(RouteStage, RouteStage.id == SectionPlanLine.route_stage_id)
            .join(Section, Section.id == RouteStage.section_id)
            .where(SectionPlanLine.plan_position_id == plan_position_id)
            .order_by(SectionPlanLine.sequence)
        )
    ).all()
    if not lines:
        return {"plan_position_id": plan_position_id, "stages": []}

    return {
        "plan_position_id": plan_position_id,
        "stages": [
            {
                "section_plan_line_id": line.id,
                "route_stage_id": line.route_stage_id,
                "section_id": stage.section_id,
                "section_code": section.code,
                "section_name": section.name,
                "section_icon": section.icon,
                "section_icon_color": section.icon_color,
                "sequence": line.sequence,
                "operation_code": stage.operations[0].operation_code if stage.operations else None,
                "operation_name": ", ".join(op.operation_name for op in stage.operations) if stage.operations else "",
                "is_final": stage.is_final,
                "planned_quantity": str(line.planned_quantity),
                "available_quantity": str(line.cached_available_quantity),
                "issued_quantity": str(line.cached_issued_quantity),
                "completed_quantity": str(line.cached_completed_quantity),
                "transferred_quantity": str(line.cached_transferred_quantity),
                "received_quantity": str(line.cached_received_quantity),
                "rejected_quantity": str(line.cached_rejected_quantity),
                "remaining_quantity": str(line.cached_remaining_quantity),
            }
            for line, stage, section in lines
        ],
    }

async def get_rework_details(db: AsyncSession, rework_task_id: int) -> dict:
    rework = await db.get(ReworkTask, rework_task_id)
    if rework is None:
        raise ValueError("Rework task not found")

    decisions = (
        await db.execute(
            select(DefectDecision).where(
                DefectDecision.defect_id == rework.defect_id
            ).order_by(DefectDecision.id)
        )
    ).scalars().all()

    return {
        "id": rework.id,
        "defect_id": rework.defect_id,
        "source_task_id": rework.source_task_id,
        "section_id": rework.section_id,
        "product_id": rework.product_id,
        "quantity": str(rework.quantity),
        "status": rework.status.value,
        "created_at": rework.created_at.isoformat(),
        "closed_at": rework.closed_at.isoformat() if rework.closed_at else None,
        "defect_decisions": [
            {
                "id": d.id,
                "decision_type": d.decision_type.value,
                "quantity": str(d.quantity),
                "decided_at": d.decided_at.isoformat(),
            }
            for d in decisions
        ],
    }

async def list_entity_comments(
    db: AsyncSession,
    entity_type: EntityType,
    entity_id: int,
) -> list[dict]:
    comments = (
        await db.execute(
            select(EntityComment)
            .where(EntityComment.entity_type == entity_type, EntityComment.entity_id == entity_id)
            .order_by(EntityComment.created_at, EntityComment.id)
        )
    ).scalars().all()
    return [
        {
            "id": c.id,
            "comment_type": c.comment_type,
            "body": c.body,
            "is_internal": c.is_internal,
            "author_id": c.author_id,
            "created_at": c.created_at.isoformat(),
        }
        for c in comments
    ]

async def list_entity_attachments(
    db: AsyncSession,
    entity_type: EntityType,
    entity_id: int,
) -> list[dict]:
    links = (
        await db.execute(
            select(AttachmentLink, Attachment)
            .join(Attachment, Attachment.id == AttachmentLink.attachment_id)
            .where(AttachmentLink.entity_type == entity_type, AttachmentLink.entity_id == entity_id)
            .order_by(AttachmentLink.created_at, AttachmentLink.id)
        )
    ).all()
    return [
        {
            "attachment_link_id": link.id,
            "attachment_id": attachment.id,
            "original_filename": attachment.original_filename,
            "stored_path": attachment.stored_path,
            "content_type": attachment.content_type,
            "size_bytes": attachment.size_bytes,
            "caption": link.caption,
            "created_at": link.created_at.isoformat(),
        }
        for link, attachment in links
    ]

