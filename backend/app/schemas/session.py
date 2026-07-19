from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class SessionOut(BaseModel):
    id: UUID
    device_label: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    login_method: str
    created_at: datetime
    last_seen_at: datetime | None = None
    is_current: bool = False

    class Config:
        from_attributes = True
