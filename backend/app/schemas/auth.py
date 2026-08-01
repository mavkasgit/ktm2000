from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.user import UserRole


class LoginRequest(BaseModel):
    username: str
    password: str


class BreakGlassLoginRequest(BaseModel):
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
    avatar_seed: str | None = None
    locale: str | None = None
    theme: str | None = None
    authentik_linked: bool = False
    profile_sot: str = "local"
    is_break_glass: bool = False


class ProfileUpdateRequest(BaseModel):
    full_name: str | None = None
    avatar_seed: str | None = None
    clear_avatar: bool = False
    email: EmailStr | None = None
    locale: Literal["ru", "en"] | None = None
    theme: Literal["system", "light", "dark"] | None = None


class ProfileUpdateResponse(BaseModel):
    full_name: str
    avatar_seed: str | None = None
    email: str | None = None
    locale: str | None = None
    theme: str | None = None


class RoleSections(BaseModel):
    code: UserRole
    label: str
    sections: list[str]


class RolesResponse(BaseModel):
    roles: list[RoleSections]
