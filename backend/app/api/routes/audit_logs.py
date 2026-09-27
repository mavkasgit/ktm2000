from datetime import datetime
from typing import Dict, List, Any

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import READER_ROLES, require_role, get_current_user, get_db
from app.core.sorting import SortClause, apply_sort, parse_sort
from app.models.audit_log import AuditLog
from app.models.user import User
from app.models.work_task import WorkTask
from app.services.audit_log_service import log_action

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])

# Единая таблица «поле ?sort= → выражение SQL» для логов аудита. Она же —
# источник истины для валидации: apply_sort отвечает 400 на поле, которого
# здесь нет, поэтому поле нельзя объявить, но не резолвить (или наоборот).
_AUDIT_SORT_COLUMNS: dict[str, object] = {
    "id": AuditLog.id,
    "created_at": AuditLog.created_at,
    "status": AuditLog.status,
    "section_name": AuditLog.section_name,
    "product_sku": AuditLog.product_sku,
    "action": AuditLog.action,
    "entity_type": AuditLog.entity_type,
    "user_name": AuditLog.user_name,
}

# Курируемый набор полей сортировки: контракт для фронта. Валидация идёт по
# _AUDIT_SORT_COLUMNS, поэтому набор выводится из таблицы, а не живёт отдельно.
AUDIT_SORT_FIELDS = frozenset(_AUDIT_SORT_COLUMNS)

# Поля, где значение может быть пустым: необязательные колонки лога. Пустые
# уходят в конец в ЛЮБОМ направлении (в Postgres DESC по умолчанию ставит NULL
# первым — оператор кликнул «спустить», а пустые уехали наверх).
_AUDIT_SORT_NULLS_LAST_FIELDS = (
    "section_name",
    "product_sku",
    "action",
    "entity_type",
    "user_name",
)

# Порядок по умолчанию — свежие сверху. Второй ключ (id) обязателен и повторяет
# направление: created_at — это now(), а в Postgres now() это метка времени
# ТРАНЗАКЦИИ, поэтому все логи одного запроса имеют одинаковую метку, и без
# id их порядок не определён. Именно id, а не «равных нет»: направление
# tiebreaker здесь наблюдаемо, и asc сломал бы порядок логов внутри пачки.
_AUDIT_SORT_DEFAULT_CLAUSES = (
    SortClause("created_at", "desc"),
    SortClause("id", "desc"),
)


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
    sort: str | None = Query(
        default=None,
        description="Comma-separated sort rules: field:asc|desc, e.g. created_at:desc,section_name:asc",
    ),
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

    # Сортировка разбирается до выполнения запроса: неизвестное поле — 400, а не
    # пустая выборка. Приоритеты слева направо, в конце tiebreaker по PK.
    # Дефолт несёт id вторым ключом (см. _AUDIT_SORT_DEFAULT_CLAUSES), поэтому
    # разбор без параметра сортировки отдаёт исходный порядок, а не перепутанный.
    # Хвост «, id ASC» от apply_sort — несуществующий ключ: id уже стоит вторым
    # и уникален, поэтому третий ключ не может ничего изменить. Он нужен ради
    # единого хелпера, а не ради результата.
    stmt = apply_sort(
        stmt,
        parse_sort(sort, default=_AUDIT_SORT_DEFAULT_CLAUSES[0])
        if sort and sort.strip()
        else list(_AUDIT_SORT_DEFAULT_CLAUSES),
        _AUDIT_SORT_COLUMNS,
        tiebreaker=AuditLog.id,
        nulls_last=_AUDIT_SORT_NULLS_LAST_FIELDS,
    )

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
    log = await log_action(
        db,
        status=payload.status,
        title=payload.title,
        message=payload.message,
        user=current_user,
        section_id=payload.section_id,
        section_name=payload.section_name,
        section_code=payload.section_code,
        task_ids=payload.task_ids,
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
    await db.commit()
    await db.refresh(log)
    return AuditLogOut.model_validate(log)

