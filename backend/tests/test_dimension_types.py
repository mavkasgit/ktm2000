"""CRUD справочника измерений + привязок к продукту и helper resolve_product_dimensions."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dimension import DimensionType, ProductDimension
from app.models.product import Product, ProductType
from app.services.dimension_validation import MissingDimensionsError, resolve_product_dimensions


async def _make_product(session: AsyncSession, *, sku: str, length_mm: float | None = None) -> Product:
    product = Product(
        sku=sku,
        name=f"Product {sku}",
        type=ProductType.component,
        unit="pcs",
        is_active=True,
        length_mm=length_mm,
    )
    session.add(product)
    await session.flush()
    return product


async def _make_dimension_type(
    session: AsyncSession,
    *,
    code: str,
    name: str = "Длина",
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
    is_required: bool = False,
    default_value: float | None = None,
) -> ProductDimension:
    link = ProductDimension(
        product_id=product_id,
        dimension_type_id=dimension_type_id,
        is_required=is_required,
        default_value=default_value,
    )
    session.add(link)
    await session.flush()
    return link


# --- CRUD справочника dimension_types --------------------------------------------


@pytest.mark.asyncio
async def test_dimension_type_crud(client, session: AsyncSession) -> None:
    created = await client.post(
        "/api/dimension-types",
        json={"code": "width_mm", "name": "Ширина", "unit": "мм"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["code"] == "width_mm"
    assert body["value_type"] == "number"
    type_id = body["id"]

    listed = await client.get("/api/dimension-types")
    assert listed.status_code == 200
    assert any(t["id"] == type_id for t in listed.json())

    patched = await client.patch(f"/api/dimension-types/{type_id}", json={"name": "Ширина листа"})
    assert patched.status_code == 200
    assert patched.json()["name"] == "Ширина листа"

    deleted = await client.delete(f"/api/dimension-types/{type_id}")
    assert deleted.status_code == 204

    listed_after = await client.get("/api/dimension-types")
    assert all(t["id"] != type_id for t in listed_after.json())


@pytest.mark.asyncio
async def test_dimension_type_duplicate_code_rejected(client, session: AsyncSession) -> None:
    await _make_dimension_type(session, code="height_mm", name="Высота")
    await session.commit()

    duplicate = await client.post(
        "/api/dimension-types",
        json={"code": "height_mm", "name": "Высота 2", "unit": "мм"},
    )
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_dimension_type_delete_blocked_when_linked(client, session: AsyncSession) -> None:
    product = await _make_product(session, sku="DIM-DEL-001")
    dim_type = await _make_dimension_type(session, code="linked_mm", name="Связанное")
    await _make_link(session, product_id=product.id, dimension_type_id=dim_type.id)
    await session.commit()

    deleted = await client.delete(f"/api/dimension-types/{dim_type.id}")
    assert deleted.status_code == 409


# --- CRUD привязок продукта -------------------------------------------------------


@pytest.mark.asyncio
async def test_product_dimension_crud(client, session: AsyncSession) -> None:
    product = await _make_product(session, sku="DIM-CRUD-001")
    dim_type = await _make_dimension_type(session, code="crud_len_mm")
    await session.commit()

    created = await client.post(
        f"/api/products/{product.id}/dimensions",
        json={"dimension_type_id": dim_type.id, "is_required": True, "default_value": 2700.0},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["product_id"] == product.id
    assert body["is_required"] is True
    assert body["default_value"] == 2700.0
    assert body["dimension_type"]["code"] == "crud_len_mm"
    link_id = body["id"]

    listed = await client.get(f"/api/products/{product.id}/dimensions")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [link_id]

    duplicate = await client.post(
        f"/api/products/{product.id}/dimensions",
        json={"dimension_type_id": dim_type.id},
    )
    assert duplicate.status_code == 409

    patched = await client.patch(
        f"/api/products/{product.id}/dimensions/{link_id}",
        json={"is_required": False, "default_value": 3000.0},
    )
    assert patched.status_code == 200
    assert patched.json()["is_required"] is False
    assert patched.json()["default_value"] == 3000.0

    deleted = await client.delete(f"/api/products/{product.id}/dimensions/{link_id}")
    assert deleted.status_code == 204

    listed_after = await client.get(f"/api/products/{product.id}/dimensions")
    assert listed_after.json() == []


@pytest.mark.asyncio
async def test_product_dimension_unknown_product_or_type(client, session: AsyncSession) -> None:
    product = await _make_product(session, sku="DIM-404-001")
    await session.commit()

    missing_product = await client.get("/api/products/999999/dimensions")
    assert missing_product.status_code == 404

    missing_type = await client.post(
        f"/api/products/{product.id}/dimensions",
        json={"dimension_type_id": 999999},
    )
    assert missing_type.status_code == 404


# --- Helper resolve_product_dimensions --------------------------------------------


@pytest.mark.asyncio
async def test_resolve_keeps_explicit_value(session: AsyncSession) -> None:
    product = await _make_product(session, sku="DIM-RES-001")
    dim_type = await _make_dimension_type(session, code="res_len_mm")
    await _make_link(
        session, product_id=product.id, dimension_type_id=dim_type.id,
        is_required=True, default_value=2700.0,
    )

    result = await resolve_product_dimensions(session, product.id, {"res_len_mm": 1800.0})
    assert result == {"res_len_mm": 1800.0}


@pytest.mark.asyncio
async def test_resolve_substitutes_default_value(session: AsyncSession) -> None:
    product = await _make_product(session, sku="DIM-RES-002")
    dim_type = await _make_dimension_type(session, code="res_def_mm")
    await _make_link(
        session, product_id=product.id, dimension_type_id=dim_type.id,
        is_required=True, default_value=2700.0,
    )

    # значение отсутствует → подставляется типовой размер
    result = await resolve_product_dimensions(session, product.id, None)
    assert result == {"res_def_mm": 2700.0}

    # значение None во входе → тоже подставляется
    result = await resolve_product_dimensions(session, product.id, {"res_def_mm": None})
    assert result == {"res_def_mm": 2700.0}


@pytest.mark.asyncio
async def test_resolve_required_without_default_raises(session: AsyncSession) -> None:
    product = await _make_product(session, sku="DIM-RES-003")
    dim_type = await _make_dimension_type(session, code="res_req_mm")
    await _make_link(
        session, product_id=product.id, dimension_type_id=dim_type.id,
        is_required=True, default_value=None,
    )

    with pytest.raises(MissingDimensionsError) as exc_info:
        await resolve_product_dimensions(session, product.id, None)
    assert exc_info.value.missing_codes == ["res_req_mm"]


@pytest.mark.asyncio
async def test_resolve_product_without_links_passthrough(session: AsyncSession) -> None:
    product = await _make_product(session, sku="DIM-RES-004")

    assert await resolve_product_dimensions(session, product.id, None) is None
    passthrough = {"custom_mm": 500.0}
    assert await resolve_product_dimensions(session, product.id, passthrough) == passthrough
