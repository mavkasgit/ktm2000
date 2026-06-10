from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.core.database import get_db
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.models.section import Section

router = APIRouter(prefix="/users", tags=["users"])


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
    email: str
    full_name: str
    role: UserRole
    section_id: int | None
    section_ids: list[int] = []
    is_active: bool
    created_at: datetime
    active_login_token: Optional[ActiveTokenOut] = None


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: str
    role: UserRole
    section_id: int | None = None
    section_ids: list[int] | None = None


class UserUpdate(BaseModel):
    username: str | None = None
    full_name: str | None = None
    role: UserRole | None = None
    section_id: int | None = None
    section_ids: list[int] | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    new_password: str


# ─── Endpoints ────────────────────────────────────────────────────────


@router.get("", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role([UserRole.admin])),
) -> list[UserOut]:
    """Получить список всех пользователей (только для admin)."""
    result = await db.execute(select(User).order_by(User.id))
    users = result.scalars().all()
    return [UserOut.model_validate(u) for u in users]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role([UserRole.admin])),
) -> UserOut:
    """Создать нового пользователя (только для admin)."""
    # Check for duplicate username
    existing_username = await db.scalar(select(User).where(User.username == payload.username))
    if existing_username is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with username '{payload.username}' already exists",
        )

    # Check for duplicate email
    existing_email = await db.scalar(select(User).where(User.email == payload.email))
    if existing_email is not None:
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

    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=get_password_hash(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        section_id=section_ids[0] if section_ids else None,
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

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active

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

    user.password_hash = get_password_hash(payload.new_password)
    await db.commit()
