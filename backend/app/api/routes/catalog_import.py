import shutil
import sqlite3
import zipfile
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from openpyxl import Workbook
from sqlalchemy import String, cast, select
from sqlalchemy.dialects.postgresql import ARRAY as pg_ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.routes.products import (
    _enforce_bidirectional_aliases,
    _sync_boolean_flag,
    _sync_lengths,
)
from app.core.config import settings
from app.core.database import get_db
from app.models.product import Product, ProductLength, ProductType
from app.services.catalog_excel_import import (
    TEMPLATE_HEADERS,
    ParsedCatalogRow,
    build_quantity_dict,
    diff_catalog_row,
    effective_lengths,
    parse_catalog_excel,
    validate_row_counts,
)

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

            existing = await db.scalar(
                select(Product).where(
                    (Product.sku == sku) | (Product.aliases.op("@>")(cast([sku], pg_ARRAY(String))))
                )
            )

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


def _read_zip_profiles(extract_dir: Path):
    """Extract profiles.db rows and image dir from extracted ZIP."""
    db_file = extract_dir / "profiles.db"
    if not db_file.exists():
        for sub in extract_dir.iterdir():
            if sub.is_dir() and (sub / "profiles.db").exists():
                db_file = sub / "profiles.db"
                extract_dir = sub
                break

    if not db_file.exists():
        return None, None

    images_dir = extract_dir / "images"

    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name, quantity_per_hanger, length, notes, photo_thumb, photo_full FROM profiles"
    )
    rows = cursor.fetchall()
    conn.close()

    return rows, images_dir


@router.post("/preview-zip")
async def preview_catalog_from_zip(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload ZIP and return preview of import changes without writing to DB."""
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are accepted")

    with TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        zip_path = tmp_path / "catalog.zip"

        content = await file.read()
        zip_path.write_bytes(content)

        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(str(extract_dir))

        rows, images_dir = _read_zip_profiles(extract_dir)
        if rows is None:
            raise HTTPException(status_code=400, detail="profiles.db not found in ZIP")

        items = []
        stats = {"total": 0, "create": 0, "update": 0, "skip": 0}

        for row in rows:
            sku, qty, length, notes, photo_thumb, photo_full = row
            stats["total"] += 1

            existing = await db.scalar(
                select(Product).where(
                    (Product.sku == sku) | (Product.aliases.op("@>")(cast([sku], pg_ARRAY(String))))
                )
            )

            # Check if photos exist in ZIP
            has_photo = False
            if images_dir:
                if photo_thumb and (images_dir / Path(photo_thumb).name).exists():
                    has_photo = True
                if photo_full and (images_dir / Path(photo_full).name).exists():
                    has_photo = True

            if existing:
                # Determine if anything would change
                would_change = (
                    existing.type != ProductType.component
                    or existing.name != sku
                    or existing.quantity_per_hanger != qty
                    or existing.length_mm != length
                    or existing.profile_type != _parse_profile_type(sku)
                )
                action = "update" if would_change else "skip"
                if action == "update":
                    stats["update"] += 1
                else:
                    stats["skip"] += 1
            else:
                action = "create"
                stats["create"] += 1

            items.append({
                "sku": sku,
                "name": sku,
                "profile_type": _parse_profile_type(sku),
                "length_mm": length,
                "quantity_per_hanger": qty,
                "has_photo": has_photo,
                "action": action,
            })

        return {"items": items, "stats": stats}


# ─── Импорт справочника сырья из Excel (#63) ────────────────────────────────


async def _load_products_by_sku(db: AsyncSession, skus: list[str]) -> dict[str, Product]:
    if not skus:
        return {}
    stmt = (
        select(Product)
        .options(selectinload(Product.lengths), selectinload(Product.processing_flags))
        .where(Product.sku.in_(skus))
    )
    items = (await db.execute(stmt)).scalars().all()
    return {product.sku: product for product in items}


def _row_count_errors(row: ParsedCatalogRow, existing_lengths: list[float] | None) -> list[dict]:
    return [
        {"row": row.row, "sku": row.sku, "message": message}
        for message in validate_row_counts(row, existing_lengths)
    ]


async def _create_product_from_row(db: AsyncSession, row: ParsedCatalogRow) -> None:
    fields = row.fields
    lengths = fields.get("lengths_mm") or []
    quantities = fields.get("quantities")
    product = Product(
        sku=row.sku,
        name=fields.get("name") or row.sku,
        type=ProductType.component,
        unit="шт",
        is_active=True,
        notes=fields.get("notes"),
        is_paired_profile=bool(fields.get("is_paired_profile")),
        aliases=list(fields.get("aliases") or []),
        source="excel_catalog_import",
    )
    if fields.get("perimeter_mm") is not None:
        product.perimeter_mm = fields["perimeter_mm"]
    if fields.get("mount_width_mm") is not None:
        product.mount_width_mm = fields["mount_width_mm"]
    if lengths and quantities is not None:
        product.quantity_per_hanger = build_quantity_dict(lengths, quantities)
    db.add(product)
    await db.flush()

    for length in lengths:
        db.add(ProductLength(product_id=product.id, length_mm=length))
    if fields.get("skip_shot_blast") is not None:
        await _sync_boolean_flag(db, product.id, "skip_shot_blast", fields["skip_shot_blast"])
    if fields.get("is_laminated") is not None:
        await _sync_boolean_flag(db, product.id, "is_laminated", fields["is_laminated"])
    if fields.get("aliases"):
        await _enforce_bidirectional_aliases(db, product.id, fields["aliases"], old_aliases=[])
    await db.flush()


async def _update_product_from_row(db: AsyncSession, product: Product, row: ParsedCatalogRow) -> bool:
    changes = diff_catalog_row(product, row)
    if not changes:
        return False

    for key in ("name", "notes", "is_paired_profile"):
        if key in changes:
            setattr(product, key, changes[key])
    if "type" in changes:
        product.type = changes["type"]
    if "is_active" in changes:
        product.is_active = changes["is_active"]
    for key in ("perimeter_mm", "mount_width_mm"):
        if key in changes:
            setattr(product, key, changes[key])
    if "lengths_mm" in changes:
        await _sync_lengths(db, product.id, changes["lengths_mm"])
    if "quantity_per_hanger" in changes:
        product.quantity_per_hanger = changes["quantity_per_hanger"]
    if "skip_shot_blast" in changes:
        await _sync_boolean_flag(db, product.id, "skip_shot_blast", changes["skip_shot_blast"])
    if "is_laminated" in changes:
        await _sync_boolean_flag(db, product.id, "is_laminated", changes["is_laminated"])
    if "aliases" in changes:
        old_aliases = list(product.aliases or [])
        product.aliases = changes["aliases"]
        await _enforce_bidirectional_aliases(db, product.id, changes["aliases"], old_aliases=old_aliases)
    await db.flush()
    return True


async def _prepare_excel_import(
    file: UploadFile, db: AsyncSession
) -> tuple[list[ParsedCatalogRow], list[dict], dict[str, Product], int]:
    """Общая часть preview/apply: парсинг файла + загрузка артикулов по SKU."""
    content = await file.read()
    try:
        rows, errors, total_data_rows = parse_catalog_excel(content, file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    products = await _load_products_by_sku(db, [row.sku for row in rows])
    return rows, errors, products, total_data_rows


@router.post("/preview-excel")
async def preview_catalog_from_excel(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Предпросмотр импорта справочника сырья из Excel без записи в БД (#63)."""
    rows, errors, products, total_data_rows = await _prepare_excel_import(file, db)
    items = []
    stats = {"total": total_data_rows, "create": 0, "update": 0, "skip": 0}
    error_rows: set[int] = {err["row"] for err in errors}

    for row in rows:
        product = products.get(row.sku)
        existing_lengths = sorted(length.length_mm for length in product.lengths) if product else None
        count_errors = _row_count_errors(row, existing_lengths)
        if count_errors:
            errors.extend(count_errors)
            error_rows.add(row.row)
            continue

        if product is None:
            action = "create"
        else:
            action = "update" if diff_catalog_row(product, row) else "skip"
        stats[action] += 1

        lengths = effective_lengths(row, existing_lengths)
        quantities = row.fields.get("quantities")
        items.append({
            "row": row.row,
            "sku": row.sku,
            "name": row.fields.get("name") or (product.name if product else row.sku),
            "length_mm": lengths[0] if lengths else None,
            "lengths_mm": lengths or [],
            "quantity_per_hanger": quantities[0] if quantities else (product.quantity_per_hanger if product else None),
            "quantities_per_hanger": quantities,
            "has_photo": False,
            "action": action,
            "warnings": row.warnings,
        })

    stats["errors"] = len(error_rows)
    return {"items": items, "errors": errors, "stats": stats}


@router.post("/apply-excel")
async def apply_catalog_from_excel(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Применение импорта справочника сырья из Excel (#63). Файл загружается повторно."""
    rows, errors, products, _total = await _prepare_excel_import(file, db)
    imported = 0
    updated = 0
    skipped = 0

    for row in rows:
        product = products.get(row.sku)
        existing_lengths = sorted(length.length_mm for length in product.lengths) if product else None
        count_errors = _row_count_errors(row, existing_lengths)
        if count_errors:
            errors.extend(count_errors)
            continue

        if product is None:
            await _create_product_from_row(db, row)
            imported += 1
        elif await _update_product_from_row(db, product, row):
            updated += 1
        else:
            skipped += 1

    await db.commit()
    return {"imported": imported, "updated": updated, "skipped": skipped, "errors": errors}


@router.get("/template-excel")
async def catalog_template_excel() -> Response:
    """Скачиваемый шаблон справочника сырья: только заголовки колонок (#63)."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Справочник сырья"
    sheet.append(list(TEMPLATE_HEADERS))
    buffer = BytesIO()
    workbook.save(buffer)
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="catalog_template.xlsx"'},
    )
