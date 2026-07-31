from datetime import datetime

from pydantic import BaseModel


class EmployeeOut(BaseModel):
    id: int
    hrms_id: int
    name: str
    tab_number: str | None = None
    position: str | None = None
    department: str | None = None


class EmployeeListOut(BaseModel):
    employees: list[EmployeeOut]
    total: int
    limit: int
    offset: int
    synced_at: datetime | None = None


class SyncDiffEntryOut(BaseModel):
    id: int
    name: str
    tab_number: str | None = None
    position: str | None = None
    department: str | None = None


class SyncChangeOut(BaseModel):
    before: SyncDiffEntryOut
    after: SyncDiffEntryOut
    fields: list[str]


class SyncDiffOut(BaseModel):
    added: list[SyncDiffEntryOut]
    removed: list[SyncDiffEntryOut]
    changed: list[SyncChangeOut]
    unchanged_count: int


class SyncPreviewOut(BaseModel):
    employees: list[SyncDiffEntryOut]
    synced_at: datetime
    diff: SyncDiffOut
