import secrets
from datetime import UTC, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token
from app.models.user import User, UserRole
from app.models.user_login_token import UserLoginToken
from app.schemas.otp import OTPGenerateRequest, OTPGenerateResponse, OTPLoginRequest
from app.schemas.auth import TokenResponse

router = APIRouter(prefix="/auth/otp", tags=["otp"])


def generate_numeric_token(length: int = 6) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


@router.post("/generate", response_model=OTPGenerateResponse)
async def generate_otp(
    payload: OTPGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> OTPGenerateResponse:
    # 1. Проверяем права: только админы, плановики и начальники участков могут генерировать коды для других.
    # Обычные пользователи (операторы, транспортировщики) могут генерировать код только для себя.
    is_privileged = current_user.role in {UserRole.admin, UserRole.planner, UserRole.section_manager}
    if not is_privileged and current_user.id != payload.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав для генерации кода входа для другого пользователя"
        )

    # 2. Проверяем существование целевого пользователя
    target_user = await db.get(User, payload.user_id)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Целевой пользователь не найден"
        )
    if not target_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Целевой пользователь заблокирован"
        )

    # 3. Генерируем уникальный 6-значный код (проверяем по базе среди активных неиспользованных)
    now_time = datetime.now(UTC)
    token = None
    for _ in range(10):  # Предотвращаем бесконечный цикл на всякий случай
        candidate = generate_numeric_token(6)
        existing = await db.scalar(
            select(UserLoginToken).where(
                and_(
                    UserLoginToken.token == candidate,
                    UserLoginToken.is_used == False,
                    UserLoginToken.expires_at > now_time
                )
            )
        )
        if not existing:
            token = candidate
            break

    if not token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось сгенерировать уникальный код. Попробуйте еще раз"
        )

    # 3.5. Автоочистка: удаляем все предыдущие коды входа для этого пользователя
    await db.execute(
        delete(UserLoginToken).where(UserLoginToken.user_id == payload.user_id)
    )

    # 4. Создаем запись в БД (код бессрочен до активации или перегенерации)
    expires_at = now_time + timedelta(days=36500)
    login_token = UserLoginToken(
        user_id=payload.user_id,
        token=token,
        expires_at=expires_at,
        session_duration_seconds=payload.session_duration_seconds,
        is_used=False
    )
    db.add(login_token)
    await db.commit()
    await db.refresh(login_token)

    return OTPGenerateResponse(
        token=login_token.token,
        expires_at=login_token.expires_at
    )


@router.post("/login", response_model=TokenResponse)
async def login_with_otp(
    payload: OTPLoginRequest,
    db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    now_time = datetime.now(UTC)

    # 1. Ищем неиспользованный и неистекший токен в БД
    login_token = await db.scalar(
        select(UserLoginToken).where(
            and_(
                UserLoginToken.token == payload.token,
                UserLoginToken.is_used == False,
                UserLoginToken.expires_at > now_time
            )
        )
    )

    if not login_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный или истекший код входа"
        )

    # 2. Подгружаем пользователя, для которого сгенерирован токен
    user = await db.get(User, login_token.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Пользователь заблокирован"
        )

    # 3. Помечаем токен как использованный
    login_token.is_used = True
    await db.commit()

    # 4. Генерируем JWT-токен
    expires_delta = None
    if login_token.session_duration_seconds is not None:
        expires_delta = timedelta(seconds=login_token.session_duration_seconds)

    token = create_access_token(subject=user.username, expires_delta=expires_delta)
    return TokenResponse(access_token=token)
