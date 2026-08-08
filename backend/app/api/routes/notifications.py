from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.internal_notification import InternalNotification
from app.models.user import User

router = APIRouter(prefix="/internal-notifications", tags=["notifications"])


class InternalNotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    notification_type: str
    title: str
    text: str | None
    entity_type: str | None
    entity_id: int | None
    created_at: datetime
    read_at: datetime | None
    closed_at: datetime | None


class InternalNotificationListOut(BaseModel):
    items: list[InternalNotificationOut]
    total: int
    unread_count: int


def _scoped_user_filter(user_id: int):
    """Общие (user_id IS NULL) + персональные текущего пользователя."""
    return or_(
        InternalNotification.user_id.is_(None),
        InternalNotification.user_id == user_id,
    )


async def _get_scoped_notification(
    db: AsyncSession,
    notification_id: int,
    user_id: int,
) -> InternalNotification:
    """Уведомление, доступное текущему пользователю.

    Отсутствующее или чужое персональное → 404 (не раскрывает существование).
    """
    notification = await db.scalar(
        select(InternalNotification).where(
            InternalNotification.id == notification_id,
            _scoped_user_filter(user_id),
        )
    )
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Уведомление не найдено",
        )
    return notification


@router.get("", response_model=InternalNotificationListOut)
async def list_internal_notifications(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    only_unclosed: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InternalNotificationListOut:
    """Список общих и персональных уведомлений текущего пользователя.

    Продюсеров событий пока нет — таблица пустая, колокольчик в UI получает
    пустой список без ошибок. Пагинация limit/offset, сортировка по created_at.
    """
    scope = _scoped_user_filter(current_user.id)

    base = select(InternalNotification).where(scope)
    if only_unclosed:
        base = base.where(InternalNotification.closed_at.is_(None))

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0

    # unread_count — непрочитанные (read_at IS NULL) среди активных (closed_at IS NULL)
    unread_stmt = (
        select(func.count())
        .select_from(InternalNotification)
        .where(scope)
        .where(InternalNotification.closed_at.is_(None))
        .where(InternalNotification.read_at.is_(None))
    )
    unread_count = (await db.execute(unread_stmt)).scalar() or 0

    items_stmt = base.order_by(
        InternalNotification.created_at.desc(),
        InternalNotification.id.desc(),
    )
    items = (await db.execute(items_stmt.limit(limit).offset(offset))).scalars().all()

    return InternalNotificationListOut(
        items=[InternalNotificationOut.model_validate(item) for item in items],
        total=total,
        unread_count=unread_count,
    )


@router.post("/{notification_id}/read", response_model=InternalNotificationOut)
async def mark_notification_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InternalNotificationOut:
    """Пометить уведомление прочитанным (идемпотентно).

    Повторный вызов не меняет read_at. Чужое персональное → 404.
    """
    notification = await _get_scoped_notification(db, notification_id, current_user.id)
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        await db.commit()
    return InternalNotificationOut.model_validate(notification)


@router.post("/{notification_id}/close", response_model=InternalNotificationOut)
async def close_notification(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InternalNotificationOut:
    """Закрыть уведомление (идемпотентно): read_at и closed_at.

    Повторный вызов не меняет даты. Чужое персональное → 404.
    """
    notification = await _get_scoped_notification(db, notification_id, current_user.id)
    now = datetime.now(UTC)
    if notification.read_at is None:
        notification.read_at = now
    if notification.closed_at is None:
        notification.closed_at = now
    await db.commit()
    return InternalNotificationOut.model_validate(notification)
