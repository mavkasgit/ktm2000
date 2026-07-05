"""Server-side column filters and sort for GET /api/products."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product, ProductLength, ProductType


async def _make_product(
    session: AsyncSession,
    *,
    sku: str,
    name: str,
    lengths_mm: list[float] | None = None,
) -> Product:
    product = Product(
        sku=sku,
        name=name,
        type=ProductType.component,
        unit="pcs",
        is_active=True,
    )
    session.add(product)
    await session.flush()
    for length_mm in lengths_mm or []:
        session.add(ProductLength(product_id=product.id, length_mm=length_mm))
    await session.flush()
    return product


@pytest.mark.asyncio
async def test_products_filter_sku_param(client, session: AsyncSession) -> None:
    target = await _make_product(session, sku="RM-UNIQUE-777", name="Target Product")
    for i in range(55):
        await _make_product(session, sku=f"RM-AAA-{i:03d}", name=f"Page filler {i}")
    await session.commit()

    first_page = await client.get("/api/products?limit=50&offset=0")
    assert first_page.status_code == 200
    first_page_body = first_page.json()
    first_page_skus = {item["sku"] for item in first_page_body["items"]}
    assert target.sku not in first_page_skus

    filtered = await client.get("/api/products?sku=UNIQUE-777&limit=50&offset=0")
    assert filtered.status_code == 200
    body = filtered.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["sku"] == "RM-UNIQUE-777"
    assert filtered.headers["x-total-count"] == "1"


@pytest.mark.asyncio
async def test_products_sort_name_asc(client, session: AsyncSession) -> None:
    await _make_product(session, sku="RM-SORT-Z", name="Zulu Profile")
    await _make_product(session, sku="RM-SORT-A", name="Alpha Profile")
    await _make_product(session, sku="RM-SORT-M", name="Mike Profile")
    await session.commit()

    response = await client.get("/api/products?sort=name:asc&limit=50")
    assert response.status_code == 200
    names = [item["name"] for item in response.json()["items"] if item["sku"].startswith("RM-SORT-")]
    assert names == ["Alpha Profile", "Mike Profile", "Zulu Profile"]