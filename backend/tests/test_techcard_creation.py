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


@pytest.mark.asyncio
async def test_create_paired_techcard_rejects_different_quantities(client) -> None:
    """«Разное кол-во» убрано: N×A + N×B — инвариант (#67), нарушение → 422."""
    response = await client.post(
        "/api/techcards",
        json={
            "product_id": None,
            "version": "A",
            "processing_type": "paired_processing",
            "is_active": True,
            "quantity_total": 20,
            "quantity_a_per_item": 8,
            "quantity_b_per_item": 12,
        },
    )
    assert response.status_code == 422
    assert "инвариант" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_paired_techcard_equal_quantities_ok(client) -> None:
    """Равные N создаются успешно."""
    response = await client.post(
        "/api/techcards",
        json={
            "product_id": None,
            "version": "A",
            "processing_type": "paired_processing",
            "is_active": True,
            "quantity_total": 16,
            "quantity_a_per_item": 8,
            "quantity_b_per_item": 8,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["quantity_a_per_item"] == 8
    assert body["quantity_b_per_item"] == 8


@pytest.mark.asyncio
async def test_create_paired_techcard_normalizes_partial_quantity(client) -> None:
    """Одиночное значение копируется в оба поля (как миграция 038, #67)."""
    for a, b in ((8, None), (None, 8)):
        response = await client.post(
            "/api/techcards",
            json={
                "product_id": None,
                "version": "A",
                "processing_type": "paired_processing",
                "is_active": True,
                "quantity_a_per_item": a,
                "quantity_b_per_item": b,
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["quantity_a_per_item"] == 8
        assert body["quantity_b_per_item"] == 8


@pytest.mark.asyncio
async def test_patch_paired_techcard_rejects_different_quantities(client) -> None:
    """Patch парной техкарты на «разное кол-во» → 422 (#67)."""
    response = await client.post(
        "/api/techcards",
        json={
            "product_id": None,
            "version": "A",
            "processing_type": "paired_processing",
            "is_active": True,
            "quantity_total": 16,
            "quantity_a_per_item": 8,
            "quantity_b_per_item": 8,
        },
    )
    assert response.status_code == 201
    techcard_id = response.json()["id"]

    resp = await client.patch(
        f"/api/techcards/{techcard_id}",
        json={"quantity_a_per_item": 8, "quantity_b_per_item": 12},
    )
    assert resp.status_code == 422
    assert "инвариант" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_patch_standard_techcard_different_quantities_is_allowed(client, session) -> None:
    """Инвариант касается только парных техкарт — стандартные не блокируются."""
    product = Product(
        sku="TEST-STD-INVARIANT",
        name="Standard",
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
            "quantity_a_per_item": 8,
            "quantity_b_per_item": 12,
        },
    )
    assert response.status_code == 201
