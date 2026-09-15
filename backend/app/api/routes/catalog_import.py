import shutil
import sqlite3
import zipfile
from dataclasses import dataclass
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

from app.api.deps import REFERENCES_WRITER_ROLES, require_role
from app.api.routes.products import (
    _enforce_bidirectional_aliases,
    _sync_boolean_flag,
    _sync_lengths,
)
from app.core.config import settings
from app.core.database import get_db
from app.models.product import Product, ProductLength, ProductPair, ProductType, _length_key
from app.services.catalog_excel_import import (
    TEMPLATE_HEADERS,
    ParsedCatalogRow,
    build_quantity_dict,
    diff_catalog_row,
    effective_lengths,
    format_lengths_cell,
    format_quantities_cell,
    parse_catalog_excel,
    validate_row_counts,
)
from app.services.hanger_quantity_calc import (
    DEFAULT_HANGER_SETTINGS,
    HangerConfigError,
    compute_hanger_quantity,
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
        # Новые продукты + их длина — строки product_lengths заводятся
        # после flush, когда известен product.id.
        new_products: list[tuple[Product, float | None]] = []

        for row in rows:
            sku, qty, length, notes, photo_thumb, photo_full = row

            existing = await db.scalar(
                select(Product)
                .options(selectinload(Product.lengths))
                .where(
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
                if length is not None and not existing.lengths:
                    # Канон длин — product_lengths: историческая дыра этого
                    # импорта — длина писалась только скаляром. Строку заводим
                    # даже при совпадающем скаляре: реимпорт лечит ранее
                    # импортированные артикулы без ручных SQL-правок.
                    existing.length_mm = length
                    db.add(ProductLength(product_id=existing.id, length_mm=length, is_primary=True))
                    changed = True
                elif length is not None and existing.length_mm != length:
                    old_length = existing.length_mm
                    existing.length_mm = length
                    changed = True
                    # Зеркалим в строку, совпадающую со старым скаляром;
                    # остальные строки не трогаем, дубли не плодим.
                    if not any(row.length_mm == length for row in existing.lengths):
                        for row in existing.lengths:
                            if row.length_mm == old_length:
                                row.length_mm = length
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
                new_products.append((product, length))
                imported += 1

        # id новых продуктов нужен для строк длин — flush после цикла.
        await db.flush()
        for product, length in new_products:
            if length is not None:
                db.add(ProductLength(product_id=product.id, length_mm=length, is_primary=True))
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


def _row_count_errors(
    row: ParsedCatalogRow, existing_lengths: list[float] | None
) -> list[dict]:
    return [
        {"row": row.row, "sku": row.sku, "message": message}
        for message in validate_row_counts(row, existing_lengths)
    ]


@dataclass(slots=True)
class _ImportBatch:
    """Общий контекст preview/apply: строки файла + загруженные артикулы."""

    rows: list[ParsedCatalogRow]
    errors: list[dict]
    products: dict[str, Product]
    partners_by_sku: dict[str, Product]
    existing_pairs: set[tuple[int, int]]
    total_data_rows: int


async def _create_product_from_row(db: AsyncSession, row: ParsedCatalogRow) -> None:
    fields = row.fields
    lengths = fields.get("lengths_mm") or []
    quantities = fields.get("quantities")
    # Черновик: длин нет — артикул создаётся неактивным (Q3: активация только
    # вместе с длинами); норма из строки при этом хранится legacy-скаляром
    # (#177, Q2). Размерность всегда 1D (length).
    draft = not lengths
    product = Product(
        sku=row.sku,
        name=fields.get("name") or row.sku,
        type=ProductType.component,
        unit="шт",
        is_active=not draft,
        notes=fields.get("notes"),
        aliases=list(fields.get("aliases") or []),
        source="excel_catalog_import",
    )
    if fields.get("perimeter_mm") is not None:
        product.perimeter_mm = fields["perimeter_mm"]
    if fields.get("mount_width_mm") is not None:
        product.mount_width_mm = fields["mount_width_mm"]
    # Режим подвеса (#127): новый артикул получает режим по данным строки
    # (периметр И габарит → auto, иначе manual) — то же правило, что в
    # миграции существующих данных. Импорт пишет только ручные значения;
    # режим существующих артикулов при обновлении не меняется.
    product.hanger_mode = (
        "auto"
        if fields.get("perimeter_mm") is not None and fields.get("mount_width_mm") is not None
        else "manual"
    )
    if quantities is not None:
        if not lengths:
            # Норма без длин (#177, Q2): legacy-скаляр. Setter принимает int и
            # пишет bare {auto: null, manual: N}; раскрытие в per-length — когда
            # у артикула появятся длины.
            product.quantity_per_hanger = quantities[0]
        else:
            qph = build_quantity_dict(lengths, quantities)
            if product.hanger_mode == "auto":
                # В авто-режиме значение должно существовать сразу — считаем
                # движком, как в products API. Несовместимые габариты — auto
                # остаётся null (ошибку покажет валидация планирования).
                for length in lengths:
                    try:
                        calc = compute_hanger_quantity(
                            perimeter_mm=fields["perimeter_mm"],
                            mount_width_mm=fields["mount_width_mm"],
                            length_mm=length,
                            hanger=DEFAULT_HANGER_SETTINGS,
                        )
                    except HangerConfigError:
                        continue
                    if calc.is_calculable:
                        qph[_length_key(length)]["auto"] = calc.total
            product.quantity_per_hanger = qph
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


async def _update_product_from_row(
    db: AsyncSession,
    product: Product,
    row: ParsedCatalogRow,
) -> bool:
    changes = diff_catalog_row(product, row)
    if not changes:
        return False

    # Пары заводятся фазой 2 apply (колонка «Парный профиль»); флаг
    # is_paired_profile по-прежнему выведенный (ADR-0023, #146).
    for key in ("name", "notes"):
        if key in changes:
            setattr(product, key, changes[key])
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


def _pair_plan(
    row: ParsedCatalogRow, batch: _ImportBatch
) -> tuple[list[str], list[dict], list[str]]:
    """Партнёры строки: резолв против БД и того же файла, строгое наличие.

    Возвращает (wanted, errors, new_links): new_links — партнёры без
    существующей пары (кандидаты на создание). Пара симметричная, без нормы
    в импорте: N считает движок, правится вручную через pairs-API.
    """
    wanted = row.fields.get("pair_partners")
    if not wanted:
        return [], [], []
    batch_skus = {r.sku for r in batch.rows}
    errors: list[dict] = []
    partner_ids: dict[str, int | None] = {}
    for sku in wanted:
        partner = batch.partners_by_sku.get(sku)
        if partner is not None:
            partner_ids[sku] = partner.id
        elif sku in batch_skus and sku != row.sku:
            same = batch.products.get(sku)
            partner_ids[sku] = same.id if same is not None else None
        else:
            errors.append({
                "row": row.row,
                "sku": row.sku,
                "message": f"Парный профиль {sku} не найден в справочнике",
            })
    if errors:
        return [], errors, []
    product = batch.products.get(row.sku)
    new_links = []
    for sku in wanted:
        partner_id = partner_ids[sku]
        if product is not None and partner_id is not None:
            key = (min(product.id, partner_id), max(product.id, partner_id))
            if key not in batch.existing_pairs:
                new_links.append(sku)
        else:
            new_links.append(sku)
    for sku in new_links:
        if not _pair_lengths(row, batch, sku):
            row.warnings.append(f"Пара с {sku}: нет общих длин — расчёт невозможен")
    return wanted, [], new_links


def _pair_lengths(
    row: ParsedCatalogRow, batch: _ImportBatch, partner_sku: str
) -> set[float]:
    """Пересечение длин строки и партнёра (БД или тот же файл)."""
    if row.fields.get("lengths_mm"):
        own = set(row.fields["lengths_mm"])
    elif batch.products.get(row.sku) is not None:
        own = {length.length_mm for length in batch.products[row.sku].lengths}
    else:
        own = set()
    partner = batch.partners_by_sku.get(partner_sku)
    if partner is not None:
        other = {length.length_mm for length in partner.lengths}
    else:
        other = set()
        for other_row in batch.rows:
            if other_row.sku == partner_sku and other_row.fields.get("lengths_mm"):
                other = set(other_row.fields["lengths_mm"])
    return own & other


async def _existing_pair_keys(db: AsyncSession, product_ids: list[int]) -> set[tuple[int, int]]:
    """Канонические ключи (min, max) всех пар с участием артикулов."""
    if not product_ids:
        return set()
    pair_rows = (
        await db.execute(
            select(ProductPair).where(
                ProductPair.product_a_id.in_(product_ids)
                | ProductPair.product_b_id.in_(product_ids)
            )
        )
    ).scalars().all()
    return {(p.product_a_id, p.product_b_id) for p in pair_rows}



async def _prepare_excel_import(file: UploadFile, db: AsyncSession) -> _ImportBatch:
    """Общая часть preview/apply: парсинг файла + загрузка артикулов."""
    content = await file.read()
    try:
        rows, errors, total_data_rows = parse_catalog_excel(content, file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    products = await _load_products_by_sku(db, [row.sku for row in rows])
    partner_skus = sorted({sku for row in rows for sku in row.fields.get("pair_partners", [])})
    partners_by_sku = await _load_products_by_sku(db, partner_skus)
    involved_ids = sorted({p.id for p in list(products.values()) + list(partners_by_sku.values())})
    existing_pairs = await _existing_pair_keys(db, involved_ids)
    return _ImportBatch(
        rows=rows,
        errors=errors,
        products=products,
        partners_by_sku=partners_by_sku,
        existing_pairs=existing_pairs,
        total_data_rows=total_data_rows,
    )


@router.post("/preview-excel")
async def preview_catalog_from_excel(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Предпросмотр импорта справочника сырья из Excel без записи в БД (#63)."""
    batch = await _prepare_excel_import(file, db)
    rows, errors = batch.rows, batch.errors
    items = []
    stats = {"total": batch.total_data_rows, "create": 0, "update": 0, "skip": 0}
    error_rows: set[int] = {err["row"] for err in errors}

    for row in rows:
        product = batch.products.get(row.sku)
        is_new = product is None

        existing_lengths = sorted(length.length_mm for length in product.lengths) if product else None
        count_errors = _row_count_errors(row, existing_lengths)
        if count_errors:
            errors.extend(count_errors)
            error_rows.add(row.row)
            continue
        wanted_partners, pair_errors, new_links = _pair_plan(row, batch)
        if pair_errors:
            errors.extend(pair_errors)
            error_rows.add(row.row)
            if product is None:
                continue
            wanted_partners, new_links = [], []
        if product is None:
            action = "create"
        else:
            action = "update" if diff_catalog_row(product, row) else "skip"
        stats[action] += 1
        lengths = effective_lengths(row, existing_lengths)
        quantities = row.fields.get("quantities")
        new_set = set(new_links)
        items.append({
            "row": row.row,
            "sku": row.sku,
            "name": row.fields.get("name") or (product.name if product else row.sku),
            "length_mm": lengths[0] if lengths else None,
            "lengths_mm": lengths or [],
            "quantity_per_hanger": quantities[0] if quantities else (product.quantity_per_hanger if product else None),
            "quantities_per_hanger": quantities,
            "draft": is_new and not lengths,
            "pairs": [{"sku": sku, "create": sku in new_set} for sku in wanted_partners],
            "has_photo": False,
            "action": action,
            "warnings": row.warnings,
        })

    stats["errors"] = len(error_rows)
    return {"items": items, "errors": errors, "stats": stats}


@router.post(
    "/apply-excel",
    dependencies=[Depends(require_role(list(REFERENCES_WRITER_ROLES)))],
)
async def apply_catalog_from_excel(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Применение импорта справочника сырья из Excel (#63). Файл загружается повторно.

    Запись — по правам editReferences (#154).
    """
    batch = await _prepare_excel_import(file, db)
    rows, errors = batch.rows, batch.errors
    imported = 0
    updated = 0
    skipped = 0

    failed_rows: set[int] = set()
    for row in rows:
        product = batch.products.get(row.sku)

        existing_lengths = sorted(length.length_mm for length in product.lengths) if product else None
        count_errors = _row_count_errors(row, existing_lengths)
        if count_errors:
            errors.extend(count_errors)
            failed_rows.add(row.row)
            continue

        _, pair_errors, _ = _pair_plan(row, batch)
        if pair_errors:
            errors.extend(pair_errors)
            failed_rows.add(row.row)
            if product is None:
                continue

        if product is None:
            await _create_product_from_row(db, row)
            imported += 1
        else:
            if await _update_product_from_row(db, product, row):
                updated += 1
            else:
                skipped += 1

    # Фаза 2: пары — продукты уже записаны и видны в сессии.
    products_by_sku = await _load_products_by_sku(
        db,
        [row.sku for row in rows]
        + [sku for row in rows for sku in row.fields.get("pair_partners", [])],
    )
    known_pairs = await _existing_pair_keys(
        db, [p.id for p in products_by_sku.values()]
    )
    pairs_created = 0
    for row in rows:
        if row.row in failed_rows:
            continue
        wanted = row.fields.get("pair_partners")
        if not wanted:
            continue
        product = products_by_sku.get(row.sku)
        if product is None:
            continue
        for sku in wanted:
            partner = products_by_sku.get(sku)
            if partner is None or partner.id == product.id:
                continue
            key = (min(product.id, partner.id), max(product.id, partner.id))
            if key in known_pairs:
                continue
            db.add(ProductPair(
                product_a_id=key[0],
                product_b_id=key[1],
                quantity_per_hanger={},
            ))
            known_pairs.add(key)
            pairs_created += 1
    await db.flush()

    await db.commit()
    return {
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "pairs_created": pairs_created,
        "errors": errors,
    }


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


async def _pair_partners_by_id(db: AsyncSession) -> dict[int, list[str]]:
    """Партнёры по парам (#146): id артикула → отсортированные SKU партнёров."""
    pairs = (await db.execute(select(ProductPair))).scalars().all()
    skus = dict((await db.execute(select(Product.id, Product.sku))).all())
    partners: dict[int, list[str]] = {}
    for pair in pairs:
        left, right = skus.get(pair.product_a_id), skus.get(pair.product_b_id)
        if left is None or right is None:
            continue
        partners.setdefault(pair.product_a_id, []).append(right)
        partners.setdefault(pair.product_b_id, []).append(left)
    for values in partners.values():
        values.sort()
    return partners


@router.get("/export-excel")
async def export_catalog_excel(db: AsyncSession = Depends(get_db)) -> Response:
    """Выгрузка справочника сырья в Excel в формате импорта (#63).

    Обратная операция к ``/apply-excel``: колонки ровно ``TEMPLATE_HEADERS``
    (11) — «Фото» в выгрузке нет (#177, Q4): фото ведётся отдельным потоком
    (ZIP-импорт / карточка), в рабочем файле колонка остаётся. Выгруженный
    файл правится в Excel и загружается назад без перенастройки колонок.
    """
    products = (
        await db.execute(
            select(Product)
            .options(selectinload(Product.lengths), selectinload(Product.processing_flags))
            .order_by(Product.sku)
        )
    ).scalars().all()
    partners = await _pair_partners_by_id(db)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Справочник сырья"
    sheet.append(list(TEMPLATE_HEADERS))
    for product in products:
        lengths = sorted(length.length_mm for length in product.lengths)
        flag_codes = {flag.code for flag in product.processing_flags}
        # Норма без длин (#177, Q2/Q11) хранится legacy-скаляром — при пустых
        # «Длинах» выгружаем её числом, иначе round-trip потерял бы значение.
        quantities_cell = (
            format_quantities_cell(lengths, product.quantity_per_hanger_by_length)
            if lengths
            else product.quantity_per_hanger
        )
        sheet.append([
            product.sku,
            product.name,
            product.perimeter_mm,
            product.mount_width_mm,
            format_lengths_cell(lengths),
            quantities_cell,
            product.notes,
            "да" if "skip_shot_blast" in flag_codes else "",
            "да" if "is_laminated" in flag_codes else "",
            "; ".join(product.aliases or []),
            "; ".join(partners.get(product.id, [])),
        ])

    buffer = BytesIO()
    workbook.save(buffer)
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="final_catalog.xlsx"'},
    )
