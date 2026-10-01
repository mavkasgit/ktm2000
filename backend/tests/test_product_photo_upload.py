"""Загрузка фото продукта: POST /api/products/{id}/photo пишет файл в storage.

Каталог берётся из `settings.PRODUCT_PHOTO_DIR`; до фикса `settings` в модуле
роутов не импортировался, и ручка падала `NameError` вместо записи файла.
Изоляция каталога — штатная: `conftest.py` выставляет `STORAGE_ROOT` на
`%TEMP%\\ktm2000_pytest_storage_<TEST_RUN_ID>` до импорта приложения.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.core.config import settings
from app.models.product import Product, ProductType
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def test_upload_photo_writes_file_into_configured_storage(
    session: AsyncSession, client
) -> None:
    product = Product(
        sku="PHOTO-1", name="Photo 1", type=ProductType.finished_good, unit="pcs", is_active=True
    )
    session.add(product)
    await session.flush()

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
