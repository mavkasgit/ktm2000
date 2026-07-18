from pydantic import BaseModel, ConfigDict

from app.models.user import UserRole


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    # Present after OIDC callback only — FE keeps for Authentik end-session id_token_hint
    id_token: str | None = None


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None = None
    full_name: str
    role: UserRole
    section_id: int | None
    section_ids: list[int] = []
    is_active: bool
    hrms_access_level: str = "no_access"
    avatar_seed: str | None = None
    authentik_linked: bool = False
    profile_sot: str = "local"


class ProfileUpdateRequest(BaseModel):
    full_name: str | None = None
    avatar_seed: str | None = None
    clear_avatar: bool = False


class ProfileUpdateResponse(BaseModel):
    full_name: str
    avatar_seed: str | None = None
