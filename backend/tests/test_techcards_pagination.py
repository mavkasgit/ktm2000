"""Tests for GET /api/techcards pagination (offset, limit, total, search, sort, filters)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.product import Product, ProductType
from app.models.techcard import Techcard, TechcardLine


async def _make_product(session, *, sku: str, name: str | None = None) -> Product:
    product = Product(
        sku=sku,
        name=name or sku,
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
    )
    session.add(product)
    await session.flush()
    return product


async def _make_standard_techcard(session, product: Product, *, quantity_total: int = 10) -> Techcard:
    techcard = Techcard(
        product_id=product.id,
        version="A",
        processing_type="standart_processing",
        is_active=True,
        quantity_total=quantity_total,
    )
    session.add(techcard)
    await session.flush()
    session.add(
        TechcardLine(
            techcard_id=techcard.id,
            component_product_id=product.id,
            quantity=1,
            unit="pcs",
        )
    )
    await session.flush()
    return techcard


async def _make_paired_techcard(
    session,
    *,
    sku_a: str,
    sku_b: str,
    quantity_total: int = 8,
) -> Techcard:
    product_a = await _make_product(session, sku=sku_a)
    product_b = await _make_product(session, sku=sku_b)
    techcard = Techcard(
        product_id=None,
        version="A",
        processing_type="paired_processing",
        is_active=True,
        quantity_total=quantity_total,
        quantity_a_per_item=2,
        quantity_b_per_item=2,
    )
    session.add(techcard)
    await session.flush()
    session.add_all([
        TechcardLine(
            techcard_id=techcard.id,
            component_product_id=product_a.id,
            quantity=2,
            unit="pcs",
        ),
        TechcardLine(
            techcard_id=techcard.id,
            component_product_id=product_b.id,
            quantity=2,
            unit="pcs",
        ),
    ])
    await session.flush()
    return techcard


async def _seed_techcards(session, count: int) -> list[Techcard]:
    techcards: list[Techcard] = []
    for index in range(count):
        product = await _make_product(session, sku=f"TC-STD-{index:03d}")
        techcards.append(await _make_standard_techcard(session, product, quantity_total=index + 1))
    await _make_paired_techcard(
        session,
        sku_a="TC-PAIR-ALPHA",
        sku_b="TC-PAIR-BETA",
        quantity_total=99,
    )
    await session.commit()
    return techcards


@pytest.mark.asyncio
async def test_techcards_offset_limit_pagination(client, session) -> None:
    await session.execute(TechcardLine.__table__.delete())
    await session.execute(Techcard.__table__.delete())
    await session.commit()

    await _seed_techcards(session, 12)

    first_page = await client.get("/api/techcards?limit=5&offset=0")
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert len(first_body["items"]) == 5
    assert first_body["total"] == 13
    assert first_body["limit"] == 5
    assert first_body["offset"] == 0

    second_page = await client.get("/api/techcards?limit=5&offset=5")
    assert second_page.status_code == 200
    second_body = second_page.json()
    assert len(second_body["items"]) == 5
    assert second_body["total"] == 13

    first_ids = {item["id"] for item in first_body["items"]}
    second_ids = {item["id"] for item in second_body["items"]}
    assert first_ids.isdisjoint(second_ids)


@pytest.mark.asyncio
async def test_techcards_processing_type_filter(client, session) -> None:
    await session.execute(TechcardLine.__table__.delete())
    await session.execute(Techcard.__table__.delete())
    await session.commit()

    await _seed_techcards(session, 4)

    paired = await client.get("/api/techcards?processing_type=paired_processing&limit=50&offset=0")
    assert paired.status_code == 200
    paired_body = paired.json()
    assert paired_body["total"] == 1
    assert paired_body["items"][0]["processing_type"] == "paired_processing"
    assert len(paired_body["items"][0]["techcard_lines"]) == 2

    standard = await client.get("/api/techcards?processing_type=standart_processing&limit=50&offset=0")
    assert standard.status_code == 200
    standard_body = standard.json()
    assert standard_body["total"] == 4
    assert all(item["processing_type"] == "standart_processing" for item in standard_body["items"])


@pytest.mark.asyncio
async def test_techcards_search_by_sku(client, session) -> None:
    await session.execute(TechcardLine.__table__.delete())
    await session.execute(Techcard.__table__.delete())
    await session.commit()

    await _seed_techcards(session, 6)

    search_response = await client.get("/api/techcards?search=TC-PAIR-ALPHA&limit=10&offset=0")
    assert search_response.status_code == 200
    search_body = search_response.json()
    assert search_body["total"] == 1
    assert search_body["items"][0]["processing_type"] == "paired_processing"

    standard_search = await client.get("/api/techcards?search=TC-STD-003&limit=10&offset=0")
    assert standard_search.status_code == 200
    standard_body = standard_search.json()
    assert standard_body["total"] == 1
    assert standard_body["items"][0]["product_sku"] == "TC-STD-003"


@pytest.mark.asyncio
async def test_techcards_column_filters_and_sort(client, session) -> None:
    await session.execute(TechcardLine.__table__.delete())
    await session.execute(Techcard.__table__.delete())
    await session.commit()

    await _seed_techcards(session, 5)

    filtered = await client.get("/api/techcards?quantity_total=3&limit=50&offset=0")
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert filtered_body["total"] == 1
    assert filtered_body["items"][0]["quantity_total"] == 3

    sorted_response = await client.get(
        "/api/techcards?processing_type=standart_processing&sort_by=quantity_total&sort_order=asc&limit=50&offset=0"
    )
    assert sorted_response.status_code == 200
    quantities = [item["quantity_total"] for item in sorted_response.json()["items"]]
    assert quantities == sorted(quantities)


@pytest.mark.asyncio
async def test_techcards_limit_max_validation(client) -> None:
    response = await client.get("/api/techcards?limit=1000")
    assert response.status_code == 422