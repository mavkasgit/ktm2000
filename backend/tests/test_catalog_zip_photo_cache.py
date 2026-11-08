"""ZIP-импорт не сбрасывает версию неизменённого фото (#404).

Проверяем именно место вызова `copy_photo_if_changed`: повторный импорт того
же архива не должен менять `mtime`/версию, а изменившийся файл — должен.
"""

from __future__ import annotations

import sqlite3
import zipfile
from io import BytesIO
from pathlib import Path

from app.core.config import settings
from app.models.product import Product
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ZIP_URL = "/api/catalog-import/upload-zip"


def _zip_with_photo(tmp_path: Path, sku: str, full_bytes: bytes) -> bytes:
    db_path = tmp_path / "profiles.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("DROP TABLE IF EXISTS profiles")
    conn.execute(
        "CREATE TABLE profiles ("
        "name TEXT, quantity_per_hanger REAL, length REAL, notes TEXT, "
        "photo_thumb TEXT, photo_full TEXT)"
    )
    conn.execute(
        "INSERT INTO profiles VALUES (?, 5, 2700, '', NULL, 'full.jpg')",
        (sku,),
    )
    conn.commit()
    conn.close()

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("profiles.db", db_path.read_bytes())
        zf.writestr("images/full.jpg", full_bytes)
    return buf.getvalue()


async def _upload(client: AsyncClient, zip_bytes: bytes) -> None:
    response = await client.post(
        ZIP_URL,
        files={"file": ("static.zip", zip_bytes, "application/zip")},
    )
    assert response.status_code == 200, response.text


async def test_zip_reimport_keeps_version_of_unchanged_photo(
    client: AsyncClient, session: AsyncSession, tmp_path: Path
) -> None:
    sku = "ЮП-ZIP-PHOTO"
    stored = Path(settings.PRODUCT_PHOTO_DIR) / f"{sku}_full.jpg"

    await _upload(client, _zip_with_photo(tmp_path, sku, b"same-photo"))
    product_id = await session.scalar(select(Product.id).where(Product.sku == sku))
    assert product_id is not None
    first = (await client.get(f"/api/products/{product_id}")).json()
    first_mtime = stored.stat().st_mtime_ns

    await _upload(client, _zip_with_photo(tmp_path, sku, b"same-photo"))
    second = (await client.get(f"/api/products/{product_id}")).json()

    assert second["photo_full_version"] == first["photo_full_version"]
    assert stored.stat().st_mtime_ns == first_mtime

    await _upload(client, _zip_with_photo(tmp_path, sku, b"changed-photo"))
    third = (await client.get(f"/api/products/{product_id}")).json()

    assert third["photo_full_version"] != first["photo_full_version"]
