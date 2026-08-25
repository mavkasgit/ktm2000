"""Подвес листов 2D/3D через API продуктов (#126).

Контракт: у артикулов dimension_state in (area, volume) словарь
quantity_per_hanger имеет ровно одну запись — ключ length_mm типового
набора строкой, значение {auto, manual}; auto заполняется сервером
формулой листов. Плюс поле hanger_mode ('auto' | 'manual', default 'auto',
невалидное значение → 422).

Паттерн — test_product_dimension_state_migration.py: HTTP через client,
product_dimensions через session (hybrid DB mode).
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def _create_product(client, sku: str, dimension_state: str = "area", **extra) -> dict:
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
    return resp.json()


# --- hanger_mode: дефолт, персист, валидация ---------------------------------


@pytest.mark.asyncio
async def test_create_2d_product_defaults_hanger_mode_auto(client, session: AsyncSession) -> None:
    await _seed_types(session)
    body = await _create_product(client, "SH-MODE-DEF")
    assert body["hanger_mode"] == "auto"
    # Осей ещё нет — записи в словаре нет.
    assert body["quantity_per_hanger"] is None


@pytest.mark.asyncio
async def test_patch_hanger_mode_manual_persists(client, session: AsyncSession) -> None:
    await _seed_types(session)
    pid = (await _create_product(client, "SH-MODE-MAN"))["id"]

    resp = await client.patch(f"/api/products/{pid}", json={"hanger_mode": "manual"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["hanger_mode"] == "manual"

    got = await client.get(f"/api/products/{pid}")
    assert got.status_code == 200
    assert got.json()["hanger_mode"] == "manual"

    # Возврат в авто тоже персистентен.
    resp = await client.patch(f"/api/products/{pid}", json={"hanger_mode": "auto"})
    assert resp.status_code == 200, resp.text
    got = await client.get(f"/api/products/{pid}")
    assert got.json()["hanger_mode"] == "auto"


@pytest.mark.asyncio
async def test_invalid_hanger_mode_returns_422(client, session: AsyncSession) -> None:
    await _seed_types(session)
    pid = (await _create_product(client, "SH-MODE-BAD"))["id"]

    resp = await client.patch(f"/api/products/{pid}", json={"hanger_mode": "foo"})
    assert resp.status_code == 422

    resp = await client.post(
        "/api/products",
        json={
            "sku": "SH-MODE-BAD2",
            "name": "SH-MODE-BAD2",
            "type": "component",
            "dimension_state": "area",
            "hanger_mode": "whatever",
        },
    )
    assert resp.status_code == 422


# --- Одна запись словаря с авто по формуле листов ------------------------------


@pytest.mark.asyncio
async def test_2d_product_single_entry_with_auto(client, session: AsyncSession) -> None:
    await _seed_types(session)
    pid = (await _create_product(client, "SH-2D-AUTO"))["id"]
    await _add_link(session, pid, "length_mm", default_value=1000.0)
    await _add_link(session, pid, "width_mm", default_value=500.0)
    await _add_link(session, pid, "thickness_mm", default_value=1.5)
    await session.commit()

    resp = await client.get(f"/api/products/{pid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["hanger_mode"] == "auto"
    # floor(9_000_000 / (1000*500)) = 18; толщина в площади не участвует.
    assert body["quantity_per_hanger"] == {"1000": {"auto": 18, "manual": None}}


@pytest.mark.asyncio
async def test_2d_product_missing_width_auto_null(client, session: AsyncSession) -> None:
    await _seed_types(session)
    pid = (await _create_product(client, "SH-2D-NOW"))["id"]
    await _add_link(session, pid, "length_mm", default_value=1000.0)
    await _add_link(session, pid, "width_mm", default_value=None)
    await session.commit()

    resp = await client.get(f"/api/products/{pid}")
    assert resp.status_code == 200
    assert resp.json()["quantity_per_hanger"] == {"1000": {"auto": None, "manual": None}}


@pytest.mark.asyncio
async def test_2d_product_over_frame_auto_null(client, session: AsyncSession) -> None:
    await _seed_types(session)
    pid = (await _create_product(client, "SH-2D-OVER"))["id"]
    await _add_link(session, pid, "length_mm", default_value=3001.0)
    await _add_link(session, pid, "width_mm", default_value=1000.0)
    await session.commit()

    resp = await client.get(f"/api/products/{pid}")
    assert resp.status_code == 200
    assert resp.json()["quantity_per_hanger"] == {"3001": {"auto": None, "manual": None}}


@pytest.mark.asyncio
async def test_3d_product_auto_with_hanging_edge(client, session: AsyncSession) -> None:
    await _seed_types(session)
    pid = (await _create_product(client, "SH-3D-OK", dimension_state="volume"))["id"]
    await _add_link(session, pid, "length_mm", default_value=1000.0)
    await _add_link(session, pid, "width_mm", default_value=500.0)
    await _add_link(session, pid, "height_mm", default_value=300.0)
    await session.commit()

    resp = await client.get(f"/api/products/{pid}")
    assert resp.status_code == 200
    assert resp.json()["quantity_per_hanger"] == {"1000": {"auto": 18, "manual": None}}


@pytest.mark.asyncio
async def test_3d_product_no_hanging_edge_auto_null(client, session: AsyncSession) -> None:
    await _seed_types(session)
    pid = (await _create_product(client, "SH-3D-EDGE", dimension_state="volume"))["id"]
    await _add_link(session, pid, "length_mm", default_value=1000.0)
    await _add_link(session, pid, "width_mm", default_value=500.0)
    await _add_link(session, pid, "height_mm", default_value=400.0)
    await session.commit()

    resp = await client.get(f"/api/products/{pid}")
    assert resp.status_code == 200
    assert resp.json()["quantity_per_hanger"] == {"1000": {"auto": None, "manual": None}}


# --- Manual сохраняется, auto продолжает считаться -----------------------------


@pytest.mark.asyncio
async def test_manual_value_saved_for_sheet(client, session: AsyncSession) -> None:
    await _seed_types(session)
    pid = (await _create_product(client, "SH-MANUAL"))["id"]
    await _add_link(session, pid, "length_mm", default_value=1000.0)
    await _add_link(session, pid, "width_mm", default_value=500.0)
    await session.commit()

    resp = await client.patch(
        f"/api/products/{pid}",
        json={"hanger_mode": "manual", "quantity_per_hanger": {"1000": {"manual": 5}}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["quantity_per_hanger"] == {"1000": {"auto": 18, "manual": 5}}

    got = await client.get(f"/api/products/{pid}")
    assert got.json()["quantity_per_hanger"] == {"1000": {"auto": 18, "manual": 5}}


@pytest.mark.asyncio
async def test_sheet_list_endpoint_returns_single_entry(client, session: AsyncSession) -> None:
    await _seed_types(session)
    pid = (await _create_product(client, "SH-LIST"))["id"]
    await _add_link(session, pid, "length_mm", default_value=3000.0)
    await _add_link(session, pid, "width_mm", default_value=1500.0)
    await session.commit()

    resp = await client.get("/api/products", params={"sku": "SH-LIST"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == pid
    assert items[0]["hanger_mode"] == "auto"
    # floor(9_000_000 / 4_500_000) = 2 — ровно поле подвеса допустимо.
    assert items[0]["quantity_per_hanger"] == {"3000": {"auto": 2, "manual": None}}
