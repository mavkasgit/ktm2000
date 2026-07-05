"""Tests for GET /api/sections pagination (offset, limit, total, search, sort)."""

from __future__ import annotations

import pytest

from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup


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

    response = await client.get("/api/sections?sort_by=sort_order&sort_order=asc&limit=50&offset=0")
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