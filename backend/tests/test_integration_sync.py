import pytest
from sqlalchemy import select
from app.models.user import User
from app.core.config import settings


@pytest.mark.asyncio
async def test_sync_employee_auth_failure(client) -> None:
    # 1. Request with missing token
    response = await client.post(
        "/api/integration/sync-employee",
        json={
            "employee_id": 12345,
            "tab_number": "12345",
            "name": "Иван Иванов",
            "position": "Оператор",
            "department": "Цех сборки",
            "is_deleted": False,
        },
    )
    assert response.status_code == 401

    # 2. Request with invalid token
    response = await client.post(
        "/api/integration/sync-employee",
        headers={"X-Integration-Token": "invalid-token"},
        json={
            "employee_id": 12345,
            "tab_number": "12345",
            "name": "Иван Иванов",
            "position": "Оператор",
            "department": "Цех сборки",
            "is_deleted": False,
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_sync_employee_success(client, session) -> None:
    headers = {"X-Integration-Token": settings.INTEGRATION_TOKEN}

    # 1. Create a new employee
    payload = {
        "employee_id": 99999,
        "tab_number": "99999",
        "name": "Ivan Ivanov",
        "position": "Welder",
        "department": "Welding Shop",
        "is_deleted": False,
    }
    response = await client.post(
        "/api/integration/sync-employee",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["username"] == "emp_99999"
    assert data["is_active"] is True

    # Check database record
    stmt = select(User).where(User.hrms_employee_id == 99999)
    result = await session.execute(stmt)
    user = result.scalars().first()
    assert user is not None
    assert user.tab_number == "99999"
    assert user.full_name == "Ivan Ivanov"
    assert user.position == "Welder"
    assert user.department == "Welding Shop"
    assert user.is_active is True

    # 2. Update the employee details
    payload_update = {
        "employee_id": 99999,
        "tab_number": "99999-new",
        "name": "Ivan Ivanov-Sidorov",
        "position": "Senior Welder",
        "department": "Welding Shop 2",
        "is_deleted": False,
    }
    response_update = await client.post(
        "/api/integration/sync-employee",
        headers=headers,
        json=payload_update,
    )
    assert response_update.status_code == 200

    # Verify updates in DB
    await session.refresh(user)
    assert user.tab_number == "99999-new"
    assert user.full_name == "Ivan Ivanov-Sidorov"
    assert user.position == "Senior Welder"
    assert user.department == "Welding Shop 2"
    assert user.is_active is True

    # 3. Mark the employee as deleted
    payload_delete = {
        "employee_id": 99999,
        "name": "Ivan Ivanov-Sidorov",
        "position": "Senior Welder",
        "department": "Welding Shop 2",
        "is_deleted": True,
    }
    response_delete = await client.post(
        "/api/integration/sync-employee",
        headers=headers,
        json=payload_delete,
    )
    assert response_delete.status_code == 200

    # Verify user is deactivated in DB
    await session.refresh(user)
    assert user.is_active is False
