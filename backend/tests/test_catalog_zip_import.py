"""Импорт справочника eKranchik из ZIP (upload-zip).

Контракт регресса: импорт создаёт и обновляет канонический реестр
``product_lengths``, не затирает уже настроенные строки и лечит старые
артикулы без реестра.
"""

import sqlite3
import zipfile
from io import BytesIO
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product, ProductLength, ProductType

ZIP_URL = "/api/catalog-import/upload-zip"


def _make_zip_bytes(profiles: list[tuple], tmp_path: Path) -> bytes:
    """ZIP с profiles.db (eKranchik-структура): (name, qty, length, notes)."""
    db_path = tmp_path / "profiles.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("DROP TABLE IF EXISTS profiles")
    conn.execute(
        "CREATE TABLE profiles ("
        "name TEXT, quantity_per_hanger REAL, length REAL, notes TEXT, "
        "photo_thumb TEXT, photo_full TEXT)"
    )
    conn.executemany(
        "INSERT INTO profiles VALUES (?, ?, ?, ?, NULL, NULL)",
        [(name, qty, length, notes) for name, qty, length, notes in profiles],
    )
    conn.commit()
    conn.close()

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.write(db_path, "profiles.db")
    return buf.getvalue()


async def _upload(client: AsyncClient, zip_bytes: bytes, tmp_path: Path):
    zip_path = tmp_path / "static.zip"
    zip_path.write_bytes(zip_bytes)
    resp = await client.post(
        ZIP_URL,
        files={"file": ("static.zip", zip_path.read_bytes(), "application/zip")},
    )
    assert resp.status_code == 200, resp.text
    return resp


async def _product_id(session: AsyncSession, sku: str) -> int:
    product_id = await session.scalar(select(Product.id).where(Product.sku == sku))
    assert product_id is not None
    return product_id


async def _product(client: AsyncClient, product_id: int) -> dict:
    response = await client.get(f"/api/products/{product_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def _lengths(client: AsyncClient, product_id: int) -> list[dict]:
    return (await _product(client, product_id))["lengths"]


async def test_zip_import_creates_product_with_length_row(
    client: AsyncClient, session: AsyncSession, tmp_path: Path
) -> None:
    await _upload(client, _make_zip_bytes([("ЮП-ZIP-1", 5, 2750, "")], tmp_path), tmp_path)

    product = await _product(client, await _product_id(session, "ЮП-ZIP-1"))
    assert product["type"] == "component"
    assert product["source"] == "ekranchik_catalog"
    assert product["lengths"] == [
        {"length_mm": 2750.0, "raw_length_mm": None, "is_primary": True}
    ]


async def test_zip_reimport_updates_existing_length_row(
    client: AsyncClient, session: AsyncSession, tmp_path: Path
) -> None:
    await _upload(client, _make_zip_bytes([("ЮП-ZIP-2", 5, 2750, "")], tmp_path), tmp_path)
    await _upload(client, _make_zip_bytes([("ЮП-ZIP-2", 5, 3000, "")], tmp_path), tmp_path)

    assert await _lengths(client, await _product_id(session, "ЮП-ZIP-2")) == [
        {"length_mm": 3000.0, "raw_length_mm": None, "is_primary": True}
    ]


async def test_zip_reimport_heals_legacy_product_without_length_rows(
    client: AsyncClient, session: AsyncSession, tmp_path: Path
) -> None:
    # Исторический артикул мог существовать без канонического реестра длин.
    product = Product(
        sku="ЮП-ZIP-3",
        name="ЮП-ZIP-3",
        type=ProductType.component,
        unit="шт",
    )
    session.add(product)
    await session.flush()
    await session.commit()

    await _upload(client, _make_zip_bytes([("ЮП-ZIP-3", 5, 2600, "")], tmp_path), tmp_path)

    assert await _lengths(client, await _product_id(session, "ЮП-ZIP-3")) == [
        {"length_mm": 2600.0, "raw_length_mm": None, "is_primary": True}
    ]


async def test_zip_reimport_keeps_manual_length_rows(
    client: AsyncClient, session: AsyncSession, tmp_path: Path
) -> None:
    product = Product(
        sku="ЮП-ZIP-4",
        name="ЮП-ZIP-4",
        type=ProductType.component,
        unit="шт",
    )
    session.add(product)
    await session.flush()
    session.add(ProductLength(product_id=product.id, length_mm=1800))
    session.add(ProductLength(product_id=product.id, length_mm=2400))
    await session.commit()

    await _upload(client, _make_zip_bytes([("ЮП-ZIP-4", 5, 2200, "")], tmp_path), tmp_path)

    assert await _lengths(client, await _product_id(session, "ЮП-ZIP-4")) == [
        {"length_mm": 1800.0, "raw_length_mm": None, "is_primary": False},
        {"length_mm": 2400.0, "raw_length_mm": None, "is_primary": False},
    ]
