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


async def test_upload_drawing_writes_separate_slot_and_marks_own(
    session: AsyncSession, client
) -> None:
    """Чертёж — третий слот (#463): файл отдельный, происхождение own."""
    product = await _make_product(session, "DRAWING-1")
    payload = b"\x89PNG\r\n\x1a\n-drawing"

    response = await client.post(
        f"/api/products/{product.id}/photo",
        params={"kind": "drawing"},
        files={"file": ("drawing.png", payload, "image/png")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    filename = f"{product.sku}_{product.id}_drawing.png"
    assert body["drawing_full"] == str(Path("products") / filename)
    assert body["visual_origin"] == "own"
    assert body["drawing_full_version"]
    # Основное фото не подменяется чертежом.
    assert body["photo_full"] is None
    written = Path(settings.PRODUCT_PHOTO_DIR) / filename
    assert written.read_bytes() == payload


async def test_drawing_version_is_independent_of_photos(
    session: AsyncSession, client
) -> None:
    product = await _make_product(session, "DRAWING-VERSION")
    full_name = f"{product.sku}_{product.id}_full.png"
    drawing_name = f"{product.sku}_{product.id}_drawing.png"
    _write_photo(_photo_path(full_name), b"full", 1_700_000_000_000_000_000)
    _write_photo(_photo_path(drawing_name), b"drawing", 1_700_000_000_000_000_000)
    product.photo_full = _storage_relative(full_name)
    product.drawing_full = _storage_relative(drawing_name)
    await session.flush()

    before = (await client.get(f"/api/products/{product.id}")).json()
    _write_photo(
        _photo_path(drawing_name), b"drawing-new", 1_700_000_001_000_000_000
    )
    after = (await client.get(f"/api/products/{product.id}")).json()

    assert before["drawing_full_version"]
    assert after["drawing_full_version"] != before["drawing_full_version"]
    assert after["photo_full_version"] == before["photo_full_version"]


async def test_upload_full_photo_keeps_drawing_version(
    session: AsyncSession, client
) -> None:
    """Загрузка фото не сдвигает версию чертежа (#465: слоты независимы)."""
    product = await _make_product(session, "UPLOAD-FULL-KEEPS-DRAWING")
    drawing_name = f"{product.sku}_{product.id}_drawing.png"
    _write_photo(_photo_path(drawing_name), b"drawing", 1_700_000_000_000_000_000)
    product.drawing_full = _storage_relative(drawing_name)
    product.visual_origin = "own"
    await session.flush()

    before = (await client.get(f"/api/products/{product.id}")).json()
    response = await client.post(
        f"/api/products/{product.id}/photo",
        params={"kind": "full"},
        files={"file": ("full.png", b"full-new", "image/png")},
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["drawing_full"] == before["drawing_full"]
    assert updated["drawing_full_version"] == before["drawing_full_version"]
    assert updated["visual_origin"] == "own"
    assert updated["photo_full_version"]


async def test_delete_drawing_removes_only_drawing_slot(
    session: AsyncSession, client
) -> None:
    """Удаление чертежа не трогает фото/превью (#465)."""
    product = await _make_product(session, "DELETE-DRAWING")
    full_name = f"{product.sku}_{product.id}_full.png"
    thumb_name = f"{product.sku}_{product.id}_thumb.png"
    drawing_name = f"{product.sku}_{product.id}_drawing.png"
    _write_photo(_photo_path(full_name), b"full", 1_700_000_000_000_000_000)
    _write_photo(_photo_path(thumb_name), b"thumb", 1_700_000_000_000_000_000)
    _write_photo(_photo_path(drawing_name), b"drawing", 1_700_000_000_000_000_000)
    product.photo_full = _storage_relative(full_name)
    product.photo_thumb = _storage_relative(thumb_name)
    product.drawing_full = _storage_relative(drawing_name)
    product.visual_origin = "alias"
    await session.flush()

    before = (await client.get(f"/api/products/{product.id}")).json()
    response = await client.delete(
        f"/api/products/{product.id}/photo", params={"kind": "drawing"}
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["drawing_full"] is None
    assert updated["drawing_full_version"] is None
    # Происхождение описывает чертёж: без него бейдж не относится к слоту.
    assert updated["visual_origin"] is None
    assert updated["photo_full"] == before["photo_full"]
    assert updated["photo_full_version"] == before["photo_full_version"]
    assert updated["photo_thumb"] == before["photo_thumb"]
    assert updated["photo_thumb_version"] == before["photo_thumb_version"]
    assert not _photo_path(drawing_name).exists()
    assert _photo_path(full_name).exists()
    assert _photo_path(thumb_name).exists()


async def test_delete_full_photo_removes_only_full_slot(
    session: AsyncSession, client
) -> None:
    """Удаление основного фото не трогает превью и чертёж (#465)."""
    product = await _make_product(session, "DELETE-FULL")
    full_name = f"{product.sku}_{product.id}_full.png"
    thumb_name = f"{product.sku}_{product.id}_thumb.png"
    drawing_name = f"{product.sku}_{product.id}_drawing.png"
    _write_photo(_photo_path(full_name), b"full", 1_700_000_000_000_000_000)
    _write_photo(_photo_path(thumb_name), b"thumb", 1_700_000_000_000_000_000)
    _write_photo(_photo_path(drawing_name), b"drawing", 1_700_000_000_000_000_000)
    product.photo_full = _storage_relative(full_name)
    product.photo_thumb = _storage_relative(thumb_name)
    product.drawing_full = _storage_relative(drawing_name)
    product.visual_origin = "own"
    await session.flush()

    before = (await client.get(f"/api/products/{product.id}")).json()
    response = await client.delete(
        f"/api/products/{product.id}/photo", params={"kind": "full"}
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["photo_full"] is None
    assert updated["photo_full_version"] is None
    assert updated["photo_thumb"] == before["photo_thumb"]
    assert updated["photo_thumb_version"] == before["photo_thumb_version"]
    assert updated["drawing_full"] == before["drawing_full"]
    assert updated["drawing_full_version"] == before["drawing_full_version"]
    assert updated["visual_origin"] == "own"
    assert not _photo_path(full_name).exists()
    assert _photo_path(thumb_name).exists()
    assert _photo_path(drawing_name).exists()


async def test_delete_thumb_removes_only_thumb_slot(
    session: AsyncSession, client
) -> None:
    """Удаление превью не трогает основное фото и чертёж (#465)."""
    product = await _make_product(session, "DELETE-THUMB")
    full_name = f"{product.sku}_{product.id}_full.png"
    thumb_name = f"{product.sku}_{product.id}_thumb.png"
    drawing_name = f"{product.sku}_{product.id}_drawing.png"
    _write_photo(_photo_path(full_name), b"full", 1_700_000_000_000_000_000)
    _write_photo(_photo_path(thumb_name), b"thumb", 1_700_000_000_000_000_000)
    _write_photo(_photo_path(drawing_name), b"drawing", 1_700_000_000_000_000_000)
    product.photo_full = _storage_relative(full_name)
    product.photo_thumb = _storage_relative(thumb_name)
    product.drawing_full = _storage_relative(drawing_name)
    await session.flush()

    before = (await client.get(f"/api/products/{product.id}")).json()
    response = await client.delete(
        f"/api/products/{product.id}/photo", params={"kind": "thumb"}
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["photo_thumb"] is None
    assert updated["photo_thumb_version"] is None
    assert updated["photo_full"] == before["photo_full"]
    assert updated["drawing_full"] == before["drawing_full"]
    assert not _photo_path(thumb_name).exists()
    assert _photo_path(full_name).exists()
    assert _photo_path(drawing_name).exists()


async def test_delete_empty_slot_is_idempotent(
    session: AsyncSession, client
) -> None:
    """Пустой слот — не ошибка: повторный DELETE отвечает 200."""
    product = await _make_product(session, "DELETE-EMPTY")

    first = await client.delete(
        f"/api/products/{product.id}/photo", params={"kind": "drawing"}
    )
    second = await client.delete(
        f"/api/products/{product.id}/photo", params={"kind": "drawing"}
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["drawing_full"] is None


async def test_delete_photo_unknown_product_returns_404(client) -> None:
    response = await client.delete("/api/products/999999/photo", params={"kind": "full"})
    assert response.status_code == 404


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
    full_name = f"{product.sku}_{product.id}_full.png"
    thumb_name = f"{product.sku}_{product.id}_thumb.png"
    _write_photo(_photo_path(full_name), b"list-full", 1_700_000_000_000_000_000)
    _write_photo(_photo_path(thumb_name), b"list-thumb", 1_700_000_000_000_000_000)
    product.photo_full = _storage_relative(full_name)
    product.photo_thumb = _storage_relative(thumb_name)
    await session.flush()

    response = await client.get("/api/products", params={"sku": product.sku})
    assert response.status_code == 200, response.text
    row = next(item for item in response.json()["items"] if item["id"] == product.id)
    assert row["photo_full_version"]
    assert row["photo_thumb_version"]
    assert row["photo_full_version"] != row["photo_thumb_version"]


async def test_list_version_changes_only_for_replaced_photo(
    session: AsyncSession, client
) -> None:
    """Замена файла в storage видна в списке; соседний товар не сбрасывает кэш."""
    first = await _make_product(session, "PHOTO-LIST-A")
    second = await _make_product(session, "PHOTO-LIST-B")
    first_full_name = f"{first.sku}_{first.id}_full.png"
    first_thumb_name = f"{first.sku}_{first.id}_thumb.png"
    second_full_name = f"{second.sku}_{second.id}_full.png"
    second_thumb_name = f"{second.sku}_{second.id}_thumb.png"
    first_full_path = _photo_path(first_full_name)
    _write_photo(first_full_path, b"first-old", 1_700_000_000_000_000_000)
    _write_photo(
        _photo_path(first_thumb_name),
        b"first-thumb-old",
        1_700_000_000_000_000_000,
    )
    _write_photo(
        _photo_path(second_full_name),
        b"second",
        1_700_000_000_000_000_000,
    )
    _write_photo(
        _photo_path(second_thumb_name),
        b"second-thumb",
        1_700_000_000_000_000_000,
    )
    first.photo_full = _storage_relative(first_full_name)
    first.photo_thumb = _storage_relative(first_thumb_name)
    second.photo_full = _storage_relative(second_full_name)
    second.photo_thumb = _storage_relative(second_thumb_name)
    await session.flush()

    def versions_by_id(
        payload: dict,
    ) -> dict[int, tuple[str | None, str | None]]:
        return {
            item["id"]: (item["photo_thumb_version"], item["photo_full_version"])
            for item in payload["items"]
        }

    before = versions_by_id(
        (await client.get("/api/products", params={"q": "PHOTO-LIST-"})).json()
    )
    _write_photo(first_full_path, b"first-new", 1_700_000_001_000_000_000)
    after = versions_by_id(
        (await client.get("/api/products", params={"q": "PHOTO-LIST-"})).json()
    )

    assert after[first.id][1] != before[first.id][1]
    assert after[first.id][0] == before[first.id][0]
    assert after[second.id] == before[second.id]

