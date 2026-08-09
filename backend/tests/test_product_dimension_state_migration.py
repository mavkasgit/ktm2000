"""Миграция product_dimensions при смене dimension_state (Ref #72).

При переключении 1D → 2D/3D продукт должен получить связи product_dimensions
для полей новой размерности (length_mm, width_mm, thickness_mm / height_mm),
а связи полей, не входящих в новую размерность, должны быть удалены
(толщина ↔ высота при переходе area ↔ volume). Значения существующих полей
(длина, ширина) сохраняются.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.dimension import DimensionType, ProductDimension


async def _seed_types(session: AsyncSession) -> None:
    for code in ("length_mm", "width_mm", "thickness_mm", "height_mm"):
        session.add(
            DimensionType(code=code, name=code, unit="мм", value_type="number")
        )
    await session.flush()


async def _add_link(
    session: AsyncSession,
    product_id: int,
    code: str,
    default_value: float | None = None,
) -> None:
    dim_type = await session.scalar(select(DimensionType).where(DimensionType.code == code))
    assert dim_type is not None, f"DimensionType '{code}' not seeded"
    session.add(
        ProductDimension(
            product_id=product_id,
            dimension_type_id=dim_type.id,
            default_value=default_value,
        )
    )
    await session.flush()


async def _link_codes(session: AsyncSession, product_id: int) -> set[str]:
    """Коды dimension_type у product_dimensions продукта."""
    links = (
        await session.execute(
            select(ProductDimension)
            .options(selectinload(ProductDimension.dimension_type))
            .where(ProductDimension.product_id == product_id)
        )
    ).scalars().all()
    return {link.dimension_type.code for link in links}


async def _link_value(session: AsyncSession, product_id: int, code: str) -> float | None:
    link = await session.scalar(
        select(ProductDimension)
        .options(selectinload(ProductDimension.dimension_type))
        .join(DimensionType, DimensionType.id == ProductDimension.dimension_type_id)
        .where(
            ProductDimension.product_id == product_id,
            DimensionType.code == code,
        )
    )
    return link.default_value if link else None


async def _create_product(client, sku: str, dimension_state: str = "length", **extra) -> int:
    payload = {
        "sku": sku,
        "name": sku,
        "type": "component",
        "unit": "pcs",
        "dimension_state": dimension_state,
        **extra,
    }
    resp = await client.post("/api/products", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# --- 1D → 2D (area): создаёт width/thickness, длина сохраняется ---------------


@pytest.mark.asyncio
async def test_switch_1d_to_2d_creates_area_links(client, session: AsyncSession) -> None:
    await _seed_types(session)
    pid = await _create_product(client, "MIG-1D-2D")

    resp = await client.patch(f"/api/products/{pid}", json={"dimension_state": "area"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["dimension_state"] == "area"

    codes = await _link_codes(session, pid)
    assert codes == {"length_mm", "width_mm", "thickness_mm"}


@pytest.mark.asyncio
async def test_switch_1d_to_2d_preserves_length_value(client, session: AsyncSession) -> None:
    """Существующая связь length_mm сохраняет значение при переключении."""
    await _seed_types(session)
    pid = await _create_product(client, "MIG-1D-2D-LEN")
    await _add_link(session, pid, "length_mm", default_value=1200.0)
    await session.commit()

    resp = await client.patch(f"/api/products/{pid}", json={"dimension_state": "area"})
    assert resp.status_code == 200, resp.text

    codes = await _link_codes(session, pid)
    assert codes == {"length_mm", "width_mm", "thickness_mm"}
    assert await _link_value(session, pid, "length_mm") == 1200.0


# --- 1D → 3D (volume): создаёт width/height, не создаёт толщину ----------------


@pytest.mark.asyncio
async def test_switch_1d_to_3d_creates_volume_links(client, session: AsyncSession) -> None:
    await _seed_types(session)
    pid = await _create_product(client, "MIG-1D-3D")

    resp = await client.patch(f"/api/products/{pid}", json={"dimension_state": "volume"})
    assert resp.status_code == 200, resp.text

    codes = await _link_codes(session, pid)
    assert codes == {"length_mm", "width_mm", "height_mm"}


# --- area → volume: толщина → высота, длина/ширина сохраняются -----------------


@pytest.mark.asyncio
async def test_switch_area_to_volume_swaps_thickness_to_height(client, session: AsyncSession) -> None:
    await _seed_types(session)
    pid = await _create_product(client, "MIG-2D-3D", dimension_state="area")

    for code, value in (("length_mm", 2000.0), ("width_mm", 1000.0), ("thickness_mm", 5.0)):
        await _add_link(session, pid, code, default_value=value)
    await session.commit()

    resp = await client.patch(f"/api/products/{pid}", json={"dimension_state": "volume"})
    assert resp.status_code == 200, resp.text

    codes = await _link_codes(session, pid)
    assert codes == {"length_mm", "width_mm", "height_mm"}
    assert await _link_value(session, pid, "length_mm") == 2000.0
    assert await _link_value(session, pid, "width_mm") == 1000.0
    assert await _link_value(session, pid, "height_mm") is None


@pytest.mark.asyncio
async def test_switch_volume_to_area_swaps_height_to_thickness(client, session: AsyncSession) -> None:
    await _seed_types(session)
    pid = await _create_product(client, "MIG-3D-2D", dimension_state="volume")

    for code, value in (("length_mm", 3000.0), ("width_mm", 800.0), ("height_mm", 10.0)):
        await _add_link(session, pid, code, default_value=value)
    await session.commit()

    resp = await client.patch(f"/api/products/{pid}", json={"dimension_state": "area"})
    assert resp.status_code == 200, resp.text

    codes = await _link_codes(session, pid)
    assert codes == {"length_mm", "width_mm", "thickness_mm"}
    assert await _link_value(session, pid, "length_mm") == 3000.0
    assert await _link_value(session, pid, "width_mm") == 800.0
    assert await _link_value(session, pid, "thickness_mm") is None


# --- 2D/3D → 1D: связи размерностей очищаются --------------------------------


@pytest.mark.asyncio
async def test_switch_2d_to_1d_clears_area_links(client, session: AsyncSession) -> None:
    await _seed_types(session)
    pid = await _create_product(client, "MIG-2D-1D", dimension_state="area")

    for code in ("length_mm", "width_mm", "thickness_mm"):
        await _add_link(session, pid, code, default_value=100.0)
    await session.commit()

    resp = await client.patch(f"/api/products/{pid}", json={"dimension_state": "length"})
    assert resp.status_code == 200, resp.text

    codes = await _link_codes(session, pid)
    assert codes == set()


@pytest.mark.asyncio
async def test_switch_3d_to_1d_clears_volume_links(client, session: AsyncSession) -> None:
    await _seed_types(session)
    pid = await _create_product(client, "MIG-3D-1D", dimension_state="volume")

    for code in ("length_mm", "width_mm", "height_mm"):
        await _add_link(session, pid, code, default_value=100.0)
    await session.commit()

    resp = await client.patch(f"/api/products/{pid}", json={"dimension_state": "length"})
    assert resp.status_code == 200, resp.text

    codes = await _link_codes(session, pid)
    assert codes == set()


# --- Неразмерные типы (напр. weight) не трогаются -----------------------------


@pytest.mark.asyncio
async def test_switch_preserves_non_dimension_links(client, session: AsyncSession) -> None:
    """Связь неразмерного типа (weight_mm) сохраняется при переключении."""
    await _seed_types(session)
    session.add(DimensionType(code="weight_mm", name="Вес", unit="кг", value_type="number"))
    await session.flush()
    pid = await _create_product(client, "MIG-NON-DIM", dimension_state="area")

    for code in ("length_mm", "width_mm", "thickness_mm", "weight_mm"):
        await _add_link(session, pid, code, default_value=100.0)
    await session.commit()

    resp = await client.patch(f"/api/products/{pid}", json={"dimension_state": "volume"})
    assert resp.status_code == 200, resp.text

    codes = await _link_codes(session, pid)
    assert codes == {"length_mm", "width_mm", "height_mm", "weight_mm"}
    assert await _link_value(session, pid, "weight_mm") == 100.0
