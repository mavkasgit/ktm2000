"""Tests for GET /api/users pagination (offset, limit, total, search, filters, sort)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.models.section import Section
from app.models.user import User, UserRole, user_sections
from app.services.users_queries import (
    _SORT_COLUMNS,
    _SORT_DEFAULT,
    _SORT_NULLS_LAST_FIELDS,
    VALID_SORT_FIELDS,
)


async def _make_user(
    session,
    *,
    username: str,
    full_name: str,
    role: UserRole = UserRole.viewer,
    is_active: bool = True,
    email: str | None = None,
) -> User:
    user = User(
        username=username,
        email=email or f"{username}@example.com",
        full_name=full_name,
        role=role,
        is_active=is_active,
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
        "/api/users?sort=full_name:desc&limit=50&offset=0"
    )
    assert sorted_response.status_code == 200
    sorted_names = [user["full_name"] for user in sorted_response.json()["users"]]
    assert sorted_names == sorted(sorted_names, reverse=True)


@pytest.mark.asyncio
async def test_users_sort_two_priorities(auth_client, session) -> None:
    """Второй приоритет решает порядок внутри групп с одинаковым первым полем.

    Данные засеяны так, что по ``role`` пары идут одинаковыми группами и
    различается только второй ключ. Ни сортировка по одной колонке, ни
    последовательные ``order_by`` такого порядка не дают.
    """
    await session.execute(User.__table__.delete().where(User.__table__.c.username != "testauth"))
    await session.commit()

    for username, role in [
        ("ms_admin_a", UserRole.admin),
        ("ms_admin_b", UserRole.admin),
        ("ms_viewer_a", UserRole.viewer),
        ("ms_viewer_b", UserRole.viewer),
    ]:
        await _make_user(
            session,
            username=username,
            full_name=f"Name {username}",
            role=role,
        )
    await session.commit()

    response = await auth_client.get("/api/users?sort=role:asc,username:desc&limit=50")
    assert response.status_code == 200, response.text
    usernames = [
        user["username"]
        for user in response.json()["users"]
        if user["username"].startswith("ms_")
    ]
    assert usernames == ["ms_admin_b", "ms_admin_a", "ms_viewer_b", "ms_viewer_a"]


@pytest.mark.asyncio
async def test_users_sort_by_section_subquery(auth_client, session) -> None:
    """Поле ``section`` резолвится в коррелированный скалярный подзапрос.

    Коды участков склеиваются одной строкой через запятую, поэтому сортировка
    идёт по вычисляемому выражению, а не по колонке users. Ключевая проверка
    — что callable из таблицы резолва действительно вызывается на каждый
    запрос (иначе подзапрос был бы построен один раз на импорте).
    """
    await session.execute(User.__table__.delete().where(User.__table__.c.username != "testauth"))
    await session.execute(Section.__table__.delete())
    await session.commit()

    section_a = Section(code="USR-SRT-A", name="Sort A", is_active=True)
    section_b = Section(code="USR-SRT-B", name="Sort B", is_active=True)
    session.add_all([section_a, section_b])
    await session.flush()

    user_a = await _make_user(session, username="sec_sort_a", full_name="Sec A")
    user_b = await _make_user(session, username="sec_sort_b", full_name="Sec B")
    await session.execute(
        user_sections.insert(),
        [
            {"user_id": user_a.id, "section_id": section_a.id},
            {"user_id": user_b.id, "section_id": section_b.id},
        ],
    )
    await session.commit()

    response = await auth_client.get("/api/users?sort=section:asc&limit=50")
    assert response.status_code == 200, response.text
    usernames = [
        user["username"]
        for user in response.json()["users"]
        if user["username"].startswith("sec_sort_")
    ]
    assert usernames == ["sec_sort_a", "sec_sort_b"]


@pytest.mark.asyncio
async def test_users_sort_tiebreaker_breaks_equal_values(auth_client, session) -> None:
    """Равные значения сортировки разложены по PK: порядок строк детерминирован.

    Все ``full_name`` одинаковы, поэтому решает только tiebreaker. UPDATE части
    строк переписывает их в хвост таблицы: физический порядок хранения
    перестаёт совпадать с порядком id, и сортировка без tiebreaker отдаёт его
    вместо возрастающего id — именно это ломало переход между страницами.
    """
    await session.execute(User.__table__.delete().where(User.__table__.c.username != "testauth"))
    await session.commit()

    created: list[User] = []
    for index in range(6):
        created.append(
            await _make_user(
                session,
                username=f"tb_user_{index}",
                full_name="Same Name",
            )
        )
    await session.commit()
    await session.execute(
        text("UPDATE users SET full_name = 'Same Name' WHERE username IN "
             "('tb_user_2','tb_user_3','tb_user_4')")
    )
    await session.commit()
    assert [u.id for u in created] == sorted(u.id for u in created)

    response = await auth_client.get("/api/users?sort=full_name:asc&limit=50")
    assert response.status_code == 200, response.text
    usernames = [
        user["username"]
        for user in response.json()["users"]
        if user["username"].startswith("tb_user_")
    ]
    assert usernames == [f"tb_user_{index}" for index in range(6)]

    # Тот же порядок на странице 2 — строки не «мигают» при постраничном ходе.
    page = await auth_client.get("/api/users?sort=full_name:asc&limit=2&offset=2")
    assert page.status_code == 200, page.text
    page_usernames = [
        user["username"]
        for user in page.json()["users"]
        if user["username"].startswith("tb_user_")
    ]
    assert page_usernames == usernames[2:4]


@pytest.mark.asyncio
async def test_users_sort_nulls_last_in_both_directions(auth_client, session) -> None:
    """Пустой email уходит в конец и при asc, и при desc.

    В Postgres DESC по умолчанию ставит NULL первым: оператор кликнул
    «спустить», а пользователи без почты оказывались наверху списка.
    """
    await session.execute(User.__table__.delete().where(User.__table__.c.username != "testauth"))
    await session.commit()

    for username, email in [("nl_mail_a", "a@example.com"), ("nl_mail_b", "b@example.com")]:
        user = User(username=username, email=email, full_name=f"NL {username}", role=UserRole.viewer)
        session.add(user)
    for username in ("nl_mail_c", "nl_mail_d"):
        session.add(User(username=username, email=None, full_name=f"NL {username}", role=UserRole.viewer))
    await session.commit()

    for order in ("asc", "desc"):
        response = await auth_client.get(f"/api/users?sort=email:{order}&limit=50")
        assert response.status_code == 200, response.text
        usernames = [
            user["username"]
            for user in response.json()["users"]
            if user["username"].startswith("nl_mail_")
        ]
        assert set(usernames[-2:]) == {"nl_mail_c", "nl_mail_d"}, order
        assert set(usernames[:2]) == {"nl_mail_a", "nl_mail_b"}, order


@pytest.mark.asyncio
async def test_users_sort_invalid_field_and_order_400(auth_client, session) -> None:
    """Молчаливый фолбэк запрещён: оператор кликнул шапку и не увидел эффекта.

    Проверяем и контрактные 400 (неизвестное поле, неизвестное направление),
    и то, что сепаратные sort_by/sort_order больше не влияют на порядок:
    FastAPI игнорирует неизвестные query-параметры, поэтому старая форма молча
    дала бы дефолтную сортировку.
    """
    response = await auth_client.get("/api/users?sort=tab_number:asc")
    assert response.status_code == 400

    response2 = await auth_client.get("/api/users?sort=username:sideways")
    assert response2.status_code == 400

    default_order = await auth_client.get("/api/users?limit=50")
    legacy = await auth_client.get("/api/users?sort_by=username&sort_order=desc&limit=50")
    assert legacy.status_code == 200
    assert legacy.json()["users"] == default_order.json()["users"]


def test_users_sort_table_keys_match_valid_fields() -> None:
    """Таблица резолва и набор допустимых полей не разъезжаются.

    Ловит дрейф: поле, добавленное в одну сторону и забытое в другой, дало бы
    либо 400 на существующей колонке, либо поле в контракте без резолва.
    """
    assert set(_SORT_COLUMNS) == VALID_SORT_FIELDS
    assert VALID_SORT_FIELDS == {
        "id", "username", "full_name", "email", "role", "is_active", "created_at", "section",
    }
    assert set(_SORT_NULLS_LAST_FIELDS) <= VALID_SORT_FIELDS
    assert _SORT_DEFAULT.field in VALID_SORT_FIELDS