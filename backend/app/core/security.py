from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


class TokenError(Exception):
    pass


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password or not hashed_password.strip():
        return False
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(
    subject: str,
    role: str | None = None,
    full_name: str | None = None,
    hrms_access_level: str | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    payload = {
        "sub": subject,
        "username": subject,
    }
    if role is not None:
        payload["role"] = role
    if full_name is not None:
        payload["full_name"] = full_name
    if hrms_access_level is not None:
        payload["hrms_access_level"] = hrms_access_level

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

