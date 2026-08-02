from datetime import UTC, datetime, timedelta
from uuid import UUID

from jose import JWTError, jwt

from app.core.config import settings


class TokenError(Exception):
    pass


def create_access_token(
    subject: str,
    role: str | None = None,
    full_name: str | None = None,
    expires_delta: timedelta | None = None,
    session_id: UUID | str | None = None,
) -> str:
    payload = {
        "sub": subject,
        "username": subject,
    }
    if role is not None:
        payload["role"] = role
    if full_name is not None:
        payload["full_name"] = full_name
    if session_id is not None:
        payload["sid"] = str(session_id)

    if expires_delta is not None:
        if expires_delta.total_seconds() != -1:
            payload["exp"] = datetime.now(UTC) + expires_delta
    else:
        payload["exp"] = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    secret_key = settings.JWT_SECRET_KEY or settings.SECRET_KEY
    return jwt.encode(payload, secret_key, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        secret_key = settings.JWT_SECRET_KEY or settings.SECRET_KEY
        return jwt.decode(token, secret_key, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise TokenError("Invalid token") from exc

