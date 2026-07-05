from datetime import datetime
from typing import Optional
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.core.database import get_db
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.models.section import Section
from app.services.hrms_employees import (
    HrmsSyncError,
    build_hrms_employees_url,
    get_cached_hrms_employees,
    get_hrms_integration_settings,
    list_cached_hrms_employees_paginated,
    sync_hrms_employees_cache,
    test_hrms_connection,
    update_hrms_integration_settings,
)
from app.services.users_queries import get_linked_hrms_ids, list_users_paginated

router = APIRouter(prefix="/users", tags=["users"])

logger = logging.getLogger(__name__)

# ─── Pydantic schemas ────────────────────────────────────────────────


class ActiveTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    token: str
    session_duration_seconds: int | None
    created_at: datetime


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None = None
    full_name: str
    role: UserRole
    section_id: int | None
    section_ids: list[int] = []
    is_active: bool
    tab_number: str | None = None
    hrms_employee_id: int | None = None
    hrms_access_level: str = "no_access"
    created_at: datetime
    active_login_token: Optional[ActiveTokenOut] = None


class UserCreate(BaseModel):
    username: str
    email: EmailStr | None = None
    password: str | None = None
    full_name: str
    role: UserRole
    section_id: int | None = None
    section_ids: list[int] | None = None
    tab_number: str | None = None
    hrms_employee_id: int | None = None
    hrms_access_level: str = "no_access"


class UserUpdate(BaseModel):
    username: str | None = None
    email: EmailStr | None = None
    full_name: str | None = None
    role: UserRole | None = None
    section_id: int | None = None
    section_ids: list[int] | None = None
    is_active: bool | None = None
    tab_number: str | None = None
    hrms_employee_id: int | None = None
    hrms_access_level: str | None = None


class PasswordReset(BaseModel):
    new_password: str | None = None


class HrmsEmployeeOut(BaseModel):
    id: int
    name: str
    tab_number: str | None = None
    position: str | None = None
    department: str | None = None
    is_linked: bool = False


class HrmsEmployeesCacheOut(BaseModel):
    employees: list[HrmsEmployeeOut]
    synced_at: datetime | None = None


class HrmsEmployeesListOut(BaseModel):
    employees: list[HrmsEmployeeOut]
    total: int
    limit: int
    offset: int
    synced_at: datetime | None = None


class UsersListOut(BaseModel):
    users: list[UserOut]
    total: int
    limit: int
    offset: int
    linked_hrms_ids: list[int] = []


class HrmsIntegrationSettingsOut(BaseModel):
    base_url: str | None = None
    api_token: str = "admin"
    employees_url: str | None = None
    updated_at: datetime | None = None


class HrmsIntegrationSettingsUpdate(BaseModel):
    base_url: str | None = None
    api_token: str | None = None


class HrmsConnectionTestIn(BaseModel):
    base_url: str | None = None
    api_token: str | None = None


class HrmsConnectionTestOut(BaseModel):
    request_url: str
    employee_count: int


def _to_hrms_employee_out(employee, *, is_linked: bool = False) -> HrmsEmployeeOut:
    return HrmsEmployeeOut(
        id=employee.hrms_id,
        name=employee.name,
        tab_number=employee.tab_number,
        position=employee.position,
        department=employee.department,
        is_linked=is_linked,
    )


def _to_hrms_employees_cache_out(employees, synced_at: datetime | None) -> HrmsEmployeesCacheOut:
    return HrmsEmployeesCacheOut(
        employees=[_to_hrms_employee_out(employee) for employee in employees],
        synced_at=synced_at,
    )


def _to_hrms_settings_out(settings) -> HrmsIntegrationSettingsOut:
    employees_url = build_hrms_employees_url(settings.base_url) if settings.base_url else None
    return HrmsIntegrationSettingsOut(
        base_url=settings.base_url,
        api_token=settings.api_token,
        employees_url=employees_url,
        updated_at=settings.updated_at,
    )


# ─── Endpoints ────────────────────────────────────────────────────────


@router.get("", response_model=UsersListOut)
async def list_users(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    sort_by: str = Query(default="id"),
    sort_order: str = Query(default="asc"),
    role: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    full_name: str | None = Query(default=None),
    email: str | None = Query(default=None),
    section: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role([UserRole.admin])),
) -> UsersListOut:
    """Получить список пользователей с фильтрацией, сортировкой и пагинацией."""
    users, total = await list_users_paginated(
        db,
        limit=limit,
        offset=offset,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        role=role,
        is_active=is_active,
        full_name=full_name,
        email=email,
        section=section,
    )
    linked_hrms_ids = await get_linked_hrms_ids(db)
    return UsersListOut(
        users=[UserOut.model_validate(user) for user in users],
        total=total,
        limit=limit,
        offset=offset,
        linked_hrms_ids=linked_hrms_ids,
    )


@router.get("/hrms-settings", response_model=HrmsIntegrationSettingsOut)
async def get_hrms_settings(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role([UserRole.admin])),
) -> HrmsIntegrationSettingsOut:
    """Получить настройки подключения к HRMS."""
    settings = await get_hrms_integration_settings(db)
    return _to_hrms_settings_out(settings)


@router.put("/hrms-settings", response_model=HrmsIntegrationSettingsOut)
async def save_hrms_settings(
    payload: HrmsIntegrationSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role([UserRole.admin])),
) -> HrmsIntegrationSettingsOut:
    """Сохранить настройки подключения к HRMS."""
    try:
        settings = await update_hrms_integration_settings(
            db,
            base_url=payload.base_url,
            api_token=payload.api_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_hrms_settings_out(settings)


@router.post("/hrms-settings/test", response_model=HrmsConnectionTestOut)
async def test_hrms_settings(
    payload: HrmsConnectionTestIn,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role([UserRole.admin])),
) -> HrmsConnectionTestOut:
    """Проверить доступность HRMS по указанному или сохранённому адресу."""
    try:
        if payload.base_url is not None or payload.api_token is not None:
            await update_hrms_integration_settings(
                db,
                base_url=payload.base_url,
                api_token=payload.api_token,
            )
        result = await test_hrms_connection(
            db,
            base_url=payload.base_url,
            api_token=payload.api_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HrmsSyncError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return HrmsConnectionTestOut(**result)


@router.get("/employees", response_model=HrmsEmployeesListOut)
async def list_employees(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    sort_by: str = Query(default="name"),
    sort_order: str = Query(default="asc"),
    department: str | None = Query(default=None),
    linked: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role([UserRole.admin])),
) -> HrmsEmployeesListOut:
    """Получить кешированный список сотрудников HRMS с пагинацией."""
    rows, total, synced_at = await list_cached_hrms_employees_paginated(
        db,
        limit=limit,
        offset=offset,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        department=department,
        linked=linked,
    )
    return HrmsEmployeesListOut(
        employees=[
            _to_hrms_employee_out(employee, is_linked=row_is_linked)
            for employee, row_is_linked in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
        synced_at=synced_at,
    )


@router.post("/employees/sync", response_model=HrmsEmployeesCacheOut)
async def sync_employees(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role([UserRole.admin])),
) -> HrmsEmployeesCacheOut:
    """Синхронизировать кеш сотрудников HRMS из внешнего сервиса."""
    try:
        employees, synced_at = await sync_hrms_employees_cache(db)
    except HrmsSyncError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return _to_hrms_employees_cache_out(employees, synced_at)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role([UserRole.admin])),
) -> UserOut:
    """Создать нового пользователя (только для admin)."""
    # 1. Если передан hrms_employee_id или tab_number, проверяем, существует ли уже такой сотрудник в системе
    existing_user = None
    if payload.hrms_employee_id:
        result = await db.execute(select(User).where(User.hrms_employee_id == payload.hrms_employee_id))
        existing_user = result.scalars().first()
    elif payload.tab_number:
        result = await db.execute(select(User).where(User.tab_number == payload.tab_number))
        existing_user = result.scalars().first()

    if existing_user and existing_user.role != UserRole.operator:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Сотрудник уже связан с активным пользователем '{existing_user.username}' с ролью '{existing_user.role.value if hasattr(existing_user.role, 'value') else str(existing_user.role)}'",
        )

    # 2. Проверка уникальности логина
    existing_username = await db.scalar(select(User).where(User.username == payload.username))
    if existing_username is not None:
        # Если логин занят другим пользователем (не тем, кого мы мержим)
        if not existing_user or existing_username.id != existing_user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"User with username '{payload.username}' already exists",
            )

    # 3. Проверка уникальности email
    if payload.email:
        existing_email = await db.scalar(select(User).where(User.email == payload.email))
        if existing_email is not None:
            # Если email занят другим пользователем (не тем, кого мы мержим)
            if not existing_user or existing_email.id != existing_user.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"User with email '{payload.email}' already exists",
                )

    section_ids = []
    if payload.section_ids is not None:
        section_ids = payload.section_ids
    elif payload.section_id is not None:
        section_ids = [payload.section_id]

    sections_list = []
    if section_ids:
        sections_res = await db.execute(select(Section).where(Section.id.in_(section_ids)))
        sections_list = list(sections_res.scalars().all())

    if existing_user:
        # Слияние/продвижение: обновляем существующего synced operator пользователя
        existing_user.username = payload.username
        existing_user.email = payload.email
        existing_user.password_hash = get_password_hash(payload.password) if payload.password else ""
        existing_user.full_name = payload.full_name
        existing_user.role = payload.role
        existing_user.is_active = True
        existing_user.section_id = section_ids[0] if section_ids else None
        existing_user.hrms_access_level = payload.hrms_access_level
        if payload.hrms_employee_id is not None:
            existing_user.hrms_employee_id = payload.hrms_employee_id
        if payload.tab_number is not None:
            existing_user.tab_number = payload.tab_number
        
        if sections_list:
            existing_user.sections = sections_list
        else:
            existing_user.sections = []

        await db.commit()
        await db.refresh(existing_user)
        return UserOut.model_validate(existing_user)

    # Создание полностью новой записи
    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=get_password_hash(payload.password) if payload.password else "",
        full_name=payload.full_name,
        role=payload.role,
        section_id=section_ids[0] if section_ids else None,
        tab_number=payload.tab_number,
        hrms_employee_id=payload.hrms_employee_id,
        hrms_access_level=payload.hrms_access_level,
        is_active=True,
    )
    if sections_list:
        user.sections = sections_list

    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role([UserRole.admin])),
) -> UserOut:
    """Обновить пользователя (только для admin). Нельзя деактивировать или менять роль себе."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Prevent admin from deactivating themselves
    if payload.is_active is False and user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account",
        )

    # Prevent admin from changing their own role
    if payload.role is not None and user.id == current_user.id and payload.role != current_user.role:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own role",
        )

    if payload.username is not None and payload.username != user.username:
        existing = await db.scalar(select(User).where(User.username == payload.username))
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"User with username '{payload.username}' already exists",
            )
        user.username = payload.username

    if "email" in payload.model_fields_set:
        if payload.email is None or payload.email == "" or payload.email == "none":
            user.email = None
        elif payload.email != user.email:
            dup = await db.scalar(select(User).where(User.email == payload.email))
            if dup is not None and dup.id != user.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"User with email '{payload.email}' already exists",
                )
            user.email = payload.email

    # Изменение табельного номера
    if "tab_number" in payload.model_fields_set:
        if payload.tab_number is None or payload.tab_number == "" or payload.tab_number == "none":
            user.tab_number = None
        else:
            user.tab_number = payload.tab_number

    # Изменение ID сотрудника HRMS
    if "hrms_employee_id" in payload.model_fields_set:
        if payload.hrms_employee_id is None or payload.hrms_employee_id == 0:
            user.hrms_employee_id = None
        elif payload.hrms_employee_id != user.hrms_employee_id:
            # Проверяем на дубликат hrms_employee_id
            dup = await db.scalar(select(User).where(User.hrms_employee_id == payload.hrms_employee_id))
            if dup is not None and dup.id != user.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Сотрудник с ID '{payload.hrms_employee_id}' уже привязан к другому пользователю",
                )
            user.hrms_employee_id = payload.hrms_employee_id

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.hrms_access_level is not None:
        user.hrms_access_level = payload.hrms_access_level

    # Асинхронно подгружаем отношение sections для предотвращения MissingGreenlet
    await db.refresh(user, attribute_names=["sections"])

    if payload.section_ids is not None:
        if payload.section_ids:
            sections_res = await db.execute(select(Section).where(Section.id.in_(payload.section_ids)))
            user.sections = list(sections_res.scalars().all())
            user.section_id = payload.section_ids[0]
        else:
            user.sections = []
            user.section_id = None
    elif payload.section_id is not None:
        user.section_id = payload.section_id
        sections_res = await db.execute(select(Section).where(Section.id == payload.section_id))
        user.sections = list(sections_res.scalars().all())

    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    user_id: int,
    payload: PasswordReset,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role([UserRole.admin])),
) -> None:
    """Сброс пароля пользователя администратором."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.password_hash = get_password_hash(payload.new_password) if payload.new_password else ""
    await db.commit()
