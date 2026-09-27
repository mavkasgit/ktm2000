"""HRMS employees sync service.

Fetches employee list from external HRMS system and maintains a local cache
in the hrms_employees table. No user-linking — pure employee directory.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
from sqlalchemy import String, cast, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.sorting import SortClause, apply_sort, parse_sort
from app.models.hrms_employee import HrmsEmployee
from app.schemas.employees import (
    SyncChangeOut,
    SyncDiffEntryOut,
    SyncDiffOut,
    SyncPreviewOut,
)


class HrmsSyncError(Exception):
    """Raised when HRMS is unreachable or returns invalid data."""


# ─── HTTP fetch ──────────────────────────────────────────────────────


def _get_hrms_base_url() -> str:
    url = settings.HRMS_BASE_URL
    if not url:
        raise HrmsSyncError("HRMS_BASE_URL не настроен")
    return url.rstrip("/")


async def fetch_employees_from_hrms() -> list[dict]:
    """Fetch all employees from HRMS API, handling pagination."""
    base_url = _get_hrms_base_url()
    url = f"{base_url}/api/employees"
    headers = {"Authorization": f"Bearer {settings.HRMS_API_TOKEN}"}
    all_items: list[dict] = []
    page = 1
    per_page = 1000
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                resp = await client.get(url, headers=headers, params={"page": page, "per_page": per_page})
                resp.raise_for_status()
                data = resp.json()
                items = data.get("items") if isinstance(data, dict) else data
                if not isinstance(items, list):
                    break
                all_items.extend(items)
                total = data.get("total", 0) if isinstance(data, dict) else len(items)
                if len(all_items) >= total:
                    break
                page += 1
    except httpx.HTTPError as exc:
        raise HrmsSyncError(f"HRMS недоступен: {exc}") from exc
    return all_items


# ─── Normalization ───────────────────────────────────────────────────


def _normalize_field(value) -> str | None:
    """Normalize HRMS field: dicts with 'name', ints, strings."""
    if value is None:
        return None
    if isinstance(value, dict):
        return str(value.get("name", "")) or None
    if isinstance(value, int):
        return str(value)
    s = str(value).strip()
    return s if s else None


def _build_employees_from_items(raw_items: list[dict], synced_at: datetime) -> list[HrmsEmployee]:
    """Build HrmsEmployee objects from raw HRMS items, skipping invalid."""
    employees: list[HrmsEmployee] = []
    for item in raw_items:
        hrms_id = item.get("id")
        name = item.get("name")
        if not hrms_id or not name or not str(name).strip():
            continue
        employees.append(
            HrmsEmployee(
                hrms_id=int(hrms_id),
                name=str(name).strip(),
                tab_number=_normalize_field(item.get("tab_number")),
                position=_normalize_field(item.get("position")),
                department=_normalize_field(item.get("department")),
                synced_at=synced_at,
            )
        )
    return employees


# ─── Sync (write) ────────────────────────────────────────────────────


async def sync_employees(db: AsyncSession) -> tuple[list[HrmsEmployee], datetime]:
    """Full-replace the employee cache from HRMS. Returns (employees, synced_at)."""
    raw_items = await fetch_employees_from_hrms()
    if not raw_items:
        raise HrmsSyncError("HRMS вернул пустой список сотрудников")

    synced_at = datetime.now(timezone.utc)
    employees = _build_employees_from_items(raw_items, synced_at)
    if not employees:
        raise HrmsSyncError("HRMS вернул данные без валидных сотрудников")

    await db.execute(delete(HrmsEmployee))
    db.add_all(employees)
    await db.commit()
    for emp in employees:
        await db.refresh(emp)

    return employees, synced_at


# ─── Preview (read-only diff) ────────────────────────────────────────


async def preview_sync(db: AsyncSession) -> SyncPreviewOut:
    """Compute diff between current cache and live HRMS data without writing."""
    result = await db.execute(select(HrmsEmployee))
    current = list(result.scalars().all())

    raw_items = await fetch_employees_from_hrms()
    if not raw_items:
        raise HrmsSyncError("HRMS вернул пустой список сотрудников")

    synced_at = datetime.now(timezone.utc)
    next_employees = _build_employees_from_items(raw_items, synced_at)
    if not next_employees:
        raise HrmsSyncError("HRMS вернул данные без валидных сотрудников")

    current_by_id: dict[int, HrmsEmployee] = {e.hrms_id: e for e in current}
    next_by_id: dict[int, HrmsEmployee] = {e.hrms_id: e for e in next_employees}
    current_ids = set(current_by_id.keys())
    next_ids = set(next_by_id.keys())

    def _to_entry(emp: HrmsEmployee) -> SyncDiffEntryOut:
        return SyncDiffEntryOut(
            id=emp.hrms_id,
            name=emp.name,
            tab_number=emp.tab_number,
            position=emp.position,
            department=emp.department,
        )

    added = [_to_entry(next_by_id[eid]) for eid in sorted(next_ids - current_ids)]
    removed = [_to_entry(current_by_id[eid]) for eid in sorted(current_ids - next_ids)]

    changed: list[SyncChangeOut] = []
    unchanged_count = 0
    for eid in sorted(current_ids & next_ids):
        cur = current_by_id[eid]
        nxt = next_by_id[eid]
        fields: list[str] = []
        if cur.name != nxt.name:
            fields.append("name")
        if (cur.tab_number or "") != (nxt.tab_number or ""):
            fields.append("tab_number")
        if (cur.position or "") != (nxt.position or ""):
            fields.append("position")
        if (cur.department or "") != (nxt.department or ""):
            fields.append("department")
        if fields:
            changed.append(SyncChangeOut(before=_to_entry(cur), after=_to_entry(nxt), fields=fields))
        else:
            unchanged_count += 1

    return SyncPreviewOut(
        employees=[_to_entry(e) for e in next_employees],
        synced_at=synced_at,
        diff=SyncDiffOut(
            added=added,
            removed=removed,
            changed=changed,
            unchanged_count=unchanged_count,
        ),
    )


# ─── List (paginated read) ───────────────────────────────────────────

# ─── Сортировка кеша сотрудников ──────────────────────────────────────
# Единая таблица «поле ?sort= → выражение SQL»; она же — источник истины
# для валидации (apply_sort отвечает 400 на поле, которого здесь нет).
_SORT_COLUMNS: dict[str, object] = {
    "hrms_id": HrmsEmployee.hrms_id,
    "name": HrmsEmployee.name,
    "tab_number": HrmsEmployee.tab_number,
    "position": HrmsEmployee.position,
    "department": HrmsEmployee.department,
}

# Курируемый набор полей сортировки: контракт для фронта. Выводится из
# таблицы резолва, а не живёт отдельно.
VALID_SORT_FIELDS = frozenset(_SORT_COLUMNS)

# Поля, где значение может быть пустым: необязательные колонки HRMS.
# Пустые уходят в конец в ЛЮБОМ направлении (в Postgres DESC по умолчанию
# ставит NULL первым — оператор кликнул «спустить», а незаполненные
# значения оказываются наверху).
_SORT_NULLS_LAST_FIELDS = ("tab_number", "position", "department")

# Порядок по умолчанию — тот же, что давал sort_by=name&sort_order=asc.
_SORT_DEFAULT = SortClause("name", "asc")


async def list_employees(
    db: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    sort: str | None = None,
    department: str | None = None,
) -> tuple[list[HrmsEmployee], int, datetime | None]:
    """List cached employees with pagination, search, sort, department filter."""
    stmt = select(HrmsEmployee)

    if department:
        stmt = stmt.where(HrmsEmployee.department.ilike(f"%{department}%"))

    if search:
        search_like = f"%{search}%"
        stmt = stmt.where(
            or_(
                HrmsEmployee.name.ilike(search_like),
                HrmsEmployee.tab_number.ilike(search_like),
                HrmsEmployee.position.ilike(search_like),
                HrmsEmployee.department.ilike(search_like),
                cast(HrmsEmployee.hrms_id, String).ilike(search_like),
            )
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # Сортировка разбирается до выборки: неизвестное поле или направление —
    # 400, а не молчаливый фолбэк на name. Приоритеты слева направо, в конце
    # tiebreaker по hrms_id (порядок строк между страницами не «мигает»).
    clauses = parse_sort(sort, default=_SORT_DEFAULT)
    stmt = apply_sort(
        stmt,
        clauses,
        _SORT_COLUMNS,
        tiebreaker=HrmsEmployee.hrms_id,
        nulls_last=_SORT_NULLS_LAST_FIELDS,
    )
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    employees = list(result.scalars().all())

    # Get latest synced_at
    synced_at = await db.scalar(select(func.max(HrmsEmployee.synced_at)))

    return employees, total, synced_at
