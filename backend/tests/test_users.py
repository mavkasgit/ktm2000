import pytest
from sqlalchemy import select
from app.models.user import User, UserRole
from app.core.security import get_password_hash


async def _make_user(session, username: str, role: UserRole, hrms_employee_id: int | None = None, tab_number: str | None = None) -> User:
    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash=get_password_hash("pass"),
        full_name=f"Full Name {username}",
        role=role,
        is_active=True,
        hrms_employee_id=hrms_employee_id,
        tab_number=tab_number,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_create_user_success(auth_client, session) -> None:
    # Создание пользователя с hrms_employee_id
    response = await auth_client.post(
        "/api/users",
        json={
            "username": "new_user_1",
            "email": "new_1@example.com",
            "password": "password123",
            "full_name": "New Employee 1",
            "role": "operator",
            "hrms_employee_id": 12345,
            "tab_number": "T-12345",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["hrms_employee_id"] == 12345
    assert data["tab_number"] == "T-12345"

    # Проверка в БД
    stmt = select(User).where(User.hrms_employee_id == 12345)
    res = await session.execute(stmt)
    user = res.scalars().first()
    assert user is not None
    assert user.username == "new_user_1"


@pytest.mark.asyncio
async def test_create_user_duplicate_role_operator_merges(auth_client, session) -> None:
    # 1. Создаем существующего оператора (например, синхронизированного из HRMS)
    existing_op = await _make_user(session, "operator_synced", UserRole.operator, hrms_employee_id=22222)
    await session.commit()

    # 2. Пытаемся создать пользователя с тем же hrms_employee_id
    response = await auth_client.post(
        "/api/users",
        json={
            "username": "promoted_user",
            "email": "promoted@example.com",
            "password": "newpassword",
            "full_name": "Promoted Worker",
            "role": "planner",
            "hrms_employee_id": 22222,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["id"] == existing_op.id
    assert data["username"] == "promoted_user"
    assert data["role"] == "planner"

    # Убеждаемся, что в БД запись обновилась
    await session.refresh(existing_op)
    assert existing_op.username == "promoted_user"
    assert existing_op.role == UserRole.planner


@pytest.mark.asyncio
async def test_create_user_duplicate_role_admin_rejected(auth_client, session) -> None:
    # 1. Создаем существующего администратора
    await _make_user(session, "admin_user", UserRole.admin, hrms_employee_id=33333)
    await session.commit()

    # 2. Пытаемся создать пользователя с тем же hrms_employee_id
    response = await auth_client.post(
        "/api/users",
        json={
            "username": "imposter",
            "email": "imposter@example.com",
            "password": "password",
            "full_name": "Imposter Admin",
            "role": "operator",
            "hrms_employee_id": 33333,
        },
    )
    # Должен вернуть 409 Conflict, так как слияние с админом запрещено
    assert response.status_code == 409
    assert "Сотрудник уже связан" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_user_hrms_employee_id(auth_client, session) -> None:
    user = await _make_user(session, "user_to_update", UserRole.operator)
    await session.commit()

    # Связываем его с сотрудником
    response = await auth_client.patch(
        f"/api/users/{user.id}",
        json={"hrms_employee_id": 44444, "tab_number": "T-44444"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["hrms_employee_id"] == 44444
    assert data["tab_number"] == "T-44444"


@pytest.mark.asyncio
async def test_update_user_hrms_employee_id_reset(auth_client, session) -> None:
    # 1. Создаем пользователя, уже связанного с сотрудником
    user = await _make_user(session, "linked_user", UserRole.operator, hrms_employee_id=55555, tab_number="T-55555")
    await session.commit()

    # 2. Сбрасываем связь (передаем None/null)
    response = await auth_client.patch(
        f"/api/users/{user.id}",
        json={"hrms_employee_id": None, "tab_number": None},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["hrms_employee_id"] is None
    assert data["tab_number"] is None

    # Проверяем в БД
    await session.refresh(user)
    assert user.hrms_employee_id is None
    assert user.tab_number is None


@pytest.mark.asyncio
async def test_update_user_duplicate_hrms_employee_id_rejected(auth_client, session) -> None:
    # 1. Создаем двух пользователей
    user1 = await _make_user(session, "user1", UserRole.operator, hrms_employee_id=66666)
    user2 = await _make_user(session, "user2", UserRole.operator)
    await session.commit()

    # 2. Пытаемся привязать пользователя 2 к тому же hrms_employee_id
    response = await auth_client.patch(
        f"/api/users/{user2.id}",
        json={"hrms_employee_id": 66666},
    )
    assert response.status_code == 409
    assert "уже привязан к другому пользователю" in response.json()["detail"]
