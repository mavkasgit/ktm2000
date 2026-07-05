from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel
from sqlalchemy import cast, delete, exists, func, or_, select, String
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hrms_employee_cache import HrmsEmployeeCache
from app.models.hrms_integration_settings import HrmsIntegrationSettings
from app.models.user import User

logger = logging.getLogger(__name__)


# ─── Preview Pydantic schemas ─────────────────────────────────────────


class HrmsSyncDiffEntryOut(BaseModel):
    id: int
    name: str
    tab_number: str | None = None
    position: str | None = None
    department: str | None = None
    is_linked: bool = False


class HrmsSyncChangeOut(BaseModel):
    before: HrmsSyncDiffEntryOut
    after: HrmsSyncDiffEntryOut
    fields: list[str]  # подмножество ["name","tab_number","position","department"]


class HrmsSyncDiffOut(BaseModel):
    added: list[HrmsSyncDiffEntryOut]
    removed: list[HrmsSyncDiffEntryOut]
    changed: list[HrmsSyncChangeOut]
    unchanged_count: int


class HrmsSyncPreviewOut(BaseModel):
    employees: list[HrmsSyncDiffEntryOut]   # что в кеше будет после применения
    synced_at: datetime
    diff: HrmsSyncDiffOut

HRMS_REQUEST_TIMEOUT_SECONDS = 5.0

HRMS_EMPLOYEE_SORT_FIELDS = frozenset({
    "hrms_id",
    "name",
    "tab_number",
    "position",
    "department",
    "linked",
})


class HrmsSyncError(Exception):
    """HRMS недоступен или вернул пустой/невалидный список сотрудников."""


def _normalize_tab_number(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_nested_label(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        name = value.get("name")
        if name is None:
            return None
        text = str(name).strip()
        return text or None
    text = str(value).strip()
    return text or None


def normalize_hrms_base_url(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise ValueError("Адрес HRMS не указан")

    if not value.startswith(("http://", "https://")):
        value = f"http://{value}"

    parsed = urlparse(value)
    if not parsed.hostname:
        raise ValueError("Некорректный адрес HRMS")

    port = f":{parsed.port}" if parsed.port else ""
    base = f"{parsed.scheme}://{parsed.hostname}{port}".rstrip("/")

    if parsed.path and parsed.path not in ("", "/"):
        path = parsed.path.rstrip("/")
        if path.endswith("/api/employees"):
            return f"{base}{path}"
        if path.endswith("/api"):
            return f"{base}{path}/employees"
        return f"{base}{path}"

    return base


def build_hrms_employees_url(base_url: str) -> str:
    normalized = normalize_hrms_base_url(base_url)
    if normalized.endswith("/api/employees"):
        return normalized
    return f"{normalized}/api/employees"


async def get_hrms_integration_settings(db: AsyncSession) -> HrmsIntegrationSettings:
    result = await db.execute(select(HrmsIntegrationSettings).order_by(HrmsIntegrationSettings.id).limit(1))
    settings = result.scalars().first()
    if settings is None:
        settings = HrmsIntegrationSettings(api_token="admin")
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


async def update_hrms_integration_settings(
    db: AsyncSession,
    *,
    base_url: str | None,
    api_token: str | None = None,
) -> HrmsIntegrationSettings:
    settings = await get_hrms_integration_settings(db)

    if base_url is not None:
        trimmed = base_url.strip()
        settings.base_url = normalize_hrms_base_url(trimmed) if trimmed else None

    if api_token is not None:
        token = api_token.strip()
        settings.api_token = token or "admin"

    settings.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(settings)
    return settings


async def _request_hrms_employees(url: str, api_token: str) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {api_token}"}
    params = {"status": "active", "per_page": 1000}

    async with httpx.AsyncClient(timeout=HRMS_REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        items = data.get("items", [])
        if not isinstance(items, list):
            return []
        return items


async def fetch_hrms_employees_from_api(db: AsyncSession) -> list[dict[str, Any]]:
    """Загрузить активных сотрудников из HRMS по адресу из настроек."""
    settings = await get_hrms_integration_settings(db)
    if not settings.base_url:
        raise HrmsSyncError("Укажите адрес HRMS в настройках на странице пользователей")

    url = build_hrms_employees_url(settings.base_url)
    try:
        return await _request_hrms_employees(url, settings.api_token)
    except httpx.HTTPStatusError as exc:
        raise HrmsSyncError(
            f"HRMS ответил с ошибкой {exc.response.status_code} по адресу {url}"
        ) from exc
    except httpx.RequestError as exc:
        raise HrmsSyncError(f"HRMS недоступен по адресу {url}") from exc


async def test_hrms_connection(
    db: AsyncSession,
    *,
    base_url: str | None = None,
    api_token: str | None = None,
) -> dict[str, Any]:
    settings = await get_hrms_integration_settings(db)
    effective_base_url = base_url.strip() if base_url and base_url.strip() else settings.base_url
    effective_token = api_token.strip() if api_token and api_token.strip() else settings.api_token

    if not effective_base_url:
        raise HrmsSyncError("Укажите адрес HRMS")

    url = build_hrms_employees_url(effective_base_url)
    items = await _request_hrms_employees(url, effective_token)
    valid_count = sum(1 for item in items if item.get("id") is not None and item.get("name"))

    if valid_count == 0:
        raise HrmsSyncError(f"HRMS доступен ({url}), но вернул пустой список сотрудников")

    return {
        "request_url": url,
        "employee_count": valid_count,
    }


def _hrms_linked_exists():
    return exists(
        select(1).where(User.hrms_employee_id == HrmsEmployeeCache.hrms_id)
    )


def _apply_hrms_employee_filters(
    stmt,
    *,
    search: str | None = None,
    department: str | None = None,
    linked: bool | None = None,
):
    if department:
        stmt = stmt.where(HrmsEmployeeCache.department.ilike(f"%{department}%"))
    if linked is True:
        stmt = stmt.where(_hrms_linked_exists())
    elif linked is False:
        stmt = stmt.where(~_hrms_linked_exists())
    if search:
        search_like = f"%{search}%"
        stmt = stmt.where(
            or_(
                HrmsEmployeeCache.name.ilike(search_like),
                HrmsEmployeeCache.tab_number.ilike(search_like),
                HrmsEmployeeCache.position.ilike(search_like),
                HrmsEmployeeCache.department.ilike(search_like),
                cast(HrmsEmployeeCache.hrms_id, String).ilike(search_like),
            )
        )
    return stmt


def _resolve_hrms_order_column(sort_by: str):
    if sort_by == "name":
        return HrmsEmployeeCache.name
    if sort_by == "tab_number":
        return HrmsEmployeeCache.tab_number
    if sort_by == "position":
        return HrmsEmployeeCache.position
    if sort_by == "department":
        return HrmsEmployeeCache.department
    if sort_by == "linked":
        return _hrms_linked_exists()
    if sort_by == "hrms_id":
        return HrmsEmployeeCache.hrms_id
    return HrmsEmployeeCache.name


async def list_cached_hrms_employees_paginated(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    search: str | None = None,
    sort_by: str = "name",
    sort_order: str = "asc",
    department: str | None = None,
    linked: bool | None = None,
) -> tuple[list[tuple[HrmsEmployeeCache, bool]], int, datetime | None]:
    resolved_sort_by = sort_by if sort_by in HRMS_EMPLOYEE_SORT_FIELDS else "name"
    order_column = _resolve_hrms_order_column(resolved_sort_by)

    base_stmt = _apply_hrms_employee_filters(
        select(HrmsEmployeeCache),
        search=search,
        department=department,
        linked=linked,
    )

    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    if sort_order == "desc":
        ordered_stmt = base_stmt.order_by(order_column.desc(), HrmsEmployeeCache.hrms_id.desc())
    else:
        ordered_stmt = base_stmt.order_by(order_column.asc(), HrmsEmployeeCache.hrms_id.asc())

    ordered_stmt = ordered_stmt.limit(limit).offset(offset)
    employees = list((await db.execute(ordered_stmt)).scalars().all())

    linked_ids = {
        int(value)
        for value in (
            await db.execute(
                select(User.hrms_employee_id).where(User.hrms_employee_id.is_not(None))
            )
        ).scalars().all()
        if value is not None
    }

    rows = [(employee, employee.hrms_id in linked_ids) for employee in employees]
    synced_at = None
    if total > 0:
        synced_at = await db.scalar(select(func.max(HrmsEmployeeCache.synced_at)))

    return rows, total, synced_at


async def get_cached_hrms_employees(
    db: AsyncSession,
) -> tuple[list[HrmsEmployeeCache], datetime | None]:
    result = await db.execute(
        select(HrmsEmployeeCache).order_by(HrmsEmployeeCache.name, HrmsEmployeeCache.hrms_id)
    )
    employees = list(result.scalars().all())
    if not employees:
        return [], None

    synced_at = await db.scalar(select(func.max(HrmsEmployeeCache.synced_at)))
    return employees, synced_at


def _build_hrms_employees_from_items(
    raw_items: list[dict[str, Any]],
    synced_at: datetime,
) -> list[HrmsEmployeeCache]:
    """Convert raw HRMS API items to HrmsEmployeeCache objects without DB writes.

    Skips items with missing id or name. Raises HrmsSyncError if the resulting
    list is empty.
    """
    employees: list[HrmsEmployeeCache] = []
    for item in raw_items:
        hrms_id = item.get("id")
        name = item.get("name")
        if hrms_id is None or not name:
            continue
        employees.append(
            HrmsEmployeeCache(
                hrms_id=int(hrms_id),
                name=str(name),
                tab_number=_normalize_tab_number(item.get("tab_number")),
                position=_normalize_nested_label(item.get("position")),
                department=_normalize_nested_label(item.get("department")),
                synced_at=synced_at,
            )
        )
    if not employees:
        raise HrmsSyncError("HRMS вернул данные без валидных сотрудников")
    return employees


async def sync_hrms_employees_cache(
    db: AsyncSession,
) -> tuple[list[HrmsEmployeeCache], datetime]:
    raw_items = await fetch_hrms_employees_from_api(db)
    if not raw_items:
        raise HrmsSyncError("HRMS недоступен или вернул пустой список сотрудников")

    synced_at = datetime.now(timezone.utc)
    employees = _build_hrms_employees_from_items(raw_items, synced_at)

    await db.execute(delete(HrmsEmployeeCache))
    for employee in employees:
        db.add(employee)

    await db.commit()

    for employee in employees:
        await db.refresh(employee)

    return employees, synced_at


async def compute_hrms_sync_preview(db: AsyncSession) -> HrmsSyncPreviewOut:
    """Compute diff between current cache and live HRMS data without writing to DB.

    Returns a HrmsSyncPreviewOut with added/removed/changed employees.
    """
    from app.services.users_queries import get_linked_hrms_ids

    current_employees, _ = await get_cached_hrms_employees(db)
    raw_items = await fetch_hrms_employees_from_api(db)
    if not raw_items:
        raise HrmsSyncError("HRMS недоступен или вернул пустой список сотрудников")

    synced_at = datetime.now(timezone.utc)
    next_employees = _build_hrms_employees_from_items(raw_items, synced_at)

    # Build lookup dicts by hrms_id
    current_by_id: dict[int, HrmsEmployeeCache] = {e.hrms_id: e for e in current_employees}
    next_by_id: dict[int, HrmsEmployeeCache] = {e.hrms_id: e for e in next_employees}
    current_ids = set(current_by_id.keys())
    next_ids = set(next_by_id.keys())

    linked_ids = set(await get_linked_hrms_ids(db))

    def _to_entry(emp: HrmsEmployeeCache) -> HrmsSyncDiffEntryOut:
        return HrmsSyncDiffEntryOut(
            id=emp.hrms_id,
            name=emp.name,
            tab_number=emp.tab_number,
            position=emp.position,
            department=emp.department,
            is_linked=emp.hrms_id in linked_ids,
        )

    # Added — in next but not in current
    added_ids = next_ids - current_ids
    added = [_to_entry(next_by_id[eid]) for eid in sorted(added_ids)]

    # Removed — in current but not in next
    removed_ids = current_ids - next_ids
    removed = [_to_entry(current_by_id[eid]) for eid in sorted(removed_ids)]

    # Changed — in both but some fields differ
    common_ids = current_ids & next_ids
    changed: list[HrmsSyncChangeOut] = []
    unchanged_count = 0
    for eid in sorted(common_ids):
        cur = current_by_id[eid]
        nxt = next_by_id[eid]
        fields: list[str] = []
        if cur.name != nxt.name:
            fields.append("name")
        if (cur.tab_number or "").strip() != (nxt.tab_number or "").strip():
            fields.append("tab_number")
        if (cur.position or "").strip() != (nxt.position or "").strip():
            fields.append("position")
        if (cur.department or "").strip() != (nxt.department or "").strip():
            fields.append("department")
        if fields:
            changed.append(
                HrmsSyncChangeOut(
                    before=_to_entry(cur),
                    after=_to_entry(nxt),
                    fields=fields,
                )
            )
        else:
            unchanged_count += 1

    diff = HrmsSyncDiffOut(
        added=added,
        removed=removed,
        changed=changed,
        unchanged_count=unchanged_count,
    )

    return HrmsSyncPreviewOut(
        employees=[_to_entry(e) for e in next_employees],
        synced_at=synced_at,
        diff=diff,
    )