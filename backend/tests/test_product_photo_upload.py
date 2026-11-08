"""Загрузка фото продукта: POST /api/products/{id}/photo пишет файл в storage.

Каталог берётся из `settings.PRODUCT_PHOTO_DIR`; до фикса `settings` в модуле
роутов не импортировался, и ручка падала `NameError` вместо записи файла.
Изоляция каталога — штатная: `conftest.py` выставляет `STORAGE_ROOT` на
`%TEMP%\\ktm2000_pytest_storage_<TEST_RUN_ID>` до импорта приложения.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from app.core.config import settings
from app.models.product import Product, ProductType
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


def _photo_path(filename: str) -> Path:
    return Path(settings.PRODUCT_PHOTO_DIR) / filename


def _storage_relative(filename: str) -> str:
    # API хранит путь от STORAGE_ROOT: `products/<файл>`.
    return str(Path("products") / filename)


def _write_photo(path: Path, payload: bytes, mtime_ns: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    os.utime(path, ns=(mtime_ns, mtime_ns))


async def _make_product(session: AsyncSession, sku: str) -> Product:
    product = Product(
        sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True
    )
    session.add(product)
    await session.flush()
    return product


async def test_upload_photo_writes_file_into_configured_storage(
    session: AsyncSession, client
) -> None:
    product = await _make_product(session, "PHOTO-1")

    payload = b"\x89PNG\r\n\x1a\n-not-a-real-image"
    response = await client.post(
        f"/api/products/{product.id}/photo",
        files={"file": ("shot.png", payload, "image/png")},
    )

    assert response.status_code == 200, response.text
    filename = f"{product.sku}_{product.id}_full.png"
    # Значение хранится как `str(Path)` — на Windows с обратными слешами.
    assert response.json()["photo_full"] == str(Path("products") / filename)

    written = Path(settings.PRODUCT_PHOTO_DIR) / filename
    assert written.read_bytes() == payload


async def test_photo_version_is_stable_between_requests(
    session: AsyncSession, client
) -> None:
    product = await _make_product(session, "PHOTO-STABLE")
    filename = f"{product.sku}_{product.id}_full.png"
    _write_photo(_photo_path(filename), b"first", 1_700_000_000_000_000_000)
    product.photo_full = _storage_relative(filename)
    await session.flush()

    first = (await client.get(f"/api/products/{product.id}")).json()
    second = (await client.get(f"/api/products/{product.id}")).json()

    assert first["photo_full_version"]
    assert second["photo_full_version"] == first["photo_full_version"]


async def test_photo_version_changes_when_file_replaced_outside_api(
    session: AsyncSession, client
) -> None:
    """Кейс 033: файл заменён в storage мимо API — версия обязана измениться."""
    product = await _make_product(session, "PHOTO-REPLACED")
    filename = f"{product.sku}_{product.id}_full.png"
    path = _photo_path(filename)
    _write_photo(path, b"old", 1_700_000_000_000_000_000)
    product.photo_full = _storage_relative(filename)
    await session.flush()

    before = (await client.get(f"/api/products/{product.id}")).json()["photo_full_version"]
    _write_photo(path, b"new", 1_700_000_001_000_000_000)
    after = (await client.get(f"/api/products/{product.id}")).json()["photo_full_version"]

    assert after != before


async def test_photo_versions_full_and_thumb_are_independent(
    session: AsyncSession, client
) -> None:
    product = await _make_product(session, "PHOTO-PAIR")
    full_name = f"{product.sku}_{product.id}_full.png"
    thumb_name = f"{product.sku}_{product.id}_thumb.png"
    _write_photo(_photo_path(full_name), b"full-old", 1_700_000_000_000_000_000)
    _write_photo(_photo_path(thumb_name), b"thumb-old", 1_700_000_000_000_000_000)
    product.photo_full = _storage_relative(full_name)
    product.photo_thumb = _storage_relative(thumb_name)
    await session.flush()

    before = (await client.get(f"/api/products/{product.id}")).json()
    _write_photo(
        _photo_path(thumb_name), b"thumb-new", 1_700_000_001_000_000_000
    )
    after = (await client.get(f"/api/products/{product.id}")).json()

    assert after["photo_full_version"] == before["photo_full_version"]
    assert after["photo_thumb_version"] != before["photo_thumb_version"]


async def test_upload_returns_new_version_only_for_replaced_photo(
    session: AsyncSession, client
) -> None:
    product = await _make_product(session, "PHOTO-UPLOAD")
    full_name = f"{product.sku}_{product.id}_full.png"
    thumb_name = f"{product.sku}_{product.id}_thumb.png"
    _write_photo(_photo_path(full_name), b"full", 1_700_000_000_000_000_000)
    _write_photo(_photo_path(thumb_name), b"thumb", 1_700_000_000_000_000_000)
    product.photo_full = _storage_relative(full_name)
    product.photo_thumb = _storage_relative(thumb_name)
    await session.flush()

    before = (await client.get(f"/api/products/{product.id}")).json()
    response = await client.post(
        f"/api/products/{product.id}/photo",
        params={"kind": "full"},
        files={"file": ("new-full.png", b"full-new-bytes", "image/png")},
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["photo_full_version"] != before["photo_full_version"]
    assert updated["photo_thumb_version"] == before["photo_thumb_version"]


async def test_product_list_exposes_photo_versions(
    session: AsyncSession, client
) -> None:
    product = await _make_product(session, "PHOTO-LIST")
    filename = f"{product.sku}_{product.id}_full.png"
    _write_photo(_photo_path(filename), b"list", 1_700_000_000_000_000_000)
    product.photo_full = _storage_relative(filename)
    await session.flush()

    response = await client.get("/api/products", params={"sku": product.sku})
    assert response.status_code == 200, response.text
    row = next(item for item in response.json()["items"] if item["id"] == product.id)
    assert row["photo_full_version"]
