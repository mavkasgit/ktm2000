"""Tests for the employees module (HRMS sync, preview, list)."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

from app.models.hrms_employee import HrmsEmployee
from app.services.hrms_employees import (
    HrmsSyncError,
    _build_employees_from_items,
    list_employees,
    preview_sync,
    sync_employees,
)


# ─── Unit: _build_employees_from_items ───────────────────────────────


def test_build_employees_skips_invalid() -> None:
    raw = [
        {"id": 1, "name": "Alice", "tab_number": "A1"},
        {"id": None, "name": "NoId"},
        {"name": "NoIdEither"},
        {"id": 2, "name": ""},
        {"id": 3, "name": "Bob"},
    ]
    synced_at = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    employees = _build_employees_from_items(raw, synced_at)
    assert len(employees) == 2
    assert employees[0].hrms_id == 1
    assert employees[1].hrms_id == 3


def test_build_employees_normalizes_fields() -> None:
    raw = [
        {
            "id": 10,
            "name": "Иванов",
            "tab_number": 488,
            "position": {"id": 1, "name": "Оператор"},
            "department": {"id": 2, "name": "Цех АСУ"},
        },
    ]
    synced_at = datetime(2026, 7, 28, tzinfo=timezone.utc)
    employees = _build_employees_from_items(raw, synced_at)
    assert len(employees) == 1
    emp = employees[0]
    assert emp.tab_number == "488"
    assert emp.position == "Оператор"
    assert emp.department == "Цех АСУ"


# ─── Integration: sync_employees ─────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_employees_replaces_cache(session) -> None:
    session.add(HrmsEmployee(hrms_id=99, name="Old", synced_at=datetime(2020, 1, 1, tzinfo=timezone.utc)))
    await session.commit()

    hrms_items = [{"id": 1, "name": "New Employee"}]
    with patch("app.services.hrms_employees.fetch_employees_from_hrms", new=AsyncMock(return_value=hrms_items)):
        employees, synced_at = await sync_employees(session)

    assert len(employees) == 1
    assert employees[0].hrms_id == 1
    assert employees[0].name == "New Employee"

    rows = list((await session.execute(select(HrmsEmployee))).scalars().all())
    assert len(rows) == 1
    assert rows[0].hrms_id == 1


@pytest.mark.asyncio
async def test_sync_employees_empty_raises(session) -> None:
    with patch("app.services.hrms_employees.fetch_employees_from_hrms", new=AsyncMock(return_value=[])):
        with pytest.raises(HrmsSyncError, match="пустой список"):
            await sync_employees(session)


@pytest.mark.asyncio
async def test_sync_employees_all_invalid_raises(session) -> None:
    with patch("app.services.hrms_employees.fetch_employees_from_hrms", new=AsyncMock(return_value=[{"name": "NoId"}])):
        with pytest.raises(HrmsSyncError, match="без валидных"):
            await sync_employees(session)


# ─── Integration: preview_sync ───────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_sync_diff(session) -> None:
    synced_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    session.add(HrmsEmployee(hrms_id=1, name="Alice", synced_at=synced_at))
    session.add(HrmsEmployee(hrms_id=2, name="Bob", synced_at=synced_at))
    await session.commit()

    hrms_items = [
        {"id": 1, "name": "Alice Updated"},
        {"id": 3, "name": "Charlie"},
    ]
    with patch("app.services.hrms_employees.fetch_employees_from_hrms", new=AsyncMock(return_value=hrms_items)):
        preview = await preview_sync(session)

    assert len(preview.diff.added) == 1
    assert preview.diff.added[0].id == 3
    assert len(preview.diff.removed) == 1
    assert preview.diff.removed[0].id == 2
    assert len(preview.diff.changed) == 1
    assert preview.diff.changed[0].before.name == "Alice"
    assert preview.diff.changed[0].after.name == "Alice Updated"
    assert "name" in preview.diff.changed[0].fields
    assert preview.diff.unchanged_count == 0

    # DB unchanged
    count = await session.scalar(select(func.count()).select_from(HrmsEmployee))
    assert count == 2


@pytest.mark.asyncio
async def test_preview_sync_does_not_modify_db(session) -> None:
    session.add(HrmsEmployee(hrms_id=10, name="Persistent", synced_at=datetime(2026, 7, 1, tzinfo=timezone.utc)))
    await session.commit()

    hrms_items = [{"id": 10, "name": "Changed"}]
    with patch("app.services.hrms_employees.fetch_employees_from_hrms", new=AsyncMock(return_value=hrms_items)):
        await preview_sync(session)

    rows = list((await session.execute(select(HrmsEmployee))).scalars().all())
    assert len(rows) == 1
    assert rows[0].name == "Persistent"


# ─── Integration: list_employees ─────────────────────────────────────


@pytest.mark.asyncio
async def test_list_employees_empty(session) -> None:
    employees, total, synced_at = await list_employees(session)
    assert employees == []
    assert total == 0
    assert synced_at is None


@pytest.mark.asyncio
async def test_list_employees_with_data(session) -> None:
    synced_at = datetime(2026, 7, 28, tzinfo=timezone.utc)
    session.add(HrmsEmployee(hrms_id=1, name="Alice", department="Цех А", synced_at=synced_at))
    session.add(HrmsEmployee(hrms_id=2, name="Bob", department="Цех Б", synced_at=synced_at))
    await session.commit()

    employees, total, _ = await list_employees(session)
    assert total == 2
    assert employees[0].name == "Alice"  # sorted by name asc


@pytest.mark.asyncio
async def test_list_employees_search(session) -> None:
    synced_at = datetime(2026, 7, 28, tzinfo=timezone.utc)
    session.add(HrmsEmployee(hrms_id=1, name="Иванов Иван", synced_at=synced_at))
    session.add(HrmsEmployee(hrms_id=2, name="Петров Пётр", synced_at=synced_at))
    await session.commit()

    employees, total, _ = await list_employees(session, search="Иванов")
    assert total == 1
    assert employees[0].hrms_id == 1


@pytest.mark.asyncio
async def test_list_employees_department_filter(session) -> None:
    synced_at = datetime(2026, 7, 28, tzinfo=timezone.utc)
    session.add(HrmsEmployee(hrms_id=1, name="A", department="Цех АСУ", synced_at=synced_at))
    session.add(HrmsEmployee(hrms_id=2, name="B", department="Цех Мех", synced_at=synced_at))
    await session.commit()

    employees, total, _ = await list_employees(session, department="АСУ")
    assert total == 1
    assert employees[0].hrms_id == 1


# ─── HTTP endpoint tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_employees_endpoint(auth_client) -> None:
    response = await auth_client.get("/api/employees")
    assert response.status_code == 200
    data = response.json()
    assert "employees" in data
    assert "total" in data
    assert "synced_at" in data


@pytest.mark.asyncio
async def test_sync_endpoint_502_when_hrms_unavailable(auth_client) -> None:
    with patch(
        "app.services.hrms_employees.fetch_employees_from_hrms",
        new=AsyncMock(side_effect=HrmsSyncError("HRMS недоступен")),
    ):
        response = await auth_client.post("/api/employees/sync")
    assert response.status_code == 502
    assert "hrms" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_sync_endpoint_success(auth_client, session) -> None:
    hrms_items = [{"id": 1, "name": "Тестовый сотрудник", "tab_number": "T1"}]
    with patch("app.services.hrms_employees.fetch_employees_from_hrms", new=AsyncMock(return_value=hrms_items)):
        response = await auth_client.post("/api/employees/sync")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["employees"][0]["name"] == "Тестовый сотрудник"


@pytest.mark.asyncio
async def test_preview_endpoint_success(auth_client, session) -> None:
    hrms_items = [{"id": 1, "name": "Alice"}]
    with patch("app.services.hrms_employees.fetch_employees_from_hrms", new=AsyncMock(return_value=hrms_items)):
        response = await auth_client.post("/api/employees/sync/preview")
    assert response.status_code == 200
    data = response.json()
    assert "diff" in data
    assert "added" in data["diff"]
    assert len(data["diff"]["added"]) == 1
