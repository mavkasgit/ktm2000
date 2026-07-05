from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.hrms_employee_cache import HrmsEmployeeCache
from app.services.hrms_employees import (
    build_hrms_employees_url,
    normalize_hrms_base_url,
    sync_hrms_employees_cache,
)


def test_normalize_hrms_base_url_accepts_host_port() -> None:
    assert normalize_hrms_base_url("192.168.1.50:8000") == "http://192.168.1.50:8000"
    assert (
        build_hrms_employees_url("192.168.1.50:8000")
        == "http://192.168.1.50:8000/api/employees"
    )


def test_normalize_hrms_base_url_accepts_connection_presets() -> None:
    assert normalize_hrms_base_url("localhost:8000") == "http://localhost:8000"
    assert (
        normalize_hrms_base_url("192.168.100.200:8000")
        == "http://192.168.100.200:8000"
    )
    assert (
        build_hrms_employees_url("192.168.100.200:8000")
        == "http://192.168.100.200:8000/api/employees"
    )


def test_normalize_hrms_base_url_accepts_full_endpoint() -> None:
    assert (
        normalize_hrms_base_url("http://hrms.local:8000/api/employees")
        == "http://hrms.local:8000/api/employees"
    )


@pytest.mark.asyncio
async def test_save_and_test_hrms_settings(auth_client) -> None:
    hrms_items = [{"id": 1, "name": "Тестовый сотрудник"}]

    with patch(
        "app.services.hrms_employees._request_hrms_employees",
        new=AsyncMock(return_value=hrms_items),
    ):
        response = await auth_client.post(
            "/api/users/hrms-settings/test",
            json={"base_url": "192.168.1.50:8000"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["employee_count"] == 1
    assert data["request_url"] == "http://192.168.1.50:8000/api/employees"

    settings_response = await auth_client.get("/api/users/hrms-settings")
    assert settings_response.status_code == 200
    settings = settings_response.json()
    assert settings["base_url"] == "http://192.168.1.50:8000"
    assert settings["employees_url"] == "http://192.168.1.50:8000/api/employees"


@pytest.mark.asyncio
async def test_sync_without_hrms_url_returns_error(auth_client) -> None:
    response = await auth_client.post("/api/users/employees/sync")
    assert response.status_code == 502
    assert "адрес hrms" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_cached_hrms_employees_empty(auth_client) -> None:
    response = await auth_client.get("/api/users/employees")
    assert response.status_code == 200
    data = response.json()
    assert data["employees"] == []
    assert data["synced_at"] is None
    assert data["total"] == 0
    assert data["limit"] == 50
    assert data["offset"] == 0


@pytest.mark.asyncio
async def test_sync_hrms_employees_normalizes_hrms_payload(auth_client, session) -> None:
    """HRMS возвращает tab_number как int, department/position как объекты."""
    hrms_items = [
        {
            "id": 1,
            "name": "Иванов Иван Иванович",
            "tab_number": 488,
            "position": {"id": 1, "name": "Оператор-наладчик"},
            "department": {"id": 1, "name": "Цех АСУ", "color": "#84CC16", "icon": "Factory"},
        },
        {
            "id": 5,
            "name": "Петров Петр",
            "tab_number": None,
            "position": {"id": 2, "name": "Мастер"},
            "department": {"id": 2, "name": 'ООО "КТМ-2000"', "color": "#3B82F6"},
        },
    ]

    with patch(
        "app.services.hrms_employees.fetch_hrms_employees_from_api",
        new=AsyncMock(return_value=hrms_items),
    ):
        response = await auth_client.post("/api/users/employees/sync")

    assert response.status_code == 200
    data = response.json()
    assert data["employees"][0]["tab_number"] == "488"
    assert data["employees"][0]["position"] == "Оператор-наладчик"
    assert data["employees"][0]["department"] == "Цех АСУ"
    assert data["employees"][1]["tab_number"] is None
    assert data["employees"][1]["position"] == "Мастер"
    assert data["employees"][1]["department"] == 'ООО "КТМ-2000"'

    result = await session.execute(select(HrmsEmployeeCache).order_by(HrmsEmployeeCache.hrms_id))
    rows = list(result.scalars().all())
    assert rows[0].tab_number == "488"
    assert rows[0].position == "Оператор-наладчик"
    assert rows[0].department == "Цех АСУ"


@pytest.mark.asyncio
async def test_sync_hrms_employees_populates_cache(auth_client, session) -> None:
    hrms_items = [
        {
            "id": 101,
            "name": "Иванов Иван",
            "tab_number": "T-101",
            "position": "Оператор",
            "department": "Цех 1",
        },
        {
            "id": 102,
            "name": "Петров Петр",
            "tab_number": None,
            "position": None,
            "department": None,
        },
    ]

    with patch(
        "app.services.hrms_employees.fetch_hrms_employees_from_api",
        new=AsyncMock(return_value=hrms_items),
    ):
        response = await auth_client.post("/api/users/employees/sync")

    assert response.status_code == 200
    data = response.json()
    assert len(data["employees"]) == 2
    assert data["employees"][0]["id"] == 101
    assert data["employees"][0]["name"] == "Иванов Иван"
    assert data["synced_at"] is not None

    result = await session.execute(select(HrmsEmployeeCache).order_by(HrmsEmployeeCache.hrms_id))
    rows = list(result.scalars().all())
    assert len(rows) == 2
    assert rows[0].hrms_id == 101
    assert rows[1].hrms_id == 102


@pytest.mark.asyncio
async def test_sync_hrms_employees_replaces_previous_cache(auth_client, session) -> None:
    session.add(
        HrmsEmployeeCache(
            hrms_id=1,
            name="Старый сотрудник",
            synced_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
    )
    await session.commit()

    with patch(
        "app.services.hrms_employees.fetch_hrms_employees_from_api",
        new=AsyncMock(return_value=[{"id": 2, "name": "Новый сотрудник"}]),
    ):
        response = await auth_client.post("/api/users/employees/sync")

    assert response.status_code == 200
    data = response.json()
    assert len(data["employees"]) == 1
    assert data["employees"][0]["id"] == 2

    result = await session.execute(select(HrmsEmployeeCache))
    rows = list(result.scalars().all())
    assert len(rows) == 1
    assert rows[0].hrms_id == 2


@pytest.mark.asyncio
async def test_sync_hrms_employees_empty_hrms_returns_error_and_keeps_cache(
    auth_client,
    session,
) -> None:
    session.add(
        HrmsEmployeeCache(
            hrms_id=77,
            name="Сохранённый сотрудник",
            synced_at=datetime(2026, 7, 5, 9, 0, tzinfo=timezone.utc),
        )
    )
    await session.commit()

    with patch(
        "app.services.hrms_employees.fetch_hrms_employees_from_api",
        new=AsyncMock(return_value=[]),
    ):
        response = await auth_client.post("/api/users/employees/sync")

    assert response.status_code == 502
    assert "пустой список" in response.json()["detail"].lower()

    result = await session.execute(select(HrmsEmployeeCache))
    rows = list(result.scalars().all())
    assert len(rows) == 1
    assert rows[0].hrms_id == 77


@pytest.mark.asyncio
async def test_get_cached_hrms_employees_returns_db_cache(auth_client, session) -> None:
    synced_at = datetime(2026, 7, 5, 10, 0, tzinfo=timezone.utc)
    session.add(
        HrmsEmployeeCache(
            hrms_id=55,
            name="Кешированный сотрудник",
            tab_number="T-55",
            synced_at=synced_at,
        )
    )
    await session.commit()

    response = await auth_client.get("/api/users/employees")
    assert response.status_code == 200
    data = response.json()
    assert len(data["employees"]) == 1
    assert data["employees"][0]["id"] == 55
    assert data["employees"][0]["name"] == "Кешированный сотрудник"
    assert data["synced_at"] is not None