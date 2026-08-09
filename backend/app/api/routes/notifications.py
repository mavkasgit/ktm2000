from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import get_current_user, get_db
from app.models.notification import Notification, UserNotificationState
from app.models.user import User

router = APIRouter(prefix="/internal-notifications", tags=["notifications"])


class NotificationOut(BaseModel):
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


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    total: int
    unread_count: int


def _scoped_user_filter(user_id: int):
    """Общие (user_id IS NULL) + персональные текущего пользователя."""
    return or_(
        Notification.user_id.is_(None),
        Notification.user_id == user_id,
    )


def _state_join_condition(
    state: type[UserNotificationState],
    user_id: int,
):
    """LEFT JOIN к состоянию уведомления текущего пользователя.

    Отсутствие state-записи = «непрочитано и активно» (ленивое создание).
    """
    return and_(
        state.notification_id == Notification.id,
        state.user_id == user_id,
    )


def _active_condition(state: type[UserNotificationState]):
    """Активное уведомление: нет записи состояния или она не закрыта."""
    return or_(state.id.is_(None), state.closed_at.is_(None))


def _unread_condition(state: type[UserNotificationState]):
    """Непрочитанное: нет записи состояния или она без read_at."""
    return or_(state.id.is_(None), state.read_at.is_(None))


def _to_out(notification: Notification, state: UserNotificationState | None) -> NotificationOut:
    return NotificationOut(
        id=notification.id,
        user_id=notification.user_id,
        notification_type=notification.notification_type,
        title=notification.title,
        text=notification.text,
        entity_type=notification.entity_type,
        entity_id=notification.entity_id,
        created_at=notification.created_at,
        read_at=state.read_at if state else None,
        closed_at=state.closed_at if state else None,
    )


async def _get_scoped_notification(
    db: AsyncSession,
    notification_id: int,
    user_id: int,
) -> Notification:
    """Уведомление, доступное текущему пользователю.

    Отсутствующее или чужое персональное → 404 (не раскрывает существование).
    """
    notification = await db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            _scoped_user_filter(user_id),
        )
    )
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Уведомление не найдено",
        )
    return notification


async def _get_state(
    db: AsyncSession,
    notification_id: int,
    user_id: int,
) -> UserNotificationState | None:
    return await db.scalar(
        select(UserNotificationState).where(
            UserNotificationState.notification_id == notification_id,
            UserNotificationState.user_id == user_id,
        )
    )


@router.get("", response_model=NotificationListOut)
async def list_internal_notifications(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    only_unclosed: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationListOut:
    """Список общих и персональных уведомлений текущего пользователя.

    read_at/closed_at подтягиваются из UserNotificationState текущего
    пользователя; отсутствие записи = активное непрочитанное. Продюсеров
    событий пока нет — таблица пустая, колокольчик в UI получает пустой
    список без ошибок. Пагинация limit/offset, сортировка по created_at.
    """
    state = aliased(UserNotificationState)
    scope = _scoped_user_filter(current_user.id)

    base = (
        select(Notification, state)
        .outerjoin(state, _state_join_condition(state, current_user.id))
        .where(scope)
    )
    active = base.where(_active_condition(state))
    if only_unclosed:
        base = active

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0

    unread_stmt = active.where(_unread_condition(state))
    unread_count = (await db.execute(select(func.count()).select_from(unread_stmt.subquery()))).scalar() or 0

    items_stmt = base.order_by(
        Notification.created_at.desc(),
        Notification.id.desc(),
    )
    rows = (await db.execute(items_stmt.limit(limit).offset(offset))).all()

    return NotificationListOut(
        items=[_to_out(notification, st) for notification, st in rows],
        total=total,
        unread_count=unread_count,
    )


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def mark_notification_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationOut:
    """Пометить уведомление прочитанным (идемпотентно).

    Создаёт state-запись, если её нет; повторный вызов не меняет read_at.
    Чужое персональное → 404.
    """
    notification = await _get_scoped_notification(db, notification_id, current_user.id)
    now = datetime.now(UTC)
    await db.execute(
        pg_insert(UserNotificationState)
        .values(
            notification_id=notification.id,
            user_id=current_user.id,
            read_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=["notification_id", "user_id"],
        )
    )
    await db.commit()
    state = await _get_state(db, notification.id, current_user.id)
    return _to_out(notification, state)


@router.post("/{notification_id}/close", response_model=NotificationOut)
async def close_notification(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationOut:
    """Закрыть уведомление (идемпотентно): read_at и closed_at.

    upsert: повторный вызов не меняет даты. Чужое персональное → 404.
    """
    notification = await _get_scoped_notification(db, notification_id, current_user.id)
    now = datetime.now(UTC)
    await db.execute(
        pg_insert(UserNotificationState)
        .values(
            notification_id=notification.id,
            user_id=current_user.id,
            read_at=now,
            closed_at=now,
        )
        .on_conflict_do_update(
            index_elements=["notification_id", "user_id"],
            set_={
                "read_at": func.coalesce(UserNotificationState.read_at, now),
                "closed_at": func.coalesce(UserNotificationState.closed_at, now),
            },
        )
    )
    await db.commit()
    state = await _get_state(db, notification.id, current_user.id)
    return _to_out(notification, state)
