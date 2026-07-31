from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.core.database import get_db
from app.models.user import User, UserRole
from app.schemas.employees import EmployeeListOut, EmployeeOut, SyncPreviewOut
from app.services.hrms_employees import (
    HrmsSyncError,
    list_employees,
    preview_sync,
    sync_employees,
)

router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("", response_model=EmployeeListOut)
async def get_employees(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    sort_by: str = Query(default="name"),
    sort_order: str = Query(default="asc"),
    department: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role([UserRole.admin])),
) -> EmployeeListOut:
    """Получить кешированный список сотрудников HRMS с пагинацией."""
    employees, total, synced_at = await list_employees(
        db,
        limit=limit,
        offset=offset,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        department=department,
    )
    return EmployeeListOut(
        employees=[
            EmployeeOut(
                id=e.id,
                hrms_id=e.hrms_id,
                name=e.name,
                tab_number=e.tab_number,
                position=e.position,
                department=e.department,
            )
            for e in employees
        ],
        total=total,
        limit=limit,
        offset=offset,
        synced_at=synced_at,
    )


@router.post("/sync", response_model=EmployeeListOut)
async def post_sync(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role([UserRole.admin])),
) -> EmployeeListOut:
    """Синхронизировать кеш сотрудников из HRMS."""
    try:
        employees, synced_at = await sync_employees(db)
    except HrmsSyncError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return EmployeeListOut(
        employees=[
            EmployeeOut(
                id=e.id,
                hrms_id=e.hrms_id,
                name=e.name,
                tab_number=e.tab_number,
                position=e.position,
                department=e.department,
            )
            for e in employees
        ],
        total=len(employees),
        limit=len(employees),
        offset=0,
        synced_at=synced_at,
    )


@router.post("/sync/preview", response_model=SyncPreviewOut)
async def post_sync_preview(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role([UserRole.admin])),
) -> SyncPreviewOut:
    """Предпросмотр синхронизации: diff БЕЗ записи в БД."""
    try:
        preview = await preview_sync(db)
    except HrmsSyncError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return preview
