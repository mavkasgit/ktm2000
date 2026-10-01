"""Tests for GET /api/sections pagination (offset, limit, total, search, sort)."""

from __future__ import annotations

import pytest
from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup
from app.services.sections_queries import (
    _SORT_COLUMNS,
    _SORT_DEFAULT,
    _SORT_NULLS_LAST_FIELDS,
    VALID_SORT_FIELDS,
)
from sqlalchemy import text


async def _seed_sections(session, count: int) -> list[Section]:
    sections: list[Section] = []
    for index in range(count):
        sections.append(
            Section(
                code=f"SEC-PAG-{index:03d}",
                name=f"Paginated Section {index:03d}",
                description=f"Description {index:03d}",
                sort_order=index * 10,
                is_active=index % 3 != 0,
                type="production" if index % 2 == 0 else "raw_stock",
            )
        )
    session.add_all(sections)
    await session.flush()

    spg = StorageProductionGroup(code="SEC-PAG-SPG", name="Pagination SPG")
    session.add(spg)
    await session.flush()
    session.add(SpgSection(spg_id=spg.id, section_id=sections[0].id, sort_order=0))
    await session.commit()
    return sections


@pytest.mark.asyncio
async def test_sections_offset_limit_pagination(client, session) -> None:
    await session.execute(SpgSection.__table__.delete())
    await session.execute(Section.__table__.delete())
    await session.commit()

    await _seed_sections(session, 12)

    first_page = await client.get("/api/sections?limit=5&offset=0")
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert len(first_body["items"]) == 5
    assert first_body["total"] == 12
    assert first_body["limit"] == 5
    assert first_body["offset"] == 0

    second_page = await client.get("/api/sections?limit=5&offset=5")
    assert second_page.status_code == 200
    second_body = second_page.json()
    assert len(second_body["items"]) == 5
    assert second_body["total"] == 12

    first_ids = {item["id"] for item in first_body["items"]}
    second_ids = {item["id"] for item in second_body["items"]}
    assert first_ids.isdisjoint(second_ids)


@pytest.mark.asyncio
async def test_sections_search_and_type_filter(client, session) -> None:
    await session.execute(SpgSection.__table__.delete())
    await session.execute(Section.__table__.delete())
    await session.commit()

    sections = await _seed_sections(session, 8)

    search_response = await client.get("/api/sections?search=SEC-PAG-003&limit=50&offset=0")
    assert search_response.status_code == 200
    search_body = search_response.json()
    assert search_body["total"] == 1
    assert search_body["items"][0]["code"] == "SEC-PAG-003"

    type_response = await client.get("/api/sections?type=raw_stock&limit=50&offset=0")
    assert type_response.status_code == 200
    type_body = type_response.json()
    assert type_body["total"] == sum(1 for section in sections if section.type == "raw_stock")
    assert all(item["type"] == "raw_stock" for item in type_body["items"])


@pytest.mark.asyncio
async def test_sections_sort_by_sort_order(client, session) -> None:
    await session.execute(SpgSection.__table__.delete())
    await session.execute(Section.__table__.delete())
    await session.commit()

    await _seed_sections(session, 6)

    response = await client.get("/api/sections?sort=sort_order:asc&limit=50&offset=0")
    assert response.status_code == 200
    body = response.json()
    sort_orders = [item["sort_order"] for item in body["items"]]
    assert sort_orders == sorted(sort_orders)


@pytest.mark.asyncio
async def test_sections_column_filters(client, session) -> None:
    await session.execute(SpgSection.__table__.delete())
    await session.execute(Section.__table__.delete())
    await session.commit()

    await _seed_sections(session, 5)

    filtered = await client.get("/api/sections?name=Paginated Section 002&limit=50&offset=0")
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert filtered_body["total"] == 1
    assert filtered_body["items"][0]["code"] == "SEC-PAG-002"


@pytest.mark.asyncio
async def test_sections_limit_max_validation(client) -> None:
    response = await client.get("/api/sections?limit=1000")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_sections_sort_two_priorities(client, session) -> None:
    """Второй приоритет решает порядок внутри групп с одинаковым первым полем.

    Данные засеяны так, что по ``type`` пары идут одинаковыми группами и
    различается только второй ключ. Ни сортировка по одной колонке, ни
    последовательные ``order_by`` такого порядка не дают.
    """
    await session.execute(SpgSection.__table__.delete())
    await session.execute(Section.__table__.delete())
    await session.commit()

    for index, (code, type_, sort_order) in enumerate(
        [
            ("SEC-MS-1", "production", 1),
            ("SEC-MS-2", "production", 9),
            ("SEC-MS-3", "raw_stock", 2),
            ("SEC-MS-4", "raw_stock", 8),
        ]
    ):
        session.add(
            Section(code=code, name=f"Multi {index}", type=type_, sort_order=sort_order, is_active=True)
        )
    await session.commit()

    response = await client.get("/api/sections?sort=type:asc,sort_order:desc&limit=50")
    assert response.status_code == 200, response.text
    codes = [item["code"] for item in response.json()["items"]]
    assert codes == ["SEC-MS-2", "SEC-MS-1", "SEC-MS-4", "SEC-MS-3"]


@pytest.mark.asyncio
async def test_sections_sort_tiebreaker_breaks_equal_values(client, session) -> None:
    """Равные значения сортировки разложены по PK: порядок строк детерминирован.

    Все ``sort_order`` одинаковы, поэтому решает только tiebreaker. UPDATE
    части строк переписывает их в хвост таблицы: физический порядок хранения
    перестаёт совпадать с порядком id, и сортировка без tiebreaker отдаёт его
    вместо возрастающего id — именно это ломало переход между страницами.
    """
    await session.execute(SpgSection.__table__.delete())
    await session.execute(Section.__table__.delete())
    await session.commit()

    created: list[Section] = []
    for index in range(6):
        section = Section(
            code=f"SEC-TB-{index}",
            name=f"Tie {index}",
            type="production",
            sort_order=0,
            is_active=True,
        )
        session.add(section)
        await session.flush()
        created.append(section)
    await session.commit()
    await session.execute(
        text("UPDATE sections SET sort_order = 0 WHERE code IN ('SEC-TB-2','SEC-TB-3','SEC-TB-4')")
    )
    await session.commit()
    assert [s.id for s in created] == sorted(s.id for s in created)

    response = await client.get("/api/sections?sort=sort_order:asc&limit=50")
    assert response.status_code == 200, response.text
    codes = [item["code"] for item in response.json()["items"]]
    assert codes == [f"SEC-TB-{index}" for index in range(6)]

    # Тот же порядок на странице 2 — строки не «мигают» при постраничном ходе.
    page = await client.get("/api/sections?sort=sort_order:asc&limit=2&offset=2")
    assert page.status_code == 200, page.text
    assert [item["code"] for item in page.json()["items"]] == codes[2:4]


@pytest.mark.asyncio
async def test_sections_sort_nulls_last_in_both_directions(client, session) -> None:
    """Пустое описание уходит в конец и при asc, и при desc.

    В Postgres DESC по умолчанию ставит NULL первым: оператор кликнул
    «спустить», а незаполненные описания оказывались наверху списка.
    """
    await session.execute(SpgSection.__table__.delete())
    await session.execute(Section.__table__.delete())
    await session.commit()

    session.add_all(
        [
            Section(code="SEC-NL-1", name="NL1", description="Alpha", type="production", is_active=True),
            Section(code="SEC-NL-2", name="NL2", description="Beta", type="production", is_active=True),
            Section(code="SEC-NL-3", name="NL3", description=None, type="production", is_active=True),
            Section(code="SEC-NL-4", name="NL4", description=None, type="production", is_active=True),
        ]
    )
    await session.commit()

    for order in ("asc", "desc"):
        response = await client.get(f"/api/sections?sort=description:{order}&limit=50")
        assert response.status_code == 200, response.text
        codes = [item["code"] for item in response.json()["items"]]
        assert set(codes[-2:]) == {"SEC-NL-3", "SEC-NL-4"}, order
        assert set(codes[:2]) == {"SEC-NL-1", "SEC-NL-2"}, order


@pytest.mark.asyncio
async def test_sections_sort_invalid_field_and_order_400(client, session) -> None:
    """Молчаливый фолбэк запрещён: оператор кликнул шапку и не увидел эффекта.

    Проверяем и контрактные 400 (неизвестное поле, неизвестное направление),
    и то, что сепаратные sort_by/sort_order больше не влияют на порядок:
    FastAPI игнорирует неизвестные query-параметры, поэтому старая форма молча
    дала бы дефолтную сортировку.
    """
    await session.execute(SpgSection.__table__.delete())
    await session.execute(Section.__table__.delete())
    await session.commit()
    await _seed_sections(session, 2)

    unknown_field = await client.get("/api/sections?sort=icon:asc")
    assert unknown_field.status_code == 400

    unknown_order = await client.get("/api/sections?sort=name:sideways")
    assert unknown_order.status_code == 400

    default_order = await client.get("/api/sections?limit=50")
    legacy = await client.get("/api/sections?sort_by=name&sort_order=desc&limit=50")
    assert legacy.status_code == 200
    assert legacy.json()["items"] == default_order.json()["items"]


def test_sections_sort_table_keys_match_valid_fields() -> None:
    """Таблица резолва и набор допустимых полей не разъезжаются.

    Ловит дрейф: поле, добавленное в одну сторону и забытое в другой, дало бы
    либо 400 на существующей колонке, либо поле в контракте без резолва.
    """
    assert set(_SORT_COLUMNS) == VALID_SORT_FIELDS
    assert {
        "id", "code", "name", "type", "sort_order", "description", "is_active",
    } == VALID_SORT_FIELDS
    assert set(_SORT_NULLS_LAST_FIELDS) <= VALID_SORT_FIELDS
    assert _SORT_DEFAULT.field in VALID_SORT_FIELDS