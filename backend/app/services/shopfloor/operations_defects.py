from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import Defect, DefectDecision, DefectDecisionType, DefectItem, DefectStatus, DefectType
from app.models.rework_task import ReworkTask, ReworkTaskStatus
from app.seeds.canon.models import DefectDecisionDef
from app.stock import QualityState, Reason, StockCommand, StockCommandService

from .cache import _refresh_section_plan_line_cache
from .common import _check_idempotency, _ensure_positive, _get_defect, _get_task, _to_decimal


def resolve_defect_status(
    decision: DefectDecisionType, defect_decision_map: dict[str, DefectDecisionDef] | None
) -> DefectDecisionDef | None:
    """Данные решения по браку из QualityCanon (ADR-0004, тикет #25).

    Оператор (диспетчеризация stock-операций) остаётся в сервисе; конкретная
    пара (status, reason) — данные конфигурации завода. Неизвестное решение
    возвращает None → сервис оставляет defect в decision_required.

    Карта решений передаётся из composition root (ADR-0007); сервис не
    резолвит PlantConfig сам.
    """
    if defect_decision_map is None:
        return None
    return defect_decision_map.get(decision.value)

async def create_defect(
    db: AsyncSession,
    *,
    task_id: int | None = None,
    product_id: int | None = None,
    section_id: int | None = None,
    route_stage_id: int | None = None,
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
    await db.flush()

    # Запись лога аудита (регистрация брака)
    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction, AuditEntityType
    from app.models.section import Section
    from app.models.product import Product
    
    section = await db.get(Section, sect_id)
    product = await db.get(Product, prod_id)
    
    await log_action(
        db,
        status="success",
        title="Регистрация брака",
        message=f"Зарегистрирован брак на участке \"{section.name if section else ''}\" (арт. {product.sku if product else ''}). Количество: {quantity} шт. Причина: {reason or '—'}",
        user_id=actor_id,
        section_id=sect_id,
        section_name=section.name if section else None,
        section_code=section.code if section else None,
        task_ids=[task_id] if task_id else [],
        product_sku=product.sku if product else None,
        qty_text=str(quantity),
        comment=comment,
        action=AuditAction.CREATE,
        entity_type=AuditEntityType.DEFECT,
        entity_id=defect.id,
        changes={"before": None, "after": {"status": "decision_required", "quantity": str(quantity), "reason": reason}},
    )

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
    defect_decision_map: dict[str, DefectDecisionDef] | None = None,
    scrap_section_type: str | None = None,
    scrap_code: str | None = None,
    scrap_name: str | None = None,
    scrap_sort_order: int | None = None,
) -> dict:
    defect = await _get_defect(db, defect_id)
    task = await _get_task(db, defect.task_id) if defect.task_id is not None else None

    if decision_type in {DefectDecisionType.rework_current, DefectDecisionType.return_previous} and task is None:
        raise ValueError("Rework decisions require an associated work task")

    if idempotency_key:
        existing = await _check_idempotency(db, idempotency_key=idempotency_key, entity_type=DefectDecision)
        if existing is not None:
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

    svc = StockCommandService()
    rework_task_id: int | None = None
    from app.models.section import Section as _Section

    # ADR-0004/0007: карта решений (status, reason) — данные канона, передаются
    # из composition root; сервис не резолвит PlantConfig сам.
    _decision_def = resolve_defect_status(decision_type, defect_decision_map)
    if _decision_def is not None:
        _decision_status = DefectStatus(_decision_def.status)
        _decision_reason = Reason(_decision_def.reason) if _decision_def.reason else None
    else:
        _decision_status = DefectStatus.decision_required
        _decision_reason = None

    if decision_type == DefectDecisionType.scrap:
        # ADR-0007: данные SCRAP-секции из composition root
        if scrap_section_type is None or scrap_code is None or scrap_name is None or scrap_sort_order is None:
            raise ValueError("scrap policy data is required for scrap decision")
        from_sec_id = task.section_id if task else defect.section_id
        # Find or auto-create scrap location
        scrap_loc = await db.scalar(
            select(_Section.id).where(_Section.type == scrap_section_type).limit(1)
        )
        if scrap_loc is None:
            scrap_sec = _Section(
                code=scrap_code, name=scrap_name,
                type=scrap_section_type, is_active=True, sort_order=scrap_sort_order,
            )
            db.add(scrap_sec)
            await db.flush()
            scrap_loc = scrap_sec.id
        to_sec_id = scrap_loc

        tx = await svc.record(db, StockCommand(
            product_id=task.product_id if task else defect.product_id,
            from_location_id=from_sec_id,
            to_location_id=to_sec_id,
            quantity=quantity,
            reason=_decision_reason or Reason.SCRAP,
            quality_state=QualityState.GOOD,
            to_quality_state=QualityState.SCRAP,
            task_id=task.id if task else None,
            source_ref=f"defect:{defect.id}:decision:scrap",
            idempotency_key=idempotency_key,
            comment=comment,
            created_by=actor_id,
        ))
        defect.stock_transaction_id = tx.id
        defect.status = _decision_status

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

        if decision_type == DefectDecisionType.rework_current:
            to_loc = target_section_id or task.section_id
            # DB constraint prevents same from/to — use None for same-location
            if to_loc == task.section_id:
                to_loc = None
            tx = await svc.record(db, StockCommand(
                product_id=task.product_id,
                from_location_id=task.section_id,
                to_location_id=to_loc,
                quantity=quantity,
                reason=_decision_reason or Reason.REWORK,
                quality_state=QualityState.GOOD,
                to_quality_state=QualityState.REWORK,
                task_id=task.id,
                source_ref=f"defect:{defect.id}:decision:rework",
                idempotency_key=f"{idempotency_key}:rework" if idempotency_key else None,
                comment=comment,
                created_by=actor_id,
            ))
            defect.stock_transaction_id = tx.id
        else:
            # return_to_previous: find previous route stage section
            to_loc = target_section_id
            if to_loc is None and task.route_stage_id is not None:
                from app.models.route import RouteStage
                prev_stage = await db.scalar(
                    select(RouteStage).where(
                        RouteStage.route_id == (
                            select(RouteStage.route_id).where(RouteStage.id == task.route_stage_id)
                        ).scalar_subquery(),
                        RouteStage.sequence < (
                            select(RouteStage.sequence).where(RouteStage.id == task.route_stage_id)
                        ).scalar_subquery(),
                    ).order_by(RouteStage.sequence.desc()).limit(1)
                )
                if prev_stage is not None:
                    to_loc = prev_stage.section_id
            if to_loc is None:
                to_loc = task.section_id
            # DB constraint prevents same from/to
            if to_loc == task.section_id:
                to_loc = None

            tx = await svc.record(db, StockCommand(
                product_id=task.product_id,
                from_location_id=task.section_id,
                to_location_id=to_loc,
                quantity=quantity,
                reason=_decision_reason or Reason.RETURN_TO_PREVIOUS,
                task_id=task.id,
                source_ref=f"defect:{defect.id}:decision:return_previous",
                idempotency_key=f"{idempotency_key}:return" if idempotency_key else None,
                comment=comment,
                created_by=actor_id,
            ))
            defect.stock_transaction_id = tx.id

        defect.status = _decision_status

    elif decision_type == DefectDecisionType.accept_with_deviation:
        if task:
            tx = await svc.record(db, StockCommand(
                product_id=task.product_id,
                from_location_id=None,
                to_location_id=task.section_id,
                quantity=quantity,
                reason=_decision_reason or Reason.COMPLETE,
                quality_state=QualityState.GOOD,
                task_id=task.id,
                source_ref=f"defect:{defect.id}:decision:accept_deviation",
                idempotency_key=f"{idempotency_key}:complete" if idempotency_key else None,
                comment=comment,
                created_by=actor_id,
            ))
            defect.stock_transaction_id = tx.id
        defect.status = _decision_status

    else:
        defect.status = _decision_status

    if task:
        await _refresh_section_plan_line_cache(db, task.section_plan_line_id)

    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction, AuditEntityType
    from app.models.section import Section
    from app.models.product import Product

    section = await db.get(Section, defect.section_id)
    product = await db.get(Product, defect.product_id)

    await log_action(
        db,
        status="success",
        title="Решение по браку",
        message=f"Принято решение по браку #{defect.id} (арт. {product.sku if product else ''}) на участке \"{section.name if section else ''}\": {decision_type.value}. Количество: {quantity} шт.",
        user_id=actor_id,
        section_id=defect.section_id,
        section_name=section.name if section else None,
        section_code=section.code if section else None,
        task_ids=[defect.task_id] if defect.task_id else [],
        product_sku=product.sku if product else None,
        qty_text=str(quantity),
        comment=comment,
        action=AuditAction.UPDATE,
        entity_type=AuditEntityType.DEFECT_DECISION,
        entity_id=decision.id,
        changes={"before": {"status": "decision_required"}, "after": {"status": defect.status.value, "decision": decision_type.value}},
    )

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
    await db.flush()

    # Запись лога аудита (задача на переделку)
    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction, AuditEntityType
    from app.models.section import Section
    from app.models.product import Product
    
    section = await db.get(Section, section_id)
    product = await db.get(Product, source_task.product_id)
    
    await log_action(
        db,
        status="success",
        title="Создание задачи на доработку",
        message=f"Создана задача на переделку #{rework.id} брака #{defect_id} (арт. {product.sku if product else ''}) на участок \"{section.name if section else ''}\". Количество: {quantity} шт.",
        user_id=actor_id,
        section_id=section_id,
        section_name=section.name if section else None,
        section_code=section.code if section else None,
        task_ids=[source_task_id],
        product_sku=product.sku if product else None,
        qty_text=str(quantity),
        action=AuditAction.CREATE,
        entity_type=AuditEntityType.REWORK_TASK,
        entity_id=rework.id,
        changes={"before": None, "after": {"status": "open", "quantity": str(quantity), "defect_id": defect_id}},
    )

    return {"rework_task_id": rework.id}

