from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import Defect, DefectDecision, DefectDecisionType, DefectItem, DefectStatus, DefectType
from app.models.movement import Movement, MovementType
from app.models.rework_task import ReworkTask, ReworkTaskStatus

from .cache import _refresh_section_plan_line_cache, _refresh_task_cache
from .common import _check_idempotency, _ensure_positive, _get_defect, _get_task, _to_decimal

async def create_defect(
    db: AsyncSession,
    *,
    task_id: int,
    quantity: Decimal,
    actor_id: int,
    reason: str | None = None,
    comment: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    if idempotency_key:
        existing = await _check_idempotency(db, idempotency_key=idempotency_key, entity_type=Defect)
        if existing is not None:
            return {"defect_id": existing.id, "item_id": None, "idempotent_replay": True}

    task = await _get_task(db, task_id)
    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")

    defect = Defect(
        product_id=task.product_id,
        section_id=task.section_id,
        task_id=task.id,
        status=DefectStatus.decision_required,
        comment=comment,
        created_by=actor_id,
        idempotency_key=idempotency_key,
    )
    db.add(defect)
    await db.flush()
    item = DefectItem(
        defect_id=defect.id,
        quantity=quantity,
        defect_type_code_snapshot=reason,
        defect_type_name_snapshot=reason,
        description=comment,
        created_by=actor_id,
    )
    db.add(item)
    return {"defect_id": defect.id, "item_id": item.id}

async def add_defect_item(
    db: AsyncSession,
    *,
    defect_id: int,
    quantity: Decimal,
    actor_id: int,
    defect_type_id: int | None = None,
    subtype_code: str | None = None,
    reason_code: str | None = None,
    description: str | None = None,
) -> dict:
    defect = await _get_defect(db, defect_id)
    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")
    defect_type = await db.get(DefectType, defect_type_id) if defect_type_id else None

    item = DefectItem(
        defect_id=defect.id,
        defect_type_id=defect_type_id,
        defect_type_code_snapshot=defect_type.code if defect_type else None,
        defect_type_name_snapshot=defect_type.name if defect_type else None,
        subtype_code=subtype_code,
        reason_code=reason_code,
        quantity=quantity,
        description=description,
        created_by=actor_id,
    )
    db.add(item)
    await db.flush()
    return {"defect_item_id": item.id}

async def defect_decide(
    db: AsyncSession,
    *,
    defect_id: int,
    decision_type: DefectDecisionType,
    quantity: Decimal,
    actor_id: int,
    target_section_id: int | None = None,
    reason: str | None = None,
    comment: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    defect = await _get_defect(db, defect_id)
    task = await _get_task(db, defect.task_id)

    if idempotency_key:
        existing = await _check_idempotency(db, idempotency_key=idempotency_key, entity_type=DefectDecision)
        if existing is not None:
            # Find associated rework task if decision type was rework
            rework = await db.scalar(
                select(ReworkTask).where(ReworkTask.defect_id == defect.id).order_by(ReworkTask.id)
            )
            return {
                "defect_id": defect.id,
                "decision_id": existing.id,
                "defect_status": defect.status.value,
                "rework_task_id": rework.id if rework else None,
                "idempotent_replay": True,
            }

    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")

    decision = DefectDecision(
        defect_id=defect.id,
        decision_type=decision_type,
        quantity=quantity,
        target_section_id=target_section_id,
        reason=reason,
        comment=comment,
        idempotency_key=idempotency_key,
        decided_by=actor_id,
    )
    db.add(decision)
    await db.flush()

    rework_task_id: int | None = None
    if decision_type == DefectDecisionType.scrap:
        movement = Movement(
            product_id=task.product_id,
            task_id=task.id,
            section_plan_line_id=task.section_plan_line_id,
            from_section_id=task.section_id,
            to_section_id=task.section_id,
            movement_type=MovementType.scrap,
            quantity=quantity,
            reason=reason,
            comment=comment,
            created_by=actor_id,
        )
        db.add(movement)
        defect.status = DefectStatus.scrapped
    elif decision_type in {DefectDecisionType.rework_current, DefectDecisionType.return_previous}:
        rework = ReworkTask(
            defect_id=defect.id,
            source_task_id=task.id,
            section_id=target_section_id or task.section_id,
            product_id=task.product_id,
            quantity=quantity,
            status=ReworkTaskStatus.open,
            created_by=actor_id,
        )
        db.add(rework)
        await db.flush()
        rework_task_id = rework.id
        defect.status = DefectStatus.rework_task_created
    elif decision_type == DefectDecisionType.accept_with_deviation:
        defect.status = DefectStatus.accepted_with_deviation
    else:
        defect.status = DefectStatus.decision_required

    await _refresh_task_cache(db, task.id)
    await _refresh_section_plan_line_cache(db, task.section_plan_line_id)
    return {"defect_id": defect.id, "decision_id": decision.id, "defect_status": defect.status.value, "rework_task_id": rework_task_id}

async def rework_create(
    db: AsyncSession,
    *,
    defect_id: int,
    source_task_id: int,
    section_id: int,
    quantity: Decimal,
    actor_id: int,
    idempotency_key: str | None = None,
) -> dict:
    defect = await _get_defect(db, defect_id)
    source_task = await _get_task(db, source_task_id)

    if idempotency_key:
        existing = await _check_idempotency(db, idempotency_key=idempotency_key, entity_type=ReworkTask)
        if existing is not None:
            return {"rework_task_id": existing.id, "idempotent_replay": True}

    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")
    rework = ReworkTask(
        defect_id=defect.id,
        source_task_id=source_task.id,
        section_id=section_id,
        product_id=source_task.product_id,
        quantity=quantity,
        status=ReworkTaskStatus.open,
        created_by=actor_id,
        idempotency_key=idempotency_key,
    )
    db.add(rework)
    await db.flush()
    defect.status = DefectStatus.rework_task_created
    return {"rework_task_id": rework.id}

