from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime
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
    PlanPositionRouteMatchQuality,
    PlanPositionRouteMatchReason,
    PlanPositionRouteOrigin,
    PlanPosition,
    PlanPositionStatus,
    ProductionPlan,
)
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
from app.services.excel_import import (
    ParsedWorkbook,
    ParsedPlanRow,
    detect_workbook_format,
    parse_factory_plan_workbook,
    sha256_bytes,
    validate_excel_extension,
)
from app.services.route_selection import load_selection_rules_for_profile, select_route_for_payload
from app.services.routing_signature import canonical_signature_from_payload


async def preview_excel_sheet(
    db: AsyncSession,
    *,
    filename: str,
    content: bytes,
    sheet_index: int = 0,
    mode: ImportBatchMode = ImportBatchMode.create_plan,
    production_plan_id: int | None = None,
    column_mapping: dict | None = None,
    normalization_rules: dict | None = None,
    row_selection: str | None = None,
    rule_profile_id: int | None = None,
) -> dict:
    """Parse an Excel sheet and return full preview checks without creating DB records."""
    parsed = parse_factory_plan_workbook(
        content,
        filename,
        sheet_index=sheet_index,
        column_mapping=column_mapping,
        normalization_rules=normalization_rules,
        row_selection=row_selection,
    )
    summary = _summary(parsed.parsed_rows, parsed.warnings, parsed)

    existing_positions: list[PlanPosition] = []
    effective_plan_id = production_plan_id
    if effective_plan_id is None and mode == ImportBatchMode.append_to_plan:
        latest_plan = await db.scalar(
            select(ProductionPlan)
            .where(ProductionPlan.status.notin_(["released", "cancelled"]))
            .order_by(ProductionPlan.created_at.desc())
            .limit(1)
        )
        if latest_plan is not None:
            effective_plan_id = latest_plan.id

    if effective_plan_id is not None and mode != ImportBatchMode.create_plan:
        existing_positions = (
            await db.execute(
                select(PlanPosition).where(
                    PlanPosition.production_plan_id == effective_plan_id,
                    PlanPosition.status != PlanPositionStatus.cancelled,
                )
            )
        ).scalars().all()

    products_by_sku = await _load_products_by_sku(db)
    item_payloads, _route_selection_diagnostics = await _make_change_items(
        db,
        0,  # dry-run preview, no persisted change set
        parsed.parsed_rows,
        products_by_sku,
        mode,
        existing_positions,
        rule_profile_id,
        template_column_mapping=column_mapping,
    )

    return {
        "sheet_name": parsed.sheet_name,
        "header_row_number": parsed.header_row_number,
        "total_rows": parsed.total_rows,
        "summary": summary,
        "items": [_serialize_item(item) for item in item_payloads],
    }


async def create_excel_import_change_set(
    db: AsyncSession,
    *,
    filename: str,
    content: bytes,
    content_type: str | None,
    sheet_index: int = 0,
    mode: ImportBatchMode = ImportBatchMode.create_plan,
    production_plan_id: int | None = None,
    plan_month: str | None = None,
    plan_version: str | None = None,
    column_mapping: dict | None = None,
    normalization_rules: dict | None = None,
    row_selection: str | None = None,
    template_id: int | None = None,
    rule_profile_id: int | None = None,
) -> dict:
    extension = validate_excel_extension(filename)
    file_hash = sha256_bytes(content)
    detected_format = detect_workbook_format(content, filename)
    parsed = parse_factory_plan_workbook(
        content,
        filename,
        sheet_index=sheet_index,
        column_mapping=column_mapping,
        normalization_rules=normalization_rules,
        row_selection=row_selection,
    )

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
    elif mode == ImportBatchMode.append_to_plan:
        # Find latest non-released/cancelled plan, or create one
        production_plan = await db.scalar(
            select(ProductionPlan)
            .where(ProductionPlan.status.notin_(["released", "cancelled"]))
            .order_by(ProductionPlan.created_at.desc())
            .limit(1)
        )
        if production_plan is None:
            plan_no, plan_name = _compose_plan_identity(
                parsed.sheet_name,
                parsed.period_start,
                plan_month=plan_month,
                plan_version=plan_version,
            )
            production_plan = ProductionPlan(
                plan_no=plan_no,
                name=plan_name,
                period_start=parsed.period_start,
                period_end=parsed.period_end,
            )
            db.add(production_plan)
            await db.flush()
    else:
        plan_no, plan_name = _compose_plan_identity(
            parsed.sheet_name,
            parsed.period_start,
            plan_month=plan_month,
            plan_version=plan_version,
        )
        production_plan = ProductionPlan(
            plan_no=plan_no,
            name=plan_name,
            period_start=parsed.period_start,
            period_end=parsed.period_end,
        )
        db.add(production_plan)
        await db.flush()

    summary = _summary(parsed.parsed_rows, parsed.warnings, parsed)
    import_batch = ImportBatch(
        source_file_id=import_file.id,
        production_plan_id=production_plan.id,
        template_id=template_id,
        rule_profile_id=rule_profile_id,
        mode=mode,
        sheet_name=parsed.sheet_name,
        header_row_number=parsed.header_row_number,
        total_rows=parsed.total_rows,
        parsed_rows=len(parsed.parsed_rows),
        summary=summary,
        rules_snapshot=[],
    )
    db.add(import_batch)
    await db.flush()

    # Persist deterministic rule snapshot used for this import run.
    snapshot_rules = await load_selection_rules_for_profile(db, profile_id=rule_profile_id)
    import_batch.rules_snapshot = [
        {
            "id": rule.id,
            "code": rule.code,
            "name": rule.name,
            "profile_id": rule.profile_id,
            "priority": rule.priority,
            "is_active": rule.is_active,
            "conditions": rule.conditions or [],
            "actions": rule.actions or [],
        }
        for rule in snapshot_rules
    ]

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
    item_payloads, route_selection_diagnostics = await _make_change_items(
        db,
        change_set.id,
        parsed.parsed_rows,
        products_by_sku,
        mode,
        existing_positions,
        rule_profile_id,
        template_id=template_id,
        template_column_mapping=column_mapping,
    )
    for item in item_payloads:
        db.add(item)
    await db.flush()

    # Update batch with diagnostics
    import_batch.route_selection_diagnostics = route_selection_diagnostics

    return {
        "import_file_id": import_file.id,
        "import_batch_id": import_batch.id,
        "production_plan_id": production_plan.id,
        "change_set_id": change_set.id,
        "template_id": import_batch.template_id,
        "rule_profile_id": import_batch.rule_profile_id,
        "rules_snapshot": import_batch.rules_snapshot,
        "route_selection_diagnostics": import_batch.route_selection_diagnostics,
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


async def _find_paired_techcard(
    db: AsyncSession, component_skus: list[str]
) -> Techcard | None:
    """Find an active paired_processing techcard that contains all given component SKUs."""
    if not component_skus:
        return None

    normalized_keys = [
        key.lower().replace(" ", "").replace("\u00A0", "").replace("\u2014", "-")
        for key in component_skus
    ]

    stmt = (
        select(Techcard)
        .where(
            Techcard.is_active.is_(True),
            Techcard.processing_type == "paired_processing",
        )
    )
    techcards = await db.execute(stmt)

    seen: set[int] = set()
    for tc in techcards.scalars().all():
        if tc.id in seen:
            continue
        seen.add(tc.id)

        lines = await db.execute(
            select(TechcardLine, Product)
            .join(Product, Product.id == TechcardLine.component_product_id)
            .where(TechcardLine.techcard_id == tc.id)
        )
        line_skus = {
            lp[1].sku.lower().replace(" ", "").replace("\u00A0", "").replace("\u2014", "-")
            for lp in lines.all()
        }
        if all(sku in line_skus for sku in normalized_keys):
            return tc

    return None


async def _make_change_items(
    db: AsyncSession,
    change_set_id: int,
    parsed_rows: list[ParsedPlanRow],
    products_by_sku: dict[str, Product],
    mode: ImportBatchMode,
    existing_positions: list[PlanPosition],
    rule_profile_id: int | None = None,
    template_id: int | None = None,
    template_column_mapping: dict | None = None,
) -> tuple[list[PlanChangeItem], dict]:
    available_by_sku = _build_available_inputs_by_sku(parsed_rows)
    by_fingerprint: dict[str, PlanPosition] = {}
    by_row_hash: dict[str, PlanPosition] = {}
    for pos in existing_positions:
        if pos.source_fingerprint:
            by_fingerprint[pos.source_fingerprint] = pos
        if pos.source_row_hash:
            by_row_hash[pos.source_row_hash] = pos

    # Build set of existing fingerprints for duplicate detection
    existing_fingerprints: set[str] = set()
    for pos in existing_positions:
        if pos.status == PlanPositionStatus.cancelled:
            continue
        if pos.source_fingerprint:
            existing_fingerprints.add(pos.source_fingerprint)

    items: list[PlanChangeItem] = []
    matched_fingerprints: set[str] = set()

    # Track fingerprints within this import to detect intra-import duplicates.
    # Use row hashes (not just first row number) so real duplicates are detected
    # and repeated references to the same source row are ignored.
    import_fingerprints: dict[str, dict[str, set[str] | set[int]]] = {}

    for row in parsed_rows:
        warnings = list(row.warnings)
        errors = list(row.errors)
        product = None
        for key in _sku_lookup_keys(row.source_sku):
            product = products_by_sku.get(key)
            if product is not None:
                break

        if product is None:
            route = None
            if row.payload.get("paired_profile"):
                components = row.payload.get("components") or []
                component_skus = [c.get("sku", "") for c in components if c.get("sku")]
                if component_skus:
                    techcard = await _find_paired_techcard(db, component_skus)
                else:
                    techcard, matched_product = await _find_active_techcard_by_sku(db, row.source_sku)
                    if techcard is not None and matched_product is not None:
                        product = matched_product
                if techcard is not None:
                    line = await db.scalar(select(TechcardLine.id).where(TechcardLine.techcard_id == techcard.id).limit(1))
                    if line is None:
                        errors.append("active_techcard_has_no_lines")
                    else:
                        lines = (
                            await db.execute(
                                select(TechcardLine, Product)
                                .join(Product, Product.id == TechcardLine.component_product_id)
                                .where(TechcardLine.techcard_id == techcard.id)
                                .order_by(TechcardLine.id)
                            )
                        ).all()
                        resolved_inputs = []
                        for tc_line, comp_product in lines:
                            sku_key = comp_product.sku.lower()
                            available = available_by_sku.get(sku_key, Decimal("0"))
                            resolved_inputs.append({
                                "product_id": comp_product.id,
                                "sku": comp_product.sku,
                                "techcard_quantity": str(tc_line.quantity),
                                "available_quantity": str(available),
                                "unit": tc_line.unit,
                            })
                        row.payload["techcard_pair"] = {
                            "resolved": len(resolved_inputs) > 0,
                            "reason": None,
                            "inputs": resolved_inputs,
                        }
                        warnings = [w for w in warnings if w != "paired_profile_product_unmapped"]
                else:
                    if "paired_profile_product_unmapped" not in warnings:
                        warnings.append("paired_profile_product_unmapped")
            else:
                techcard, matched_product = await _find_active_techcard_by_sku(db, row.source_sku)
                if techcard is not None and matched_product is not None:
                    product = matched_product
                else:
                    errors.append("product_not_found")
        else:
            if not product.is_active:
                errors.append("product_inactive")

            if row.payload.get("paired_profile"):
                components = row.payload.get("components") or []
                component_skus = [c.get("sku", "") for c in components if c.get("sku")]
                techcard = await _find_paired_techcard(db, component_skus) if component_skus else None
                if techcard is None:
                    techcard = await db.scalar(
                        select(Techcard).where(Techcard.product_id == product.id, Techcard.is_active.is_(True))
                    )
            else:
                techcard = await db.scalar(
                    select(Techcard).where(Techcard.product_id == product.id, Techcard.is_active.is_(True))
                )

            if techcard is None:
                errors.append("active_techcard_not_found")
            else:
                line = await db.scalar(select(TechcardLine.id).where(TechcardLine.techcard_id == techcard.id).limit(1))
                if line is None:
                    errors.append("active_techcard_has_no_lines")

                if techcard.processing_type == "paired_processing":
                    lines = (
                        await db.execute(
                            select(TechcardLine, Product)
                            .join(Product, Product.id == TechcardLine.component_product_id)
                            .where(TechcardLine.techcard_id == techcard.id)
                            .order_by(TechcardLine.id)
                        )
                    ).all()
                    resolved_inputs = []
                    for tc_line, comp_product in lines:
                        sku_key = comp_product.sku.lower()
                        available = available_by_sku.get(sku_key, Decimal("0"))
                        resolved_inputs.append({
                            "product_id": comp_product.id,
                            "sku": comp_product.sku,
                            "techcard_quantity": str(tc_line.quantity),
                            "available_quantity": str(available),
                            "unit": tc_line.unit,
                        })
                    row.payload["techcard_pair"] = {
                        "resolved": len(resolved_inputs) > 0,
                        "reason": None,
                        "inputs": resolved_inputs,
                    }
                    warnings = [w for w in warnings if w != "paired_profile_product_unmapped"]

        signature = canonical_signature_from_payload(row.payload)
        selection = await select_route_for_payload(
            db, row.payload, product, profile_id=rule_profile_id,
            template_column_mapping=template_column_mapping,
        )
        route = selection.route
        excel_condition_diagnostics = [
            diagnostic
            for diagnostic in selection.condition_diagnostics
            if diagnostic.get("source") == "excel"
        ]

        if route is None:
            errors.append(selection.error or "no_route_candidate")
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

        route_match_quality = None
        route_match_reason = None
        route_assigned_at = None
        if route is not None:
            route_assigned_at = datetime.now(UTC).isoformat()
            route_match_quality = selection.route_match_quality or PlanPositionRouteMatchQuality.exact.value
            route_match_reason = PlanPositionRouteMatchReason.selection_rules.value

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
            "route_id": route.id if route else None,
            "route_name": route.name if route else None,
            "route_source": "auto" if route else "missing",
            "route_origin": PlanPositionRouteOrigin.auto.value if route else None,
            "route_match_quality": route_match_quality,
            "route_match_reason": route_match_reason,
            "route_assigned_at": route_assigned_at,
            "route_manual_confirmed_at": None,
            "route_selection": {
                "matched_rule_ids": selection.matched_rule_ids,
                "required_sections": selection.required_sections,
                "excluded_sections": selection.excluded_sections,
                "selected_route_id": route.id if route else None,
                "route_match_reason": selection.route_match_reason,
                "excel_column_diagnostics": excel_condition_diagnostics,
                "normalize_applied_actions": selection.normalize_applied_actions,
                "ctx_snapshot": selection.ctx_snapshot,
                "route_select_matched_rule_ids": selection.route_select_matched_rule_ids,
            },
            "operation_family": signature.operation_family.value if signature else None,
            "output_kind": signature.output_kind.value if signature else None,
            "has_pack_ops": signature.has_pack_ops if signature else None,
        }

        # Detect duplicate within this import using fingerprint (full row match)
        fp = row.source_fingerprint
        if fp not in import_fingerprints:
            import_fingerprints[fp] = {"row_hashes": set(), "row_numbers": set()}
        fp_entry = import_fingerprints[fp]
        row_hashes = fp_entry["row_hashes"]
        row_numbers = fp_entry["row_numbers"]
        if isinstance(row_hashes, set):
            row_hashes.add(row.source_row_hash)
        if isinstance(row_numbers, set):
            # Use only the canonical (first) row number to avoid false positives
            # from paired profile rows which have multiple source_row_numbers.
            canonical_row = row.source_row_numbers[0] if row.source_row_numbers else row.source_row_number
            row_numbers.add(canonical_row)

        change_action = PlanChangeAction.create_position
        before_data = None
        plan_position_id = None

        existing_by_fp = None
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
                            "operation_family": existing_by_fp.operation_family.value if existing_by_fp.operation_family else None,
                            "output_kind": existing_by_fp.output_kind.value if existing_by_fp.output_kind else None,
                            "has_pack_ops": existing_by_fp.has_pack_ops,
                        }
                elif existing_by_fp.status == PlanPositionStatus.released:
                    change_action = PlanChangeAction.mark_possible_duplicate
                    plan_position_id = existing_by_fp.id

        # Duplicate against existing data
        if mode != ImportBatchMode.create_plan and fp in existing_fingerprints:
            if "duplicate_sku_due_date" not in errors:
                errors.append("duplicate_sku_due_date")

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

    # Mark intra-import duplicates: fingerprints that appear more than once
    duplicate_pairs: dict[str, list[int]] = {}
    for fp, fp_entry in import_fingerprints.items():
        row_hashes = fp_entry["row_hashes"]
        row_numbers = fp_entry["row_numbers"]
        if isinstance(row_numbers, set) and len(row_numbers) > 1:
            duplicate_pairs[fp] = sorted(row_numbers)

    if duplicate_pairs:
        for item in items:
            if item.after_data:
                fp = item.after_data.get("source_fingerprint")
                if fp and fp in duplicate_pairs and "duplicate_sku_due_date" not in item.errors:
                    item.errors = list(item.errors) + ["duplicate_sku_due_date"]
                    item.status = PlanChangeItemStatus.invalid
                    # Store duplicate info for frontend display
                    item.after_data["duplicate_rows"] = duplicate_pairs[fp]
                    item.after_data["duplicate_type"] = "within_import"

    # Mark duplicates against existing positions with row info
    if mode != ImportBatchMode.create_plan:
        for item in items:
            if item.after_data and "duplicate_sku_due_date" in item.errors:
                # Already marked as intra-import duplicate
                if item.after_data.get("duplicate_type"):
                    continue
                # Find existing position with matching fingerprint
                fp = item.after_data.get("source_fingerprint")
                if fp and fp in existing_fingerprints:
                    # Find the existing position with matching fingerprint
                    for pos in existing_positions:
                        if pos.status == PlanPositionStatus.cancelled:
                            continue
                        if pos.source_fingerprint == fp:
                            item.after_data["duplicate_existing_id"] = pos.id
                            item.after_data["duplicate_existing_row"] = pos.source_row_number
                            item.after_data["duplicate_existing_payload"] = pos.source_payload
                            item.after_data["duplicate_type"] = "against_existing"
                            break

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
                            "operation_family": pos.operation_family.value if pos.operation_family else None,
                            "output_kind": pos.output_kind.value if pos.output_kind else None,
                            "has_pack_ops": pos.has_pack_ops,
                        },
                        after_data={},
                        status=PlanChangeItemStatus.pending,
                        plan_position_id=pos.id,
                        warnings=[],
                        errors=[],
                    )
                )

    route_selection_diagnostics = {
        "template_id": template_id,
        "profile_id": rule_profile_id,
        "total_rows": len(parsed_rows),
        "matched_count": sum(1 for item in items if item.after_data and item.after_data.get("route_id")),
        "unmatched_count": sum(1 for item in items if item.after_data and not item.after_data.get("route_id")),
        "normalize_actions_count": sum(
            len((item.after_data or {}).get("route_selection", {}).get("normalize_applied_actions", []))
            for item in items
        ),
        "ctx_samples": [
            (item.after_data or {}).get("route_selection", {}).get("ctx_snapshot")
            for item in items
            if (item.after_data or {}).get("route_selection", {}).get("ctx_snapshot")
        ][:5],
        "excel_diagnostics": {
            "conditions_evaluated": sum(
                len((item.after_data or {}).get("route_selection", {}).get("excel_column_diagnostics", []))
                for item in items
            ),
            "header_mismatch_count": sum(
                1
                for item in items
                for diagnostic in ((item.after_data or {}).get("route_selection", {}).get("excel_column_diagnostics", []))
                if "excel_header_mismatch" in (diagnostic.get("issues") or [])
            ),
            "fallback_used_count": sum(
                1
                for item in items
                for diagnostic in ((item.after_data or {}).get("route_selection", {}).get("excel_column_diagnostics", []))
                if diagnostic.get("resolved_by") in {"header_fallback", "explicit_header"}
            ),
        },
    }

    return items, route_selection_diagnostics


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
        "plan_position_id": item.plan_position_id,
    }


def _summary(
    rows: list[ParsedPlanRow],
    workbook_warnings: list[str],
    parsed_workbook: ParsedWorkbook | None = None,
) -> dict:
    warning_counter = Counter(warning for row in rows for warning in row.warnings)
    error_counter = Counter(error for row in rows for error in row.errors)
    summary = {
        "total_positions": len(rows),
        "paired_profile_positions": sum(1 for row in rows if row.payload.get("paired_profile")),
        "warning_count": sum(warning_counter.values()) + len(workbook_warnings),
        "error_count": sum(error_counter.values()),
        "warnings": dict(warning_counter),
        "errors": dict(error_counter),
        "workbook_warnings": workbook_warnings,
        "quantity_total": str(sum((row.quantity for row in rows), start=rows[0].quantity * 0) if rows else 0),
    }
    if parsed_workbook is not None:
        summary["row_selection"] = parsed_workbook.row_selection
        summary["selected_row_numbers"] = parsed_workbook.selected_row_numbers
        summary["auto_included_row_numbers"] = parsed_workbook.auto_included_row_numbers
        summary["period_start"] = parsed_workbook.period_start.isoformat() if parsed_workbook.period_start else None
        summary["period_end"] = parsed_workbook.period_end.isoformat() if parsed_workbook.period_end else None
        summary["period_label"] = (
            f"{summary['period_start']} - {summary['period_end']}"
            if summary["period_start"] and summary["period_end"]
            else "не определен"
        )
    return summary


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
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    safe_sheet = "".join(ch for ch in sheet_name if ch.isalnum() or ch in " _-")[:30] or "Excel"
    return f"План-{safe_sheet}-{stamp}"


def _compose_plan_identity(
    sheet_name: str,
    period_start: date | None,
    *,
    plan_month: str | None,
    plan_version: str | None,
) -> tuple[str, str]:
    month_label = (plan_month or "").strip()
    if not month_label and period_start is not None:
        month_label = period_start.strftime("%Y-%m")

    version_label = (plan_version or "").strip()
    version_suffix = f" v{version_label}" if version_label else ""

    if month_label:
        plan_name = f"План {month_label}{version_suffix}"
        safe_month = "".join(ch for ch in month_label if ch.isalnum() or ch in "-_") or "month"
        safe_ver = "".join(ch for ch in version_label if ch.isalnum() or ch in "-_") or "v1"
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        plan_no = f"PLAN-{safe_month}-{safe_ver}-{stamp}" if version_label else f"PLAN-{safe_month}-{stamp}"
        return plan_no, plan_name

    return _make_plan_no(sheet_name), f"Import {sheet_name}"
