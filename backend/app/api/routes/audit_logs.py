from datetime import datetime
from typing import Dict, List, Any

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import READER_ROLES, require_role, get_current_user, get_db
from app.models.audit_log import AuditLog
from app.models.user import User
from app.models.work_task import WorkTask

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])

AUDIT_SORT_FIELDS = frozenset({
    "created_at",
    "status",
    "section_name",
    "product_sku",
    "action",
    "entity_type",
    "user_name",
})


def _apply_audit_log_filters(
    stmt,
    *,
    status: str | None = None,
    section_id: int | None = None,
    section_name: str | None = None,
    product_sku: str | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    user_name: str | None = None,
    search: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    if status:
        stmt = stmt.where(AuditLog.status == status)
    if section_id:
        stmt = stmt.where(AuditLog.section_id == section_id)
    if section_name:
        stmt = stmt.where(AuditLog.section_name.ilike(f"%{section_name}%"))
    if product_sku:
        stmt = stmt.where(AuditLog.product_sku.ilike(f"%{product_sku}%"))
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"%{action}%"))
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type.ilike(f"%{entity_type}%"))
    if user_name:
        stmt = stmt.where(AuditLog.user_name.ilike(f"%{user_name}%"))
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= date_to)
    if search:
        search_like = f"%{search}%"
        stmt = stmt.where(
            or_(
                AuditLog.message.ilike(search_like),
                AuditLog.title.ilike(search_like),
                AuditLog.user_name.ilike(search_like),
                AuditLog.product_sku.ilike(search_like),
            )
        )
    return stmt


class AuditLogOut(BaseModel):
    id: int
    created_at: datetime
    user_id: int | None
    user_name: str | None
    status: str
    title: str
    message: str
    section_id: int | None
    section_name: str | None
    section_code: str | None
    task_ids: str | None
    product_sku: str | None
    operation_name: str | None
    qty_text: str | None
    comment: str | None
    error_details: str | None
    action: str | None
    entity_type: str | None
    entity_id: int | None
    changes: Dict[str, Any] | None

    class Config:
        from_attributes = True


class AuditLogCreate(BaseModel):
    status: str
    title: str
    message: str
    section_id: int | None = None
    section_name: str | None = None
    section_code: str | None = None
    task_ids: List[int] | None = None
    product_sku: str | None = None
    operation_name: str | None = None
    qty_text: str | None = None
    comment: str | None = None
    error_details: str | None = None
    action: str | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    changes: Dict[str, Any] | None = None


class AuditLogsResponse(BaseModel):
    items: List[AuditLogOut]
    task_statuses: Dict[int, str]
    counts: Dict[str, int]
    total: int


@router.get("", response_model=AuditLogsResponse)
async def get_audit_logs(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    section_id: int | None = Query(None),
    section_name: str | None = Query(None),
    product_sku: str | None = Query(None),
    action: str | None = Query(None),
    entity_type: str | None = Query(None),
    user_name: str | None = Query(None),
    search: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    sort_by: str | None = Query("created_at"),
    sort_order: str | None = Query("desc"),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> AuditLogsResponse:
    """Получить список логов аудита с фильтрацией, пагинацией и сортировкой."""
    stmt = _apply_audit_log_filters(
        select(AuditLog),
        status=status,
        section_id=section_id,
        section_name=section_name,
        product_sku=product_sku,
        action=action,
        entity_type=entity_type,
        user_name=user_name,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )

    # Подсчитываем общее количество
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # Сортировка на сервере (whitelist + fallback created_at)
    resolved_sort_by = sort_by if sort_by in AUDIT_SORT_FIELDS else "created_at"
    order_column = AuditLog.created_at
    if resolved_sort_by == "status":
        order_column = AuditLog.status
    elif resolved_sort_by == "section_name":
        order_column = AuditLog.section_name
    elif resolved_sort_by == "product_sku":
        order_column = AuditLog.product_sku
    elif resolved_sort_by == "action":
        order_column = AuditLog.action
    elif resolved_sort_by == "entity_type":
        order_column = AuditLog.entity_type
    elif resolved_sort_by == "user_name":
        order_column = AuditLog.user_name

    if sort_order == "asc":
        stmt = stmt.order_by(order_column.asc(), AuditLog.id.asc())
    else:
        stmt = stmt.order_by(order_column.desc(), AuditLog.id.desc())

    # Выполняем пагинацию
    stmt = stmt.limit(limit).offset(offset)
    logs = (await db.execute(stmt)).scalars().all()

    # Сбор всех ID задач для проверки их существования в БД
    all_task_ids = set()
    for log in logs:
        if log.task_ids:
            for tid_str in log.task_ids.split(","):
                try:
                    all_task_ids.add(int(tid_str.strip()))
                except ValueError:
                    pass

    task_statuses = {}
    if all_task_ids:
        # Проверяем какие задачи существуют
        exist_stmt = select(WorkTask.id).where(WorkTask.id.in_(list(all_task_ids)))
        existing_ids = set((await db.execute(exist_stmt)).scalars().all())
        for tid in all_task_ids:
            task_statuses[tid] = "active" if tid in existing_ids else "deleted"

    # Вычисляем counts по статусам (учитывая column/search фильтры, но не по самому статусу)
    counts_base_stmt = _apply_audit_log_filters(
        select(AuditLog.status, func.count(AuditLog.id)).select_from(AuditLog),
        section_id=section_id,
        section_name=section_name,
        product_sku=product_sku,
        action=action,
        entity_type=entity_type,
        user_name=user_name,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )
    counts_base_stmt = counts_base_stmt.group_by(AuditLog.status)
    counts_rows = (await db.execute(counts_base_stmt)).all()

    counts = {"all": 0, "success": 0, "error": 0, "info": 0}
    for status_val, cnt in counts_rows:
        if status_val in counts:
            counts[status_val] = cnt
            counts["all"] += cnt

    return AuditLogsResponse(
        items=[AuditLogOut.model_validate(log) for log in logs],
        task_statuses=task_statuses,
        counts=counts,
        total=total,
    )


@router.get("/entity/{entity_type}/{entity_id}", response_model=List[AuditLogOut])
async def get_entity_audit_logs(
    entity_type: str,
    entity_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> List[AuditLogOut]:
    """Получить историю изменений (Timeline) для конкретной сущности."""
    stmt = (
        select(AuditLog)
        .where(AuditLog.entity_type == entity_type)
        .where(AuditLog.entity_id == entity_id)
        .order_by(AuditLog.created_at.asc())
    )
    logs = (await db.execute(stmt)).scalars().all()
    return [AuditLogOut.model_validate(log) for log in logs]


@router.post("", response_model=AuditLogOut)
async def create_audit_log(
    payload: AuditLogCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AuditLogOut:
    """Создать новую запись в журнале аудита."""
    task_ids_str = None
    if payload.task_ids:
        task_ids_str = ",".join(map(str, payload.task_ids))

    log = AuditLog(
        user_id=current_user.id,
        user_name=current_user.full_name,
        status=payload.status,
        title=payload.title,
        message=payload.message,
        section_id=payload.section_id,
        section_name=payload.section_name,
        section_code=payload.section_code,
        task_ids=task_ids_str,
        product_sku=payload.product_sku,
        operation_name=payload.operation_name,
        qty_text=payload.qty_text,
        comment=payload.comment,
        error_details=payload.error_details,
        action=payload.action,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        changes=payload.changes,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return AuditLogOut.model_validate(log)

