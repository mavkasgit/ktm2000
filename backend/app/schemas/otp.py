from datetime import datetime
from pydantic import BaseModel, Field


class OTPGenerateRequest(BaseModel):
    user_id: int
    session_duration_seconds: int | None = Field(None, description="Время жизни сессии (JWT-токена) после входа в секундах")
    code_lifetime_seconds: int = Field(600, description="Время жизни самого 6-значного кода до использования в секундах")


class OTPGenerateResponse(BaseModel):
    token: str = Field(..., description="6-значный цифровой код входа")
    expires_at: datetime = Field(..., description="Время истечения действия кода")


class OTPLoginRequest(BaseModel):
    token: str = Field(..., description="6-значный цифровой код входа")
