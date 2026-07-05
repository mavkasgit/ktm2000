"""Tests for GET /api/import-templates pagination (limit, offset, total)."""

from __future__ import annotations

import pytest

from app.models.import_template import ImportTemplate


async def _seed_templates(session, count: int) -> list[ImportTemplate]:
    templates: list[ImportTemplate] = []
    for index in range(count):
        template = ImportTemplate(
            name=f"Template {index:03d}",
            code=f"template-{index:03d}",
            button_label=f"Import {index:03d}",
            is_active=True,
            sort_order=index,
            column_mapping={"A": "sku"},
            description=f"Description {index:03d}",
        )
        session.add(template)
        templates.append(template)
    await session.commit()
    return templates


@pytest.mark.asyncio
async def test_import_templates_offset_limit_pagination(client, session) -> None:
    await session.execute(ImportTemplate.__table__.delete())
    await session.commit()

    await _seed_templates(session, 12)

    first_page = await client.get("/api/import-templates?limit=5&offset=0")
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert len(first_body["items"]) == 5
    assert first_body["total"] == 12
    assert first_body["limit"] == 5
    assert first_body["offset"] == 0

    second_page = await client.get("/api/import-templates?limit=5&offset=5")
    assert second_page.status_code == 200
    second_body = second_page.json()
    assert len(second_body["items"]) == 5
    assert second_body["total"] == 12

    first_ids = {item["id"] for item in first_body["items"]}
    second_ids = {item["id"] for item in second_body["items"]}
    assert first_ids.isdisjoint(second_ids)


@pytest.mark.asyncio
async def test_import_templates_default_sort_order(client, session) -> None:
    await session.execute(ImportTemplate.__table__.delete())
    await session.commit()

    await _seed_templates(session, 3)

    response = await client.get("/api/import-templates?limit=10&offset=0")
    assert response.status_code == 200
    body = response.json()
    sort_orders = [item["sort_order"] for item in body["items"]]
    assert sort_orders == sorted(sort_orders)