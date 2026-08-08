"""Product dimensions in GET /api/products list response.

Проверяет что поле `dimensions` (code → default_value) correctly populated
для 2D/3D продуктов и отсутствует для 1D.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dimension import DimensionType, ProductDimension
from app.models.product import Product, ProductType, DimensionState


async def _make_product(
    session: AsyncSession,
    *,
    sku: str,
    name: str = "Test Product",
    dimension_state: str = "length",
) -> Product:
    product = Product(
        sku=sku,
        name=name,
        type=ProductType.component,
        unit="pcs",
        is_active=True,
        dimension_state=DimensionState(dimension_state),
    )
    session.add(product)
    await session.flush()
    return product


async def _make_dimension_type(
    session: AsyncSession,
    *,
    code: str,
    name: str = "Dim",
    unit: str = "мм",
) -> DimensionType:
    dim_type = DimensionType(code=code, name=name, unit=unit, value_type="number")
    session.add(dim_type)
    await session.flush()
    return dim_type


async def _make_link(
    session: AsyncSession,
    *,
    product_id: int,
    dimension_type_id: int,
    default_value: float | None = None,
) -> ProductDimension:
    link = ProductDimension(
        product_id=product_id,
        dimension_type_id=dimension_type_id,
        default_value=default_value,
    )
    session.add(link)
    await session.flush()
    return link


# --- 1D: dimensions field is null -----------------------------------------------


@pytest.mark.asyncio
async def test_product_list_1d_has_no_dimensions(client, session: AsyncSession) -> None:
    product = await _make_product(session, sku="DIM-1D-001", dimension_state="length")
    await session.commit()

    response = await client.get(f"/api/products?sku=DIM-1D-001")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["dimensions"] is None


# --- 2D: dimensions field populated with length_mm, width_mm, thickness_mm ------


@pytest.mark.asyncio
async def test_product_list_2d_has_dimensions(client, session: AsyncSession) -> None:
    product = await _make_product(session, sku="DIM-2D-001", dimension_state="area")
    length_type = await _make_dimension_type(session, code="length_mm", name="Длина")
    width_type = await _make_dimension_type(session, code="width_mm", name="Ширина")
    thickness_type = await _make_dimension_type(session, code="thickness_mm", name="Толщина")
    await _make_link(session, product_id=product.id, dimension_type_id=length_type.id, default_value=1200.0)
    await _make_link(session, product_id=product.id, dimension_type_id=width_type.id, default_value=800.0)
    await _make_link(session, product_id=product.id, dimension_type_id=thickness_type.id, default_value=2.0)
    await session.commit()

    response = await client.get(f"/api/products?sku=DIM-2D-001")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    dims = items[0]["dimensions"]
    assert dims is not None
    assert dims["length_mm"] == 1200.0
    assert dims["width_mm"] == 800.0
    assert dims["thickness_mm"] == 2.0


@pytest.mark.asyncio
async def test_product_list_2d_partial_dimensions(client, session: AsyncSession) -> None:
    """2D с только length_mm и thickness_mm (width_mm не заполнен)."""
    product = await _make_product(session, sku="DIM-2D-002", dimension_state="area")
    length_type = await _make_dimension_type(session, code="length_mm", name="Длина")
    thickness_type = await _make_dimension_type(session, code="thickness_mm", name="Толщина")
    await _make_link(session, product_id=product.id, dimension_type_id=length_type.id, default_value=1500.0)
    await _make_link(session, product_id=product.id, dimension_type_id=thickness_type.id, default_value=3.0)
    await session.commit()

    response = await client.get(f"/api/products?sku=DIM-2D-002")
    assert response.status_code == 200
    dims = response.json()["items"][0]["dimensions"]
    assert dims is not None
    assert dims["length_mm"] == 1500.0
    assert dims["thickness_mm"] == 3.0
    assert "width_mm" not in dims


@pytest.mark.asyncio
async def test_product_list_2d_link_without_value_excluded(client, session: AsyncSession) -> None:
    """Связь без default_value не попадает в dimensions."""
    product = await _make_product(session, sku="DIM-2D-003", dimension_state="area")
    length_type = await _make_dimension_type(session, code="length_mm", name="Длина")
    width_type = await _make_dimension_type(session, code="width_mm", name="Ширина")
    await _make_link(session, product_id=product.id, dimension_type_id=length_type.id, default_value=1200.0)
    await _make_link(session, product_id=product.id, dimension_type_id=width_type.id, default_value=None)
    await session.commit()

    response = await client.get(f"/api/products?sku=DIM-2D-003")
    assert response.status_code == 200
    dims = response.json()["items"][0]["dimensions"]
    assert dims is not None
    assert dims["length_mm"] == 1200.0
    assert "width_mm" not in dims


# --- 3D: dimensions field populated with length_mm, width_mm, height_mm ---------


@pytest.mark.asyncio
async def test_product_list_3d_has_dimensions(client, session: AsyncSession) -> None:
    product = await _make_product(session, sku="DIM-3D-001", dimension_state="volume")
    length_type = await _make_dimension_type(session, code="length_mm", name="Длина")
    width_type = await _make_dimension_type(session, code="width_mm", name="Ширина")
    height_type = await _make_dimension_type(session, code="height_mm", name="Высота")
    await _make_link(session, product_id=product.id, dimension_type_id=length_type.id, default_value=2000.0)
    await _make_link(session, product_id=product.id, dimension_type_id=width_type.id, default_value=1000.0)
    await _make_link(session, product_id=product.id, dimension_type_id=height_type.id, default_value=500.0)
    await session.commit()

    response = await client.get(f"/api/products?sku=DIM-3D-001")
    assert response.status_code == 200
    dims = response.json()["items"][0]["dimensions"]
    assert dims is not None
    assert dims["length_mm"] == 2000.0
    assert dims["width_mm"] == 1000.0
    assert dims["height_mm"] == 500.0


# --- Create dimension link then verify in list ----------------------------------


@pytest.mark.asyncio
async def test_create_dimension_then_appear_in_list(client, session: AsyncSession) -> None:
    """Создание связи через API → появляется в списке продуктов."""
    product = await _make_product(session, sku="DIM-CRT-001", dimension_state="area")
    length_type = await _make_dimension_type(session, code="length_mm", name="Длина")
    width_type = await _make_dimension_type(session, code="width_mm", name="Ширина")
    await session.commit()

    # Создаём связи через API
    resp1 = await client.post(
        f"/api/products/{product.id}/dimensions",
        json={"dimension_type_id": length_type.id, "default_value": 1200.0},
    )
    assert resp1.status_code == 201

    resp2 = await client.post(
        f"/api/products/{product.id}/dimensions",
        json={"dimension_type_id": width_type.id, "default_value": 800.0},
    )
    assert resp2.status_code == 201

    # Проверяем что dimensions в списке
    response = await client.get(f"/api/products?sku=DIM-CRT-001")
    assert response.status_code == 200
    dims = response.json()["items"][0]["dimensions"]
    assert dims is not None
    assert dims["length_mm"] == 1200.0
    assert dims["width_mm"] == 800.0


# --- Patch dimension then verify in list ----------------------------------------


@pytest.mark.asyncio
async def test_patch_dimension_reflected_in_list(client, session: AsyncSession) -> None:
    """Изменение default_value через API → обновляется в списке."""
    product = await _make_product(session, sku="DIM-PTC-001", dimension_state="area")
    length_type = await _make_dimension_type(session, code="length_mm", name="Длина")
    link = await _make_link(
        session, product_id=product.id, dimension_type_id=length_type.id, default_value=1000.0,
    )
    await session.commit()

    # Проверяем начальное значение
    response = await client.get(f"/api/products?sku=DIM-PTC-001")
    assert response.json()["items"][0]["dimensions"]["length_mm"] == 1000.0

    # Обновляем через API
    patch_resp = await client.patch(
        f"/api/products/{product.id}/dimensions/{link.id}",
        json={"default_value": 2500.0},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["default_value"] == 2500.0

    # Проверяем что обновилось в списке
    response = await client.get(f"/api/products?sku=DIM-PTC-001")
    assert response.json()["items"][0]["dimensions"]["length_mm"] == 2500.0


# --- Delete dimension then verify in list ---------------------------------------


@pytest.mark.asyncio
async def test_delete_dimension_removed_from_list(client, session: AsyncSession) -> None:
    """Удаление связи → поле исчезает из dimensions."""
    product = await _make_product(session, sku="DIM-DEL-001", dimension_state="area")
    length_type = await _make_dimension_type(session, code="length_mm", name="Длина")
    width_type = await _make_dimension_type(session, code="width_mm", name="Ширина")
    link_l = await _make_link(session, product_id=product.id, dimension_type_id=length_type.id, default_value=1200.0)
    await _make_link(session, product_id=product.id, dimension_type_id=width_type.id, default_value=800.0)
    await session.commit()

    # Проверяем что оба есть
    response = await client.get(f"/api/products?sku=DIM-DEL-001")
    dims = response.json()["items"][0]["dimensions"]
    assert "length_mm" in dims
    assert "width_mm" in dims

    # Удаляем length_mm
    del_resp = await client.delete(f"/api/products/{product.id}/dimensions/{link_l.id}")
    assert del_resp.status_code == 204

    # Проверяем что остался только width_mm
    response = await client.get(f"/api/products?sku=DIM-DEL-001")
    dims = response.json()["items"][0]["dimensions"]
    assert dims is not None
    assert "length_mm" not in dims
    assert dims["width_mm"] == 800.0


# --- Multiple products with different dimension states --------------------------


@pytest.mark.asyncio
async def test_mixed_dimension_states_in_list(client, session: AsyncSession) -> None:
    """1D и 2D продукты в одном ответе — каждый со своим dimensions."""
    prod_1d = await _make_product(session, sku="DIM-MIX-1D", dimension_state="length")
    prod_2d = await _make_product(session, sku="DIM-MIX-2D", dimension_state="area")
    length_type = await _make_dimension_type(session, code="length_mm", name="Длина")
    width_type = await _make_dimension_type(session, code="width_mm", name="Ширина")
    thickness_type = await _make_dimension_type(session, code="thickness_mm", name="Толщина")
    await _make_link(session, product_id=prod_2d.id, dimension_type_id=length_type.id, default_value=1200.0)
    await _make_link(session, product_id=prod_2d.id, dimension_type_id=width_type.id, default_value=800.0)
    await _make_link(session, product_id=prod_2d.id, dimension_type_id=thickness_type.id, default_value=2.0)
    await session.commit()

    response = await client.get("/api/products?sku=DIM-MIX-")
    assert response.status_code == 200
    items = {item["sku"]: item for item in response.json()["items"]}

    assert items["DIM-MIX-1D"]["dimensions"] is None
    assert items["DIM-MIX-2D"]["dimensions"] == {
        "length_mm": 1200.0,
        "width_mm": 800.0,
        "thickness_mm": 2.0,
    }
