from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.core.security import get_password_hash
from app.models.user import User, UserRole

router = APIRouter(prefix="/integration", tags=["integration"])


class SyncEmployeePayload(BaseModel):
    employee_id: int
    tab_number: str | None = None
    name: str
    position: str | None = None
    department: str | None = None
    is_deleted: bool = False


async def verify_integration_token(
    x_integration_token: str | None = Header(None, alias="X-Integration-Token")
):
    if not x_integration_token or x_integration_token != settings.INTEGRATION_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing integration token",
        )


@router.post("/sync-employee", status_code=status.HTTP_200_OK)
async def sync_employee(
    payload: SyncEmployeePayload,
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(verify_integration_token),
) -> dict:
    """
    Синхронизирует сотрудника из HRMS.
    Создает пользователя, если его нет, иначе обновляет его данные.
    """
    if not payload.employee_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="employee_id is required",
        )

    # 1. Поиск существующего пользователя по ID сотрудника HRMS
    result = await db.execute(
        select(User).where(User.hrms_employee_id == payload.employee_id)
    )
    user = result.scalars().first()

    # 2. Обратная совместимость: если не найден по ID, но передан tab_number
    if not user and payload.tab_number:
        result = await db.execute(
            select(User).where(User.tab_number == payload.tab_number)
        )
        user = result.scalars().first()
        if user:
            # Связываем существующего по ID
            user.hrms_employee_id = payload.employee_id

    if user:
        # Обновляем существующего
        user.full_name = payload.name
        user.position = payload.position
        user.department = payload.department
        user.is_active = not payload.is_deleted
        if payload.tab_number is not None:
            user.tab_number = payload.tab_number
    else:
        # Создаем нового пользователя
        username = f"emp_{payload.employee_id}"
        email = f"emp_{payload.employee_id}@ktm2000.local"

        # Проверяем уникальность username / email
        username_exists = await db.scalar(select(User).where(User.username == username))
        email_exists = await db.scalar(select(User).where(User.email == email))

        if username_exists or email_exists:
            # Если возник конфликт, добавим суффикс
            import uuid
            suffix = uuid.uuid4().hex[:6]
            username = f"{username}_{suffix}"
            email = f"emp_{payload.employee_id}_{suffix}@ktm2000.local"

        user = User(
            hrms_employee_id=payload.employee_id,
            tab_number=payload.tab_number,
            username=username,
            email=email,
            password_hash=get_password_hash(f"pwd_{payload.employee_id}_{settings.SECRET_KEY[:10]}"),
            full_name=payload.name,
            role=UserRole.operator,  # Роль по умолчанию для цеховых работников
            position=payload.position,
            department=payload.department,
            is_active=not payload.is_deleted,
        )
        db.add(user)

    await db.commit()
    await db.refresh(user)

    return {
        "status": "success",
        "user_id": user.id,
        "username": user.username,
        "is_active": user.is_active,
    }
