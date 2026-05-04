from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.techcard import Techcard, TechcardLine
from app.models.imports import ImportBatch, ImportBatchMode, ImportFile
from app.models.product import Product
from app.models.production_plan import (
    PlanChangeAction,
    PlanChangeItem,
    PlanChangeItemStatus,
    PlanChangeSet,
    PlanPosition,
    PlanPositionStatus,
    ProductionPlan,
)
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
from app.services.excel_import import (
    ParsedPlanRow,
    detect_workbook_format,
    parse_factory_plan_workbook,
    sha256_bytes,
    validate_excel_extension,
)
from app.services.route_matcher import find_route


async def create_excel_import_change_set(
    db: AsyncSession,
    *,
    filename: str,
    content: bytes,
    content_type: str | None,
    sheet_index: int = 0,
    mode: ImportBatchMode = ImportBatchMode.create_plan,
    production_plan_id: int | None = None,
    column_mapping: dict | None = None,
) -> dict:
    extension = validate_excel_extension(filename)
    file_hash = sha256_bytes(content)
    detected_format = detect_workbook_format(content, filename)
    parsed = parse_factory_plan_workbook(content, filename, sheet_index=sheet_index, column_mapping=column_mapping)

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

    existing_positions = []
    if production_plan_id is not None and mode != ImportBatchMode.create_plan:
        existing_positions = (
            await db.execute(
                select(PlanPosition).where(
                    PlanPosition.production_plan_id == production_plan_id,
                    PlanPosition.status != PlanPositionStatus.cancelled,
                )
            )
        ).scalars().all()

    products_by_sku = await _load_products_by_sku(db)
    item_payloads = await _make_change_items(
        db, change_set.id, parsed.parsed_rows, products_by_sku, mode, existing_positions
    )
    for item in item_payloads:
        db.add(item)
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
    result: dict[str, Product] = {}
    for product in products:
        for key in _sku_lookup_keys(product.sku):
            result[key] = product
    return result


def _sku_lookup_keys(sku: str) -> set[str]:
    raw = (sku or "").strip()
    if not raw:
        return set()

    keys = {raw.lower(), _normalize_sku(raw)}

    # Heuristic mojibake recovery for legacy CP1251/Latin-1 mismatch.
    try:
        recovered = raw.encode("latin-1").decode("cp1251")
        keys.add(recovered.lower())
        keys.add(_normalize_sku(recovered))
    except Exception:
        pass
    return {k for k in keys if k}


def _normalize_sku(sku: str) -> str:
    s = (sku or "").strip().lower()
    dash_variants = "\u2010\u2011\u2012\u2013\u2014\u2212\u2043\uFE58\uFE63\uFF0D"
    for d in dash_variants:
        s = s.replace(d, "-")
    s = s.replace(" ", "").replace("\u00A0", "")
    return s


async def _find_active_techcard_by_sku(db: AsyncSession, sku: str) -> tuple[Techcard | None, Product | None]:
    for key in _sku_lookup_keys(sku):
        normalized_product_sku = func.lower(
            func.replace(
                func.replace(
                    func.replace(
                        Product.sku,
                        " ",
                        "",
                    ),
                    "\u00A0",
                    "",
                ),
                "—",
                "-",
            )
        )
        product = await db.scalar(select(Product).where(normalized_product_sku == key).limit(1))
        if product is None:
            continue
        techcard = await db.scalar(
            select(Techcard).where(Techcard.product_id == product.id, Techcard.is_active.is_(True)).limit(1)
        )
        if techcard is not None:
            return techcard, product
    return None, None


async def _make_change_items(
    db: AsyncSession,
    change_set_id: int,
    parsed_rows: list[ParsedPlanRow],
    products_by_sku: dict[str, Product],
    mode: ImportBatchMode,
    existing_positions: list[PlanPosition],
) -> list[PlanChangeItem]:
    available_by_sku = _build_available_inputs_by_sku(parsed_rows)
    by_fingerprint: dict[str, PlanPosition] = {}
    by_row_hash: dict[str, PlanPosition] = {}
    for pos in existing_positions:
        if pos.source_fingerprint:
            by_fingerprint[pos.source_fingerprint] = pos
        if pos.source_row_hash:
            by_row_hash[pos.source_row_hash] = pos

    items: list[PlanChangeItem] = []
    matched_fingerprints: set[str] = set()

    for row in parsed_rows:
        warnings = list(row.warnings)
        errors = list(row.errors)
        product = None
        for key in _sku_lookup_keys(row.source_sku):
            product = products_by_sku.get(key)
            if product is not None:
                break

        if product is None:
            techcard, matched_product = await _find_active_techcard_by_sku(db, row.source_sku)
            if techcard is not None and matched_product is not None:
                product = matched_product
            elif row.payload.get("paired_profile"):
                if "paired_profile_product_unmapped" not in warnings:
                    warnings.append("paired_profile_product_unmapped")
            else:
                errors.append("product_not_found")
        else:
            if not product.is_active:
                errors.append("product_inactive")

            techcard = await db.scalar(select(Techcard).where(Techcard.product_id == product.id, Techcard.is_active.is_(True)))
            if techcard is None:
                errors.append("active_techcard_not_found")
            else:
                line = await db.scalar(select(TechcardLine.id).where(TechcardLine.techcard_id == techcard.id).limit(1))
                if line is None:
                    errors.append("active_techcard_has_no_lines")

                if row.payload.get("paired_profile") and techcard.processing_type == "paired_processing":
                    lines = (
                        await db.execute(
                            select(TechcardLine, Product)
                            .join(Product, Product.id == TechcardLine.component_product_id)
                            .where(TechcardLine.techcard_id == techcard.id)
                            .order_by(TechcardLine.id)
                        )
                    ).all()
                    resolved_inputs = []
                    all_fit = True
                    for tc_line, comp_product in lines:
                        sku_key = comp_product.sku.lower()
                        required = row.quantity * Decimal(str(tc_line.quantity))
                        available = available_by_sku.get(sku_key, Decimal("0"))
                        resolved_inputs.append({
                            "product_id": comp_product.id,
                            "sku": comp_product.sku,
                            "required_quantity": str(required),
                            "available_quantity": str(available),
                            "unit": tc_line.unit,
                        })
                        if available < required:
                            all_fit = False
                    row.payload["techcard_pair"] = {
                        "resolved": all_fit and len(resolved_inputs) > 0,
                        "reason": None if all_fit else "insufficient_components",
                        "inputs": resolved_inputs,
                    }
                    if all_fit:
                        warnings = [w for w in warnings if w != "paired_profile_product_unmapped"]
                    else:
                        warnings.append("techcard_pair_not_resolved")

            route = await find_route(db, product) if product else None
            if route is None:
                errors.append("active_route_not_found")
            else:
                steps = (
                    await db.execute(select(RouteStep).where(RouteStep.route_id == route.id).order_by(RouteStep.sequence))
                ).scalars().all()
                if not steps:
                    errors.append("active_route_has_no_steps")
                else:
                    for step in steps:
                        section = await db.get(Section, step.section_id)
                        if section is None or not section.is_active:
                            errors.append("route_contains_inactive_section")
                            break

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

        change_action = PlanChangeAction.create_position
        before_data = None
        plan_position_id = None

        if mode != ImportBatchMode.create_plan:
            existing_by_fp = by_fingerprint.get(row.source_fingerprint)
            if existing_by_fp is not None:
                matched_fingerprints.add(row.source_fingerprint)
                if existing_by_fp.status == PlanPositionStatus.draft:
                    if existing_by_fp.source_row_hash == row.source_row_hash:
                        change_action = PlanChangeAction.ignore_unchanged
                    else:
                        change_action = PlanChangeAction.update_draft_position
                        plan_position_id = existing_by_fp.id
                        before_data = {
                            "product_id": existing_by_fp.product_id,
                            "source_sku": existing_by_fp.source_sku,
                            "source_name": existing_by_fp.source_name,
                            "quantity": str(existing_by_fp.quantity),
                            "source_ref": existing_by_fp.source_ref,
                            "source_row_numbers": [existing_by_fp.source_row_number],
                            "source_fingerprint": existing_by_fp.source_fingerprint,
                            "source_row_hash": existing_by_fp.source_row_hash,
                            "source_payload": existing_by_fp.source_payload,
                        }
                elif existing_by_fp.status == PlanPositionStatus.released:
                    change_action = PlanChangeAction.mark_possible_duplicate
                    plan_position_id = existing_by_fp.id

        status = PlanChangeItemStatus.invalid if errors else PlanChangeItemStatus.warning if warnings else PlanChangeItemStatus.pending
        if change_action == PlanChangeAction.mark_possible_duplicate and status == PlanChangeItemStatus.pending:
            status = PlanChangeItemStatus.warning

        items.append(
            PlanChangeItem(
                change_set_id=change_set_id,
                source_row_number=row.source_row_numbers[0],
                source_ref=row.source_ref,
                change_action=change_action,
                before_data=before_data,
                after_data=after_data,
                status=status,
                plan_position_id=plan_position_id,
                warnings=warnings,
                errors=errors,
            )
        )

    if mode == ImportBatchMode.replace_draft_from_same_source:
        for fp, pos in by_fingerprint.items():
            if fp not in matched_fingerprints and pos.status == PlanPositionStatus.draft:
                items.append(
                    PlanChangeItem(
                        change_set_id=change_set_id,
                        source_row_number=pos.source_row_number,
                        source_ref=pos.source_ref,
                        change_action=PlanChangeAction.cancel_draft_position,
                        before_data={
                            "product_id": pos.product_id,
                            "source_sku": pos.source_sku,
                            "source_name": pos.source_name,
                            "quantity": str(pos.quantity),
                            "source_ref": pos.source_ref,
                            "source_row_numbers": [pos.source_row_number],
                            "source_fingerprint": pos.source_fingerprint,
                            "source_row_hash": pos.source_row_hash,
                            "source_payload": pos.source_payload,
                        },
                        after_data={},
                        status=PlanChangeItemStatus.pending,
                        plan_position_id=pos.id,
                        warnings=[],
                        errors=[],
                    )
                )

    return items


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


def _build_available_inputs_by_sku(rows: list[ParsedPlanRow]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for row in rows:
        components = row.payload.get("components") or []
        if isinstance(components, list) and components:
            for component in components:
                sku = str(component.get("sku") or "").strip()
                if not sku:
                    continue
                key = sku.lower()
                current = totals.get(key, Decimal("0"))
                totals[key] = current + row.quantity
            continue

        key = row.source_sku.lower()
        current = totals.get(key, Decimal("0"))
        totals[key] = current + row.quantity
    return totals


def _make_plan_no(sheet_name: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    safe_sheet = "".join(ch for ch in sheet_name if ch.isalnum())[:20] or "excel"
    return f"IMP-{safe_sheet}-{stamp}"
