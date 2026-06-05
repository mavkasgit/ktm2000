from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import Defect, DefectDecision, DefectDecisionType, DefectItem, DefectStatus, DefectType
from app.models.movement import Movement, MovementType
from app.models.rework_task import ReworkTask, ReworkTaskStatus

from .cache import _refresh_section_plan_line_cache, _refresh_task_cache
from .common import _check_idempotency, _ensure_positive, _get_defect, _get_task, _get_user_snapshot_name, _to_decimal

async def create_defect(
    db: AsyncSession,
    *,
    task_id: int | None = None,
    product_id: int | None = None,
    section_id: int | None = None,
    route_stage_id: int | None = None,
    spg_remainder_id: int | None = None,
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

    quantity = _to_decimal(quantity)
    _ensure_positive(quantity, "quantity")

    if task_id is not None:
        task = await _get_task(db, task_id)
        prod_id = task.product_id
        sect_id = task.section_id
    else:
        if spg_remainder_id is not None:
            from app.models.spg_remainder import SpgRemainder
            remainder = await db.get(SpgRemainder, spg_remainder_id)
            if not remainder:
                raise ValueError(f"SpgRemainder {spg_remainder_id} not found")
            prod_id = remainder.product_id
            if route_stage_id is None:
                route_stage_id = remainder.route_stage_id
        else:
            if product_id is None:
                raise ValueError("product_id is required for manual defect registration")
            prod_id = product_id

        if route_stage_id is not None:
            from app.models.route import RouteStage
            stage = await db.get(RouteStage, route_stage_id)
            if not stage:
                raise ValueError(f"RouteStage {route_stage_id} not found")
            sect_id = stage.section_id
        else:
            if section_id is None:
                raise ValueError("section_id or route_stage_id is required for manual defect registration")
            sect_id = section_id

    defect = Defect(
        product_id=prod_id,
        section_id=sect_id,
        task_id=task_id,
        route_stage_id=route_stage_id,
        spg_remainder_id=spg_remainder_id,
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
    task = await _get_task(db, defect.task_id) if defect.task_id is not None else None

    if decision_type in {DefectDecisionType.rework_current, DefectDecisionType.return_previous} and task is None:
        raise ValueError("Rework decisions require an associated work task")

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
        actor_name = await _get_user_snapshot_name(db, actor_id)
        
        prod_id = task.product_id if task else defect.product_id
        t_id = task.id if task else None
        spl_id = task.section_plan_line_id if task else None
        from_sec_id = task.section_id if task else defect.section_id
        to_sec_id = task.section_id if task else defect.section_id

        movement = Movement(
            product_id=prod_id,
            task_id=t_id,
            section_plan_line_id=spl_id,
            from_section_id=from_sec_id,
            to_section_id=to_sec_id,
            movement_type=MovementType.scrap,
            quantity=quantity,
            reason=reason,
            comment=comment,
            created_by=actor_id,
            created_by_user_name=actor_name,
        )
        db.add(movement)

        # Deduct from SpgRemainder if associated
        if defect.spg_remainder_id is not None:
            from app.models.spg_remainder import SpgRemainder
            from sqlalchemy import func
            remainder = await db.get(SpgRemainder, defect.spg_remainder_id)
            if remainder:
                remainder.remainder_quantity -= quantity
                if remainder.remainder_quantity <= 0:
                    remainder.consumed_at = func.now()

        defect.status = DefectStatus.scrapped
    elif decision_type in {DefectDecisionType.rework_current, DefectDecisionType.return_previous}:
        assert task is not None
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

    if task:
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

