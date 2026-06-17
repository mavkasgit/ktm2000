from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token, verify_password
from app.models.user import User
from app.schemas.auth import LoginRequest, MeResponse, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    user = await db.scalar(
        select(User).where(
            or_(User.username == payload.username, User.email == payload.username)
        )
    )
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is disabled")

    token = create_access_token(
        subject=user.username,
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        full_name=user.full_name,
        hrms_access_level=user.hrms_access_level,
    )
    return TokenResponse(access_token=token)


@router.get("/me", response_model=MeResponse)
async def me(current_user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse.model_validate(current_user)
