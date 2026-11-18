"""Сторонний 3D-заказ «урны» и ручная норма на подвес (T-380, спека 0003).

Контракт через API справочника артикулов:

- ``dimension_state=volume`` без длин принимает ручную норму с ключом
  ``default``: ``quantity_per_hanger.default.manual = 8``;
- ``attributes`` стороннего заказа (``third_party``, ``customer``, ``pack``)
  отдаются карточкой;
- ``volume`` + непустые длины — 422 (правило «длины только для 1D»);
- без ручной нормы у ``volume`` работает прежняя формула по площади;
- у ``length``-артикула норма по длине не меняется.

Фикстура `урны` — данные из спеки 0003: 4 комплекта по 2 предмета = 8 шт.
"""
from __future__ import annotations

import pytest
from app.models.dimension import DimensionType, ProductDimension
from app.models.product import Product
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def urn_payload(**overrides) -> dict:
    """Данные продукта «урны» из спеки 0003 (фикстура, не прод-БД)."""
    payload = {
        "sku": "урны",
        "name": "Урны, комплект 2 шт (корпус + крышка)",
        "type": "component",
        "unit": "шт",
        "dimension_state": "volume",
        "third_party": True,
        "customer": "ГорКомплекс",
        "pack": {"sets_per_hanger": 4, "pieces_per_set": 2},
        "hanger_mode": "manual",
        "quantity_per_hanger": {"default": {"manual": 8}},
        "source": "manual",
        "is_catalog_item": True,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_create_volume_product_with_manual_default(client, session: AsyncSession) -> None:
    """Урны: volume без длин, ручная норма 8 с ключом default — создаются."""
    resp = await client.post("/api/products", json=urn_payload())

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["dimension_state"] == "volume"
    assert body["lengths"] == []
    assert body["hanger_mode"] == "manual"
    assert body["third_party"] is True
    assert body["customer"] == "ГорКомплекс"
    assert body["pack"] == {"sets_per_hanger": 4, "pieces_per_set": 2}
    assert body["quantity_per_hanger"] == {"default": {"auto": None, "manual": 8}}


@pytest.mark.asyncio
async def test_get_returns_third_party_attributes_and_manual_default(client) -> None:
    """Карточка урн отдаёт отметку стороннего заказа, заказчика, комплект и норму."""
    created = (await client.post("/api/products", json=urn_payload())).json()

    resp = await client.get(f"/api/products/{created['id']}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sku"] == "урны"
    assert body["name"] == "Урны, комплект 2 шт (корпус + крышка)"
    assert body["is_catalog_item"] is True
    assert body["third_party"] is True
    assert body["customer"] == "ГорКомплекс"
    assert body["pack"] == {"sets_per_hanger": 4, "pieces_per_set": 2}
    assert body["quantity_per_hanger"]["default"]["manual"] == 8


@pytest.mark.asyncio
async def test_volume_manual_default_is_the_norm(client, session: AsyncSession) -> None:
    """Норма урн — 8: ручное значение default, а не расчёт по площади."""
    pid = (await client.post("/api/products", json=urn_payload())).json()["id"]

    product = await session.get(Product, pid, populate_existing=True)

    assert product is not None
    assert product.quantity_per_hanger == 8
    assert product.quantity_per_hanger_default == 8


@pytest.mark.asyncio
async def test_volume_with_lengths_is_rejected(client) -> None:
    """Правило «длины только для 1D» не меняется: volume + длины → 422."""
    resp = await client.post(
        "/api/products",
        json=urn_payload(
            sku="урны-с-длинами",
            lengths=[{"length_mm": 1000, "is_primary": True}],
        ),
    )

    assert resp.status_code == 422, resp.text
    assert "линейным" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_volume_without_manual_keeps_sheet_formula(
    client, session: AsyncSession
) -> None:
    """Без ручной нормы у volume остаётся прежняя формула по площади."""
    for code in ("length_mm", "width_mm", "height_mm"):
        session.add(DimensionType(code=code, name=code, unit="мм", value_type="number"))
    await session.flush()

    created = await client.post(
        "/api/products",
        json=urn_payload(
            sku="урны-без-нормы",
            quantity_per_hanger=None,
            hanger_mode="auto",
        ),
    )
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    assert created.json()["quantity_per_hanger"] is None

    for code, value in (("length_mm", 1000.0), ("width_mm", 500.0), ("height_mm", 300.0)):
        dim_type = await session.scalar(
            select(DimensionType).where(DimensionType.code == code)
        )
        assert dim_type is not None
        session.add(
            ProductDimension(
                product_id=pid,
                dimension_type_id=dim_type.id,
                default_value=value,
            )
        )
    await session.commit()

    resp = await client.get(f"/api/products/{pid}")

    assert resp.status_code == 200, resp.text
    # floor(9_000_000 / (1000*500)) = 18 — формула листов, как раньше.
    assert resp.json()["quantity_per_hanger"] == {"1000": {"auto": 18, "manual": None}}


@pytest.mark.asyncio
async def test_length_product_norm_unchanged(client) -> None:
    """Обычный length-артикул считает норму по длине, как раньше."""
    resp = await client.post(
        "/api/products",
        json={
            "sku": "профиль-длины",
            "name": "Профиль по длинам",
            "type": "component",
            "unit": "pcs",
            "hanger_mode": "manual",
            "lengths": [
                {"length_mm": 2800, "is_primary": True},
                {"length_mm": 3500, "is_primary": False},
            ],
            "quantity_per_hanger": {"2800": {"manual": 60}, "3500": {"manual": 48}},
        },
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["third_party"] is False
    assert body["customer"] is None
    assert body["quantity_per_hanger"] == {
        "2800": {"auto": None, "manual": 60},
        "3500": {"auto": None, "manual": 48},
    }


@pytest.mark.asyncio
async def test_patch_sets_manual_default_on_existing_volume(client) -> None:
    """Норму урн можно задать после создания: PATCH default.manual = 8."""
    created = await client.post(
        "/api/products",
        json=urn_payload(sku="урны-patch", quantity_per_hanger=None, hanger_mode=None),
    )
    assert created.status_code == 201, created.text
    pid = created.json()["id"]

    resp = await client.patch(
        f"/api/products/{pid}",
        json={"hanger_mode": "manual", "quantity_per_hanger": {"default": {"manual": 8}}},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["quantity_per_hanger"] == {"default": {"auto": None, "manual": 8}}

    got = await client.get(f"/api/products/{pid}")
    assert got.json()["quantity_per_hanger"]["default"]["manual"] == 8


@pytest.mark.asyncio
async def test_default_norm_key_rejected_for_length_product(client) -> None:
    """У length-артикула норма по длине: ключ default не принимается."""
    resp = await client.post(
        "/api/products",
        json={
            "sku": "профиль-default",
            "name": "Профиль",
            "type": "component",
            "hanger_mode": "manual",
            "lengths": [{"length_mm": 2800, "is_primary": True}],
            "quantity_per_hanger": {"default": {"manual": 8}},
        },
    )

    assert resp.status_code == 422, resp.text
    assert "default" in resp.json()["detail"]
