"""Tests for GET /api/users pagination (offset, limit, total, search, filters, sort)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.section import Section
from app.models.user import User, UserRole, user_sections
from app.core.security import get_password_hash


async def _make_user(
    session,
    *,
    username: str,
    full_name: str,
    role: UserRole = UserRole.viewer,
    is_active: bool = True,
    email: str | None = None,
    hrms_employee_id: int | None = None,
) -> User:
    user = User(
        username=username,
        email=email or f"{username}@example.com",
        password_hash=get_password_hash("pass"),
        full_name=full_name,
        role=role,
        is_active=is_active,
        hrms_employee_id=hrms_employee_id,
    )
    session.add(user)
    await session.flush()
    return user


async def _seed_users(session, count: int) -> list[User]:
    users: list[User] = []
    roles = [UserRole.admin, UserRole.planner, UserRole.operator, UserRole.viewer]
    for index in range(count):
        users.append(
            await _make_user(
                session,
                username=f"paginated_user_{index:03d}",
                full_name=f"Paginated User {index:03d}",
                role=roles[index % len(roles)],
                is_active=index % 3 != 0,
                email=f"paginated_{index:03d}@example.com",
                hrms_employee_id=10_000 + index if index % 4 == 0 else None,
            )
        )
    await session.commit()
    return users


@pytest.mark.asyncio
async def test_users_offset_limit_pagination(auth_client, session) -> None:
    await session.execute(User.__table__.delete().where(User.__table__.c.username != "testauth"))
    await session.commit()

    await _seed_users(session, 12)

    first_page = await auth_client.get("/api/users?limit=5&offset=0")
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert len(first_body["users"]) == 5
    assert first_body["total"] == 13  # 12 seeded + testauth from auth_client fixture
    assert first_body["limit"] == 5
    assert first_body["offset"] == 0

    second_page = await auth_client.get("/api/users?limit=5&offset=5")
    assert second_page.status_code == 200
    second_body = second_page.json()
    assert len(second_body["users"]) == 5
    assert second_body["total"] == 13

    first_ids = {user["id"] for user in first_body["users"]}
    second_ids = {user["id"] for user in second_body["users"]}
    assert first_ids.isdisjoint(second_ids)


@pytest.mark.asyncio
async def test_users_search_across_pages(auth_client, session) -> None:
    await session.execute(User.__table__.delete().where(User.__table__.c.username != "testauth"))
    await session.commit()

    await _make_user(
        session,
        username="alpha_marker",
        full_name="UNIQUE-USERS-MARKER Alpha",
        role=UserRole.planner,
    )
    await _seed_users(session, 10)
    await session.commit()

    unfiltered = await auth_client.get("/api/users?limit=3&offset=0")
    assert unfiltered.status_code == 200
    assert unfiltered.json()["total"] >= 11

    filtered = await auth_client.get("/api/users?search=UNIQUE-USERS-MARKER&limit=3&offset=0")
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert filtered_body["total"] == 1
    assert filtered_body["users"][0]["full_name"] == "UNIQUE-USERS-MARKER Alpha"


@pytest.mark.asyncio
async def test_users_role_and_active_filters(auth_client, session) -> None:
    await session.execute(User.__table__.delete().where(User.__table__.c.username != "testauth"))
    await session.commit()

    users = await _seed_users(session, 9)

    role_response = await auth_client.get("/api/users?role=planner&limit=50&offset=0")
    assert role_response.status_code == 200
    role_body = role_response.json()
    assert role_body["total"] == sum(1 for user in users if user.role == UserRole.planner)
    assert all(user["role"] == "planner" for user in role_body["users"])

    active_response = await auth_client.get("/api/users?is_active=false&limit=50&offset=0")
    assert active_response.status_code == 200
    active_body = active_response.json()
    assert active_body["total"] == sum(1 for user in users if not user.is_active)
    assert all(user["is_active"] is False for user in active_body["users"])


@pytest.mark.asyncio
async def test_users_section_filter_and_sort(auth_client, session) -> None:
    await session.execute(User.__table__.delete().where(User.__table__.c.username != "testauth"))
    await session.execute(Section.__table__.delete())
    await session.commit()

    section_a = Section(code="USR-SEC-A", name="Section A", is_active=True)
    section_b = Section(code="USR-SEC-B", name="Section B", is_active=True)
    session.add_all([section_a, section_b])
    await session.flush()

    user_a = await _make_user(session, username="section_user_a", full_name="Section User A")
    user_b = await _make_user(session, username="section_user_b", full_name="Section User B")
    await session.execute(
        user_sections.insert(),
        [
            {"user_id": user_a.id, "section_id": section_a.id},
            {"user_id": user_b.id, "section_id": section_b.id},
        ],
    )
    await session.commit()

    filtered = await auth_client.get("/api/users?section=USR-SEC-A&limit=50&offset=0")
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert filtered_body["total"] == 1
    assert filtered_body["users"][0]["username"] == "section_user_a"

    sorted_response = await auth_client.get(
        "/api/users?sort_by=full_name&sort_order=desc&limit=50&offset=0"
    )
    assert sorted_response.status_code == 200
    sorted_names = [user["full_name"] for user in sorted_response.json()["users"]]
    assert sorted_names == sorted(sorted_names, reverse=True)


@pytest.mark.asyncio
async def test_users_linked_hrms_ids_metadata(auth_client, session) -> None:
    await session.execute(User.__table__.delete().where(User.__table__.c.username != "testauth"))
    await session.commit()

    await _make_user(
        session,
        username="linked_one",
        full_name="Linked One",
        hrms_employee_id=42,
    )
    await _make_user(
        session,
        username="linked_two",
        full_name="Linked Two",
        hrms_employee_id=84,
    )
    await _make_user(session, username="plain_user", full_name="Plain User")
    await session.commit()

    response = await auth_client.get("/api/users?limit=10&offset=0")
    assert response.status_code == 200
    body = response.json()
    assert set(body["linked_hrms_ids"]) == {42, 84}