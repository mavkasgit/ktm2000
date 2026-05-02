"""CLI script to import profiles from ekranchik SQLite database into FactoryFlow.

Usage:
    cd backend
    python -m scripts.import_ekranchik_profiles
"""
import asyncio
import shutil
import sqlite3
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session
from app.models.product import Product, ProductType


# Paths
EKRANCHIK_DB = Path(r"C:\Users\user\VibeCoding\ekranchik-modern\static\profiles.db")
EKRANCHIK_IMAGES = Path(r"C:\Users\user\VibeCoding\ekranchik-modern\static\images")
PRODUCT_PHOTO_DIR = Path(settings.PRODUCT_PHOTO_DIR)


def parse_profile_type(sku: str) -> str | None:
    """Infer profile type from SKU prefix."""
    prefix = sku.split("-")[0] if "-" in sku else sku[:3]
    mapping = {
        "ЮП": "универсальный профиль",
        "АТ": "анодированный трубный",
        "ALS": "светодиодный профиль",
        "СРЛ": "светодиодный линейный",
        "МС": "модульный светильник",
        "ПП": "подвесной профиль",
        "ПТ": "профиль трубчатый",
        "Круг": "круглый трубный",
    }
    return mapping.get(prefix, prefix)


def parse_cross_section(sku: str) -> str | None:
    """Extract dimensions from SKU."""
    # e.g., СРЛ3326 -> 33x26, ЮП-460 -> 47мм
    return None


async def import_profiles():
    PRODUCT_PHOTO_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(EKRANCHIK_DB))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name, quantity_per_hanger, length, notes, photo_thumb, photo_full FROM profiles"
    )
    rows = cursor.fetchall()
    conn.close()

    print(f"Found {len(rows)} profiles in ekranchik database")

    async with async_session() as session:
        imported = 0
        skipped = 0
        for row in rows:
            sku, qty, length, notes, photo_thumb, photo_full = row
            
            # Check if already exists
            from sqlalchemy import select
            existing = await session.scalar(select(Product).where(Product.sku == sku))
            if existing:
                print(f"  Skip (exists): {sku}")
                skipped += 1
                continue

            # Copy photos
            new_thumb = None
            new_full = None
            if photo_thumb:
                src_thumb = EKRANCHIK_IMAGES / Path(photo_thumb).name
                if src_thumb.exists():
                    dst_thumb = PRODUCT_PHOTO_DIR / f"{sku}_thumb.jpg"
                    shutil.copy2(str(src_thumb), str(dst_thumb))
                    new_thumb = str(dst_thumb.relative_to(Path(settings.PRODUCT_PHOTO_DIR).parent))
            if photo_full:
                src_full = EKRANCHIK_IMAGES / Path(photo_full).name
                if src_full.exists():
                    dst_full = PRODUCT_PHOTO_DIR / f"{sku}_full.jpg"
                    shutil.copy2(str(src_full), str(dst_full))
                    new_full = str(dst_full.relative_to(Path(settings.PRODUCT_PHOTO_DIR).parent))

            product = Product(
                sku=sku,
                name=sku,  # Use SKU as name initially; user can update later
                type=ProductType.finished_good,
                unit="шт",
                is_active=True,
                notes=notes or None,
                profile_type=parse_profile_type(sku),
                length_mm=length,
                quantity_per_hanger=qty,
                photo_thumb=new_thumb,
                photo_full=new_full,
                source="ekranchik_catalog",
                is_catalog_item=True,
            )
            session.add(product)
            imported += 1
            print(f"  Imported: {sku}")

        await session.commit()
        print(f"\nDone: {imported} imported, {skipped} skipped (already existed)")


if __name__ == "__main__":
    asyncio.run(import_profiles())
