from uuid import UUID
from datetime import datetime, UTC
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User
from app.models.user_session import UserSession
from app.schemas.session import SessionOut
from app.services.session_service import (
    list_active_sessions,
    revoke_session,
    revoke_sessions_for_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def get_current_session_id(request: Request) -> UUID | None:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    if token == "admin":
        return None
    try:
        payload = decode_access_token(token)
        sid = payload.get("sid")
        if sid:
            return UUID(str(sid))
    except Exception:
        pass
    return None


@router.get("/sessions", response_model=list[SessionOut])
async def get_sessions(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sessions = await list_active_sessions(db, user_id=current_user.id)
    current_sid = get_current_session_id(request)

    return [
        SessionOut(
            id=s.id,
            device_label="Unknown Device",
            ip_address=None,
            user_agent=None,
            login_method=s.login_method,
            created_at=s.created_at,
            last_seen_at=s.created_at,
            is_current=bool(current_sid and s.id == current_sid),
        )
        for s in sessions
    ]


@router.delete("/sessions/others")
async def revoke_other_sessions(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_sid = get_current_session_id(request)
    count = await revoke_sessions_for_user(
        db,
        user_id=current_user.id,
        except_id=current_sid,
    )
    await db.commit()
    return {"count": count}


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(UserSession, session_id)
    if session is None or session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    # Проверим, активна ли сессия (не отозвана и не просрочена)
    now = datetime.now(UTC)
    expires = session.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)

    if session.revoked_at is not None or expires <= now:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    await revoke_session(db, session_id)
    await db.commit()

