from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.imports import ImportBatch, ImportBatchMode, ImportFile
from app.models.product import Product
from app.models.production_plan import (
    PlanChangeAction,
    PlanChangeItem,
    PlanChangeItemStatus,
    PlanChangeSet,
    ProductionPlan,
)
from app.services.excel_import import (
    ParsedPlanRow,
    detect_workbook_format,
    parse_factory_plan_workbook,
    sha256_bytes,
    validate_excel_extension,
)


async def create_excel_import_change_set(
    db: AsyncSession,
    *,
    filename: str,
    content: bytes,
    content_type: str | None,
    sheet_index: int = 0,
    mode: ImportBatchMode = ImportBatchMode.create_plan,
    production_plan_id: int | None = None,
) -> dict:
    extension = validate_excel_extension(filename)
    file_hash = sha256_bytes(content)
    detected_format = detect_workbook_format(content, filename)
    parsed = parse_factory_plan_workbook(content, filename, sheet_index=sheet_index)

    import_file = await _get_or_create_import_file(
        db,
        filename=filename,
        content=content,
        content_type=content_type,
        extension=extension,
        detected_format=detected_format,
        file_hash=file_hash,
    )

    if production_plan_id is not None:
        production_plan = await db.get(ProductionPlan, production_plan_id)
        if production_plan is None:
            raise ValueError("Production plan not found")
    else:
        production_plan = ProductionPlan(
            plan_no=_make_plan_no(parsed.sheet_name),
            name=f"Import {parsed.sheet_name}",
            period_start=parsed.period_start,
            period_end=parsed.period_end,
        )
        db.add(production_plan)
        await db.flush()

    summary = _summary(parsed.parsed_rows, parsed.warnings)
    import_batch = ImportBatch(
        source_file_id=import_file.id,
        production_plan_id=production_plan.id,
        mode=mode,
        sheet_name=parsed.sheet_name,
        header_row_number=parsed.header_row_number,
        total_rows=parsed.total_rows,
        parsed_rows=len(parsed.parsed_rows),
        summary=summary,
    )
    db.add(import_batch)
    await db.flush()

    change_set = PlanChangeSet(
        production_plan_id=production_plan.id,
        import_batch_id=import_batch.id,
        summary=summary,
    )
    db.add(change_set)
    await db.flush()

    products_by_sku = await _load_products_by_sku(db)
    item_payloads = []
    for parsed_row in parsed.parsed_rows:
        item = _make_change_item(change_set.id, parsed_row, products_by_sku)
        db.add(item)
        item_payloads.append(item)

    await db.flush()

    return {
        "import_file_id": import_file.id,
        "import_batch_id": import_batch.id,
        "production_plan_id": production_plan.id,
        "change_set_id": change_set.id,
        "sheet_name": parsed.sheet_name,
        "header_row_number": parsed.header_row_number,
        "summary": summary,
        "items": [_serialize_item(item) for item in item_payloads],
    }


async def _get_or_create_import_file(
    db: AsyncSession,
    *,
    filename: str,
    content: bytes,
    content_type: str | None,
    extension: str,
    detected_format: str,
    file_hash: str,
) -> ImportFile:
    existing = await db.scalar(select(ImportFile).where(ImportFile.file_sha256 == file_hash))
    if existing is not None:
        return existing

    storage_dir = Path(settings.IMPORT_STORAGE_DIR)
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_path = storage_dir / f"{file_hash}{extension}"
    stored_path.write_bytes(content)

    import_file = ImportFile(
        original_filename=filename,
        stored_path=str(stored_path),
        content_type=content_type,
        file_extension=extension,
        detected_format=detected_format,
        file_sha256=file_hash,
        size_bytes=len(content),
    )
    db.add(import_file)
    await db.flush()
    return import_file


async def _load_products_by_sku(db: AsyncSession) -> dict[str, Product]:
    products = (await db.execute(select(Product))).scalars().all()
    return {product.sku.lower(): product for product in products}


def _make_change_item(change_set_id: int, row: ParsedPlanRow, products_by_sku: dict[str, Product]) -> PlanChangeItem:
    warnings = list(row.warnings)
    errors = list(row.errors)
    product = products_by_sku.get(row.source_sku.lower())

    if product is None:
        if row.payload.get("paired_profile"):
            if "paired_profile_product_unmapped" not in warnings:
                warnings.append("paired_profile_product_unmapped")
        else:
            errors.append("product_not_found")

    after_data = {
        "product_id": product.id if product else None,
        "source_sku": row.source_sku,
        "source_name": row.source_name,
        "quantity": str(row.quantity),
        "source_ref": row.source_ref,
        "source_row_numbers": row.source_row_numbers,
        "source_fingerprint": row.source_fingerprint,
        "source_row_hash": row.source_row_hash,
        "source_payload": row.payload,
    }
    status = PlanChangeItemStatus.invalid if errors else PlanChangeItemStatus.warning if warnings else PlanChangeItemStatus.pending
    return PlanChangeItem(
        change_set_id=change_set_id,
        source_row_number=row.source_row_numbers[0],
        source_ref=row.source_ref,
        change_action=PlanChangeAction.create_position,
        before_data=None,
        after_data=after_data,
        status=status,
        warnings=warnings,
        errors=errors,
    )


def _serialize_item(item: PlanChangeItem) -> dict:
    return {
        "id": item.id,
        "source_row_number": item.source_row_number,
        "source_ref": item.source_ref,
        "change_action": item.change_action.value,
        "status": item.status.value,
        "warnings": item.warnings,
        "errors": item.errors,
        "after_data": item.after_data,
    }


def _summary(rows: list[ParsedPlanRow], workbook_warnings: list[str]) -> dict:
    warning_counter = Counter(warning for row in rows for warning in row.warnings)
    error_counter = Counter(error for row in rows for error in row.errors)
    return {
        "total_positions": len(rows),
        "paired_profile_positions": sum(1 for row in rows if row.payload.get("paired_profile")),
        "warning_count": sum(warning_counter.values()) + len(workbook_warnings),
        "error_count": sum(error_counter.values()),
        "warnings": dict(warning_counter),
        "errors": dict(error_counter),
        "workbook_warnings": workbook_warnings,
        "quantity_total": str(sum((row.quantity for row in rows), start=rows[0].quantity * 0) if rows else 0),
    }


def _make_plan_no(sheet_name: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    safe_sheet = "".join(ch for ch in sheet_name if ch.isalnum())[:20] or "excel"
    return f"IMP-{safe_sheet}-{stamp}"
