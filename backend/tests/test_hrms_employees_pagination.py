"""Tests for GET /api/users/employees pagination (offset, limit, total, search, filters, sort)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.hrms_employee_cache import HrmsEmployeeCache
from app.models.user import User, UserRole
from app.core.security import get_password_hash


async def _seed_hrms_cache(session, count: int) -> list[HrmsEmployeeCache]:
    synced_at = datetime.now(timezone.utc)
    employees: list[HrmsEmployeeCache] = []
    departments = ["Цех АСУ", "Цех Механо", "Склад"]
    for index in range(count):
        employees.append(
            HrmsEmployeeCache(
                hrms_id=1_000 + index,
                name=f"HRMS Employee {index:03d}",
                tab_number=f"T-{index:04d}",
                position=f"Position {index % 3}",
                department=departments[index % len(departments)],
                synced_at=synced_at,
            )
        )
    session.add_all(employees)
    await session.commit()
    return employees


@pytest.mark.asyncio
async def test_hrms_employees_offset_limit_pagination(auth_client, session) -> None:
    await session.execute(HrmsEmployeeCache.__table__.delete())
    await session.commit()

    await _seed_hrms_cache(session, 11)

    first_page = await auth_client.get("/api/users/employees?limit=4&offset=0")
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert len(first_body["employees"]) == 4
    assert first_body["total"] == 11
    assert first_body["limit"] == 4
    assert first_body["offset"] == 0
    assert first_body["synced_at"] is not None

    second_page = await auth_client.get("/api/users/employees?limit=4&offset=4")
    assert second_page.status_code == 200
    second_body = second_page.json()
    assert len(second_body["employees"]) == 4
    assert second_body["total"] == 11

    first_ids = {employee["id"] for employee in first_body["employees"]}
    second_ids = {employee["id"] for employee in second_body["employees"]}
    assert first_ids.isdisjoint(second_ids)


@pytest.mark.asyncio
async def test_hrms_employees_search_across_pages(auth_client, session) -> None:
    await session.execute(HrmsEmployeeCache.__table__.delete())
    await session.commit()

    synced_at = datetime.now(timezone.utc)
    session.add(
        HrmsEmployeeCache(
            hrms_id=9001,
            name="UNIQUE-HRMS-MARKER Employee",
            tab_number="TAB-9001",
            position="Marker Position",
            department="Marker Department",
            synced_at=synced_at,
        )
    )
    await _seed_hrms_cache(session, 8)

    unfiltered = await auth_client.get("/api/users/employees?limit=3&offset=0")
    assert unfiltered.status_code == 200
    assert unfiltered.json()["total"] == 9

    filtered = await auth_client.get(
        "/api/users/employees?search=UNIQUE-HRMS-MARKER&limit=3&offset=0"
    )
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert filtered_body["total"] == 1
    assert filtered_body["employees"][0]["name"] == "UNIQUE-HRMS-MARKER Employee"


@pytest.mark.asyncio
async def test_hrms_employees_department_filter(auth_client, session) -> None:
    await session.execute(HrmsEmployeeCache.__table__.delete())
    await session.commit()

    employees = await _seed_hrms_cache(session, 9)

    response = await auth_client.get(
        "/api/users/employees?department=Цех%20АСУ&limit=50&offset=0"
    )
    assert response.status_code == 200
    body = response.json()
    expected_total = sum(1 for employee in employees if employee.department == "Цех АСУ")
    assert body["total"] == expected_total
    assert all(employee["department"] == "Цех АСУ" for employee in body["employees"])


@pytest.mark.asyncio
async def test_hrms_employees_linked_filter_and_sort(auth_client, session) -> None:
    await session.execute(HrmsEmployeeCache.__table__.delete())
    await session.execute(User.__table__.delete().where(User.__table__.c.username != "testauth"))
    await session.commit()

    employees = await _seed_hrms_cache(session, 6)

    session.add(
        User(
            username="hrms_linked_user",
            email="hrms_linked_user@example.com",
            password_hash=get_password_hash("pass"),
            full_name="HRMS Linked User",
            role=UserRole.operator,
            is_active=True,
            hrms_employee_id=employees[1].hrms_id,
        )
    )
    await session.commit()

    linked_response = await auth_client.get("/api/users/employees?linked=true&limit=50&offset=0")
    assert linked_response.status_code == 200
    linked_body = linked_response.json()
    assert linked_body["total"] == 1
    assert linked_body["employees"][0]["id"] == employees[1].hrms_id
    assert linked_body["employees"][0]["is_linked"] is True

    unlinked_response = await auth_client.get("/api/users/employees?linked=false&limit=50&offset=0")
    assert unlinked_response.status_code == 200
    assert unlinked_response.json()["total"] == 5

    sorted_response = await auth_client.get(
        "/api/users/employees?sort_by=name&sort_order=desc&limit=50&offset=0"
    )
    assert sorted_response.status_code == 200
    sorted_names = [employee["name"] for employee in sorted_response.json()["employees"]]
    assert sorted_names == sorted(sorted_names, reverse=True)