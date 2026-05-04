import pytest
from sqlalchemy import select

from app.models.product import Product, ProductType
from app.models.techcard import Techcard, TechcardLine


@pytest.mark.asyncio
async def test_create_standard_techcard_auto_creates_line(client, session) -> None:
    """Standard techcard should auto-create a techcard line with product as component."""
    product = Product(
        sku="TEST-STD-001",
        name="Test Standard Product",
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
    )
    session.add(product)
    await session.commit()

    response = await client.post(
        "/api/techcards",
        json={
            "product_id": product.id,
            "version": "A",
            "processing_type": "standart_processing",
            "is_active": True,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["product_id"] == product.id
    assert body["processing_type"] == "standart_processing"

    line = await session.scalar(
        select(TechcardLine).where(TechcardLine.techcard_id == body["id"])
    )
    assert line is not None
    assert line.component_product_id == product.id
    assert line.quantity == 1
    assert line.unit == "pcs"


@pytest.mark.asyncio
async def test_create_paired_techcard_no_auto_line(client, session) -> None:
    """Paired techcard should NOT auto-create lines; they must be added manually."""
    comp_a = Product(
        sku="TEST-PAIR-A",
        name="Paired Profile A",
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
        is_paired_profile=True,
    )
    comp_b = Product(
        sku="TEST-PAIR-B",
        name="Paired Profile B",
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
        is_paired_profile=True,
    )
    session.add_all([comp_a, comp_b])
    await session.commit()

    response = await client.post(
        "/api/techcards",
        json={
            "product_id": None,
            "version": "A",
            "processing_type": "paired_processing",
            "is_active": True,
            "quantity_total": 2,
            "quantity_a_per_item": 1,
            "quantity_b_per_item": 1,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["product_id"] is None
    assert body["processing_type"] == "paired_processing"

    lines = (
        await session.execute(
            select(TechcardLine).where(TechcardLine.techcard_id == body["id"])
        )
    ).scalars().all()
    assert len(lines) == 0

    # Now add lines manually via API (as frontend does)
    resp_a = await client.post(
        f"/api/techcards/{body['id']}/lines",
        json={"component_product_id": comp_a.id, "quantity": 1, "unit": "pcs"},
    )
    assert resp_a.status_code == 201

    resp_b = await client.post(
        f"/api/techcards/{body['id']}/lines",
        json={"component_product_id": comp_b.id, "quantity": 1, "unit": "pcs"},
    )
    assert resp_b.status_code == 201

    all_lines = (
        await session.execute(
            select(TechcardLine).where(TechcardLine.techcard_id == body["id"]).order_by(TechcardLine.id)
        )
    ).scalars().all()
    assert len(all_lines) == 2
    assert all_lines[0].component_product_id == comp_a.id
    assert all_lines[1].component_product_id == comp_b.id
