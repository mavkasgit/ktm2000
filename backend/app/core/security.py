"""JWT helpers — thin KTM host shim over the shared session_core module.

The actual issuance/verification lives in app/services/session_core.py
(must-match across HRMS/KTM). This file only adapts the legacy
``app.core.security`` API surface so existing callers and tests keep
working; domain claims (role/full_name) are shaped here.
"""

from datetime import timedelta
from uuid import UUID

from app.core.config import settings
from app.services.session_core import (
    JwtConfig,
    TokenError,
    create_access_token as _core_create_access_token,
    decode_access_token as _core_decode_access_token,
)


def _jwt_config() -> JwtConfig:
    return JwtConfig(
        secret_key=settings.JWT_SECRET_KEY or settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
        default_ttl_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
    )


def create_access_token(
    subject: str,
    role: str | None = None,
    full_name: str | None = None,
    expires_delta: timedelta | None = None,
    session_id: UUID | str | None = None,
    claims: dict | None = None,
) -> str:
    base: dict = {}
    if role is not None:
        base["role"] = role
    if full_name is not None:
        base["full_name"] = full_name
    if claims:
        base.update(claims)
    return _core_create_access_token(
        _jwt_config(),
        subject,
        claims=base,
        session_id=session_id,
        expires_delta=expires_delta,
    )


def decode_access_token(token: str) -> dict:
    return _core_decode_access_token(_jwt_config(), token)
