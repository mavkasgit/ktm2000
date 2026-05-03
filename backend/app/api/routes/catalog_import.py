import shutil
import sqlite3
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.product import Product, ProductType

router = APIRouter(prefix="/catalog-import", tags=["catalog-import"])


def _parse_profile_type(sku: str) -> str | None:
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


def _normalize_photo_path(path: str | None) -> str | None:
    if not path:
        return None
    normalized = path.replace("\\", "/")
    return normalized


@router.post("/upload-zip")
async def import_catalog_from_zip(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload static.zip and import/update catalog items.

    ZIP structure:
        profiles.db
        images/
            SKU-thumb.jpg
            SKU.jpg
    """
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are accepted")

    photo_dir = Path(settings.PRODUCT_PHOTO_DIR)
    photo_dir.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        zip_path = tmp_path / "catalog.zip"

        content = await file.read()
        zip_path.write_bytes(content)

        # Extract
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(str(extract_dir))

        # Find profiles.db
        db_file = extract_dir / "profiles.db"
        if not db_file.exists():
            # Maybe it's inside a subfolder
            for sub in extract_dir.iterdir():
                if sub.is_dir() and (sub / "profiles.db").exists():
                    db_file = sub / "profiles.db"
                    extract_dir = sub
                    break

        if not db_file.exists():
            raise HTTPException(status_code=400, detail="profiles.db not found in ZIP")

        images_dir = extract_dir / "images"

        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, quantity_per_hanger, length, notes, photo_thumb, photo_full FROM profiles"
        )
        rows = cursor.fetchall()
        conn.close()

        imported = 0
        updated = 0
        skipped = 0
        errors = []

        for row in rows:
            sku, qty, length, notes, photo_thumb, photo_full = row

            existing = await db.scalar(select(Product).where(Product.sku == sku))

            # Prepare photo paths
            new_thumb = None
            new_full = None
            try:
                if photo_thumb:
                    src_thumb = images_dir / Path(photo_thumb).name
                    if src_thumb.exists():
                        dst_thumb = photo_dir / f"{sku}_thumb.jpg"
                        shutil.copy2(str(src_thumb), str(dst_thumb))
                        new_thumb = _normalize_photo_path(
                            str(dst_thumb.relative_to(Path(settings.PRODUCT_PHOTO_DIR).parent))
                        )
                if photo_full:
                    src_full = images_dir / Path(photo_full).name
                    if src_full.exists():
                        dst_full = photo_dir / f"{sku}_full.jpg"
                        shutil.copy2(str(src_full), str(dst_full))
                        new_full = _normalize_photo_path(
                            str(dst_full.relative_to(Path(settings.PRODUCT_PHOTO_DIR).parent))
                        )
            except Exception as e:
                errors.append(f"{sku}: photo copy failed - {e}")

            if existing:
                # Update existing
                changed = False
                if existing.type != ProductType.component:
                    existing.type = ProductType.component
                    changed = True
                if existing.name != sku:
                    existing.name = sku
                    changed = True
                if existing.quantity_per_hanger != qty:
                    existing.quantity_per_hanger = qty
                    changed = True
                if existing.length_mm != length:
                    existing.length_mm = length
                    changed = True
                if new_thumb and existing.photo_thumb != new_thumb:
                    existing.photo_thumb = new_thumb
                    changed = True
                if new_full and existing.photo_full != new_full:
                    existing.photo_full = new_full
                    changed = True
                if existing.profile_type != _parse_profile_type(sku):
                    existing.profile_type = _parse_profile_type(sku)
                    changed = True
                if changed:
                    updated += 1
                else:
                    skipped += 1
            else:
                # Create new
                product = Product(
                    sku=sku,
                    name=sku,
                    type=ProductType.component,
                    unit="шт",
                    is_active=True,
                    notes=notes or None,
                    profile_type=_parse_profile_type(sku),
                    length_mm=length,
                    quantity_per_hanger=qty,
                    photo_thumb=new_thumb,
                    photo_full=new_full,
                    source="ekranchik_catalog",
                    is_catalog_item=True,
                )
                db.add(product)
                imported += 1

        await db.commit()

    return {
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "total_in_zip": len(rows),
    }
