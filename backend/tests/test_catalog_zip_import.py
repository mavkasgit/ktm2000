"""Импорт справочника eKranchik из ZIP (upload-zip): длины в product_lengths.
Историческая дыра импорта: длина писалась только скаляром ``length_mm``
(attributes JSONB), строки ``product_lengths`` не заводились — пары считали
пустое пересечение при видимой в витрине длине (дев-БД выправлена разовым
backfill-SQL, миграции нет). Регресс-тесты держат: создание заводит строку,
реимпорт зеркалит длину в строку, legacy-артикул без строк при обновлении
получает строку, ручные строки не трогаются.
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
    conn.execute(
        "DROP TABLE IF EXISTS profiles"
    )
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


async def _lengths(session: AsyncSession, sku: str) -> list[float]:
    product = await session.scalar(select(Product).where(Product.sku == sku))
    assert product is not None
    rows = await session.scalars(
        select(ProductLength).where(ProductLength.product_id == product.id)
    )
    return sorted(row.length_mm for row in rows.all())


async def _scalar(session: AsyncSession, sku: str) -> float | None:
    product = await session.scalar(select(Product).where(Product.sku == sku))
    assert product is not None
    return product.length_mm


async def test_zip_import_creates_product_with_length_row(
    client: AsyncClient, session: AsyncSession, tmp_path: Path
) -> None:
    await _upload(client, _make_zip_bytes([("ЮП-ZIP-1", 5, 2750, "")], tmp_path), tmp_path)

    product = await session.scalar(select(Product).where(Product.sku == "ЮП-ZIP-1"))
    assert product is not None
    assert product.type == ProductType.component
    assert product.source == "ekranchik_catalog"
    # Длина — и скаляр (legacy-чтение), и канон-строка product_lengths.
    assert await _scalar(session, "ЮП-ZIP-1") == 2750
    assert await _lengths(session, "ЮП-ZIP-1") == [2750]
    primary = await session.scalar(
        select(ProductLength).where(ProductLength.product_id == product.id)
    )
    assert primary is not None and primary.is_primary is True


async def test_zip_reimport_updates_existing_length_row(
    client: AsyncClient, session: AsyncSession, tmp_path: Path
) -> None:
    await _upload(client, _make_zip_bytes([("ЮП-ZIP-2", 5, 2750, "")], tmp_path), tmp_path)
    await _upload(client, _make_zip_bytes([("ЮП-ZIP-2", 5, 3000, "")], tmp_path), tmp_path)

    assert await _scalar(session, "ЮП-ZIP-2") == 3000
    assert await _lengths(session, "ЮП-ZIP-2") == [3000]


async def test_zip_reimport_backfills_legacy_scalar_only_product(
    client: AsyncClient, session: AsyncSession, tmp_path: Path
) -> None:
    # Явно созданная дыра: скаляр есть, строк нет (историческое состояние).
    product = Product(
        sku="ЮП-ZIP-3",
        name="ЮП-ZIP-3",
        type=ProductType.component,
        unit="шт",
        length_mm=2500,
    )
    session.add(product)
    await session.flush()
    await session.commit()

    await _upload(client, _make_zip_bytes([("ЮП-ZIP-3", 5, 2600, "")], tmp_path), tmp_path)

    assert await _scalar(session, "ЮП-ZIP-3") == 2600
    assert await _lengths(session, "ЮП-ZIP-3") == [2600]


async def test_zip_reimport_keeps_unrelated_rows(
    client: AsyncClient, session: AsyncSession, tmp_path: Path
) -> None:
    # Ручные строки, не совпадающие со старым скаляром, не трогаем.
    product = Product(
        sku="ЮП-ZIP-4",
        name="ЮП-ZIP-4",
        type=ProductType.component,
        unit="шт",
        length_mm=2000,
    )
    session.add(product)
    await session.flush()
    session.add(ProductLength(product_id=product.id, length_mm=1800))
    session.add(ProductLength(product_id=product.id, length_mm=2400))
    await session.commit()

    await _upload(client, _make_zip_bytes([("ЮП-ZIP-4", 5, 2200, "")], tmp_path), tmp_path)

    assert await _scalar(session, "ЮП-ZIP-4") == 2200
    assert await _lengths(session, "ЮП-ZIP-4") == [1800, 2400]


async def test_zip_reimport_heals_rows_even_when_scalar_matches(
    client: AsyncClient, session: AsyncSession, tmp_path: Path
) -> None:
    # Главный кейс лечения: скаляр уже равен длине из ZIP, но строк нет —
    # реимпорт заводит строку, хотя скаляр не менялся.
    product = Product(
        sku="ЮП-ZIP-5",
        name="ЮП-ZIP-5",
        type=ProductType.component,
        unit="шт",
        length_mm=2750,
    )
    session.add(product)
    await session.flush()
    await session.commit()

    await _upload(client, _make_zip_bytes([("ЮП-ZIP-5", 5, 2750, "")], tmp_path), tmp_path)

    assert await _scalar(session, "ЮП-ZIP-5") == 2750
    assert await _lengths(session, "ЮП-ZIP-5") == [2750]
