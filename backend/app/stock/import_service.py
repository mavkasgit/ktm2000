"""Сервис для импорта остатков из Excel в Stock Ledger.

Содержит:
* ``parse_remainders_excel`` — парсинг Excel-файла с остатками.
* ``apply_remainders_import`` — создание ``StockTransaction`` через
  ``StockCommandService``, с опцией очистки существующих остатков.
* ``generate_remainders_template_for_location`` — генерация шаблона .xlsx.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.route import SectionOperation
from app.models.section import Section
from app.models.user import User
from app.stock.models import QualityState, Reason, StockBalance
from app.stock.services import StockCommand, StockCommandService
from app.services.excel_import import parse_row_selection


# ─── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class RemainderItem:
    """Одна строка из Excel-файла с остатками после парсинга."""

    source_row_number: int
    sku: str
    quantity: float | None
    comment: str | None
    product_id: int | None
    product_name: str | None
    status: Literal["valid", "invalid"]
    errors: list[str]
    raw_values: list[str]
    # NEW: колонка «Выполненные операции» (сырая строка из Excel)
    completed_operations_raw: str | None = None
    # NEW: резолвнутые пройденные этапы (поднабор ops_dict)
    completed_stages: list[dict] | None = None
    # NEW: имя целевой секции из Excel
    target_section_name: str | None = None
    # NEW: ID целевой секции (None если не найдена или не указана)
    target_section_id: int | None = None


@dataclass
class SheetSummary:
    """Сводка по результатам парсинга листа Excel."""

    total: int
    valid: int
    invalid: int
    quantity_total: float


@dataclass
class ImportResult:
    """Результат применения импорта остатков."""

    success: bool
    imported_count: int
    errors: list[str]
    transaction_ids: list[int]


# ─── Column header aliases ─────────────────────────────────────────────────────

_SKU_ALIASES = frozenset({
    "sku", "артикул", "код", "продукт",
    "sku/артикул", "артикул / sku", "артикул/sku",
})
_QTY_ALIASES = frozenset({
    "quantity", "количество", "кол-во",
    "кол-во, шт", "кол-во шт", "кол-во шт.", "кол-во,шт",
})
_COMMENT_ALIASES = frozenset({"comment", "комментарий", "примечание"})
_COMPLETED_OPS_ALIASES = frozenset({
    "выполненные операции", "операции", "completed_operations",
    "пройденные операции", "этапы",
})
_TARGET_SECTION_ALIASES = frozenset({
    "целевая секция", "секция", "target_section",
    "целевой участок", "участок",
})


def _norm_hdr(value: str) -> str:
    """Normalise a header string for comparison (lowercase, collapse whitespace)."""
    return " ".join(str(value).lower().replace("\xa0", " ").strip().split())


def _find_cols(headers: list[str]) -> tuple[int, int, int, int | None, int | None]:
    """Find column indices for SKU, quantity, comment, completed_ops, target_section.

    Returns (sku_idx, qty_idx, comment_idx, completed_ops_idx, target_section_idx).
    ``sku_idx``, ``qty_idx``, ``comment_idx`` default to 0, 1, 2 if not found.
    ``completed_ops_idx``, ``target_section_idx`` default to ``None`` if not found.
    """
    sku_idx: int = 0
    qty_idx: int = 1
    comment_idx: int = 2
    completed_ops_idx: int | None = None
    target_section_idx: int | None = None
    normed = [_norm_hdr(h) for h in headers]
    for i, h in enumerate(normed):
        if h in _SKU_ALIASES:
            sku_idx = i
        elif h in _QTY_ALIASES:
            qty_idx = i
        elif h in _COMMENT_ALIASES:
            comment_idx = i
        elif h in _COMPLETED_OPS_ALIASES:
            completed_ops_idx = i
        elif h in _TARGET_SECTION_ALIASES:
            target_section_idx = i
    return sku_idx, qty_idx, comment_idx, completed_ops_idx, target_section_idx


def _parse_qty(value: object) -> Decimal | None:
    """Try to parse a cell value as a positive Decimal quantity."""
    if value is None or value == "" or value == 0:
        return None
    try:
        if isinstance(value, Decimal):
            qty = value
        elif isinstance(value, (int, float)):
            qty = Decimal(str(value))
        else:
            norm = str(value).replace(" ", "").replace(",", ".").strip()
            if not norm:
                return None
            qty = Decimal(norm)
        return qty if qty > 0 else None
    except (InvalidOperation, ValueError):
        return None


def _cell_txt(value: object) -> str:
    """Convert a cell value to its string representation."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


# ─── Core functions ────────────────────────────────────────────────────────────


async def parse_remainders_excel(
    content: bytes,
    sheet_index: int = 0,
    row_selection: str | None = None,
) -> tuple[str, int, list[RemainderItem], SheetSummary]:
    """Parse an Excel file with remainders data.

    Performs basic cell-level validation (SKU not empty, quantity > 0).
    Product lookup is **not** done here — call ``_lookup_products`` separately
    or use ``apply_remainders_import`` which does it internally.

    Args:
        content: Raw bytes of the .xlsx file.
        sheet_index: 0-based sheet index.
        row_selection: Optional selection string like ``"2-10,12"``.

    Returns:
        ``(sheet_name, total_rows, items, summary)``.

    Raises:
        ValueError: If the sheet index is out of range or the sheet is empty.
    """
    from python_calamine import load_workbook

    workbook = load_workbook(BytesIO(content))
    if sheet_index < 0 or sheet_index >= len(workbook.sheet_names):
        raise ValueError(
            f"Sheet index {sheet_index} not found, "
            f"available sheets: {len(workbook.sheet_names)}"
        )

    sheet = workbook.get_sheet_by_index(sheet_index)
    rows = list(sheet.iter_rows())
    if not rows:
        raise ValueError("Workbook sheet is empty")

    # --- Detect header row ---------------------------------------------------
    header_row_idx: int | None = None
    for idx, row in enumerate(rows[:10]):
        normed = {_norm_hdr(_cell_txt(c)) for c in row}
        if _SKU_ALIASES & normed or _QTY_ALIASES & normed:
            header_row_idx = idx
            break

    if header_row_idx is None:
        header_row_idx = 0  # fallback: first row is header

    headers = [_cell_txt(c) for c in rows[header_row_idx]]
    sku_idx, qty_idx, comment_idx, completed_ops_idx, target_section_idx = _find_cols(headers)

    # --- Determine which rows to process -------------------------------------
    selected_rows: set[int] | None = None
    if row_selection:
        selected_rows = parse_row_selection(row_selection)

    data_rows: list[tuple[int, list]] = []
    if selected_rows is not None:
        # 1-based row numbers
        for rn in sorted(selected_rows):
            idx_0 = rn - 1
            if 0 <= idx_0 < len(rows) and idx_0 != header_row_idx:
                data_rows.append((rn, list(rows[idx_0])))
    else:
        for i, row in enumerate(rows[header_row_idx + 1 :], start=header_row_idx + 2):
            data_rows.append((i, list(row)))

    # --- Parse rows ----------------------------------------------------------
    items: list[RemainderItem] = []
    valid_count = 0
    invalid_count = 0
    quantity_total = 0.0

    for row_num, row in data_rows:
        raw = [_cell_txt(c) for c in row]

        sku_raw = _cell_txt(row[sku_idx] if sku_idx < len(row) else None)
        qty_val = row[qty_idx] if qty_idx < len(row) else None
        comment_raw = _cell_txt(row[comment_idx] if comment_idx < len(row) else None)
        completed_ops_raw = (
            _cell_txt(row[completed_ops_idx])
            if completed_ops_idx is not None and completed_ops_idx < len(row)
            else None
        ) or None
        target_section_name = (
            _cell_txt(row[target_section_idx])
            if target_section_idx is not None and target_section_idx < len(row)
            else None
        ) or None

        sku = sku_raw.strip() if sku_raw else ""
        comment = comment_raw if comment_raw else None
        parsed_qty = _parse_qty(qty_val)

        errors: list[str] = []
        if not sku:
            errors.append("SKU is empty")
        if parsed_qty is None:
            errors.append("Quantity is missing, zero, or not a valid number")

        # Skip completely empty rows
        if not sku and parsed_qty is None and not comment:
            continue

        item = RemainderItem(
            source_row_number=row_num,
            sku=sku,
            quantity=float(parsed_qty) if parsed_qty is not None else None,
            comment=comment,
            product_id=None,
            product_name=None,
            status="invalid" if errors else "valid",
            errors=errors,
            raw_values=raw,
            completed_operations_raw=completed_ops_raw,
            completed_stages=[],
            target_section_name=target_section_name,
            target_section_id=None,
        )

        if errors:
            invalid_count += 1
        else:
            valid_count += 1
            if parsed_qty is not None:
                quantity_total += float(parsed_qty)

        items.append(item)

    summary = SheetSummary(
        total=len(items),
        valid=valid_count,
        invalid=invalid_count,
        quantity_total=round(quantity_total, 3),
    )

    return sheet.name, len(rows), items, summary


async def _lookup_products(db: AsyncSession, items: list[RemainderItem]) -> None:
    """Batch-lookup products by SKU and update items in-place.

    Sets ``product_id``, ``product_name`` for found products.
    Marks valid items as ``invalid`` if their SKU is not found.
    """
    skus = [it.sku for it in items if it.status == "valid" and it.sku]
    if not skus:
        return

    result = await db.execute(select(Product).where(Product.sku.in_(skus)))
    products = {p.sku: p for p in result.scalars().all()}

    for item in items:
        prod = products.get(item.sku)
        if prod is not None:
            item.product_id = prod.id
            item.product_name = prod.name
        elif item.status == "valid":
            item.status = "invalid"
            item.errors.append(f"SKU '{item.sku}' not found in database")


# ─── Operations & Section resolvers ──────────────────────────────────────────


async def resolve_operations_dictionary(db: AsyncSession) -> list[dict]:
    """Return the dictionary of significant production operations.

    Returns a list of dicts in ``RouteStepsDisplay`` format:
    ``[{sequence, section_code, section_name, operation_code, operation_name, is_significant}]``
    Only ``is_significant=True AND operation_type='production'`` are included.
    Ordered by ``section.sort_order, section.id, section_operation.sort_order, section_operation.id``.
    """
    stmt = (
        select(SectionOperation, Section)
        .join(Section, Section.id == SectionOperation.section_id)
        .where(
            SectionOperation.is_significant.is_(True),
            SectionOperation.operation_type == "production",
        )
        .order_by(Section.sort_order, Section.id, SectionOperation.sort_order, SectionOperation.id)
    )
    result = await db.execute(stmt)
    return [
        {
            "sequence": so.sort_order,
            "section_code": section.code,
            "section_name": section.name,
            "operation_code": so.operation_code,
            "operation_name": so.operation_name,
            "is_significant": so.is_significant,
        }
        for so, section in result.all()
    ]


async def resolve_completed_stages(
    db: AsyncSession,
    raw_ops_str: str | None,
    ops_dict: list[dict],
    errors: list[str] | None = None,
) -> list[dict]:
    """Parse ``raw_ops_str`` and match against ``ops_dict``.

    Splits by ``,`` / ``;`` / ``|``, trims, lowercases, and exact-matches against
    ``operation_name`` (normalised). Returns a subset of ``ops_dict`` preserving
    original order (``sequence`` from dictionary, not re-calculated).

    Edge cases:
    - Empty/``—`` input → empty list, no error.
    - Duplicate operation name in input → single match (dedup).
    - Operation not found in dictionary → optional warning appended to ``errors``,
      item is **not** invalidated.
    """
    if not raw_ops_str or raw_ops_str.strip() in ("", "—", "-"):
        return []

    parts = [p.strip().lower() for p in re.split(r"[,;|]+", raw_ops_str) if p.strip()]
    if not parts:
        return []

    matched: list[dict] = []
    seen_names: set[str] = set()

    for raw_name in parts:
        found = False
        for op in ops_dict:
            op_norm = op["operation_name"].strip().lower()
            if raw_name == op_norm and op_norm not in seen_names:
                matched.append(op)
                seen_names.add(op_norm)
                found = True
                break
        if not found and errors is not None:
            errors.append(f"Операция '{raw_name}' не найдена в справочнике")

    return matched


async def resolve_target_section(
    db: AsyncSession,
    name: str | None,
    item_errors: list[str] | None = None,
) -> tuple[int | None, str | None]:
    """Resolve a section name to ``(section_id, section_name)``.

    Match is case-insensitive, trimmed.  ``production``-type sections are rejected
    (remainders cannot be imported there).  Allowed types:
    ``raw_stock, wip_stock, finished_stock, scrap, quarantine``.

    Returns ``(None, None)`` if not found or type is ``production``, with
    a warning appended to ``item_errors`` (if provided).
    """
    if not name or name.strip() in ("", "—", "-"):
        return (None, None)

    norm_name = name.strip()
    result = await db.execute(
        select(Section).where(Section.name.ilike(norm_name))
    )
    section = result.scalar_one_or_none()

    if section is None:
        if item_errors is not None:
            item_errors.append(f"Секция '{norm_name}' не найдена")
        return (None, None)

    if section.type == "production":
        if item_errors is not None:
            item_errors.append(
                f"Секция '{norm_name}' имеет тип production, "
                f"нельзя использовать как цель импорта"
            )
        return (None, None)

    return (section.id, section.name)


async def apply_remainders_import(
    db: AsyncSession,
    location_id: int,
    items: list[RemainderItem],
    quality_state: QualityState = QualityState.GOOD,
    user: User | None = None,
    clear_existing: bool = False,
    skip_invalid: bool = True,
    target_section_overrides: dict[int, int] | None = None,
) -> ImportResult:
    """Apply remainders import: create ``StockTransaction`` records.

    This function:
    1. Validates the location exists.
    2. Looks up products by SKU (``_lookup_products``).
    3. If ``clear_existing=True``, zeros out current balances for
       ``(location_id, quality_state)`` with ``ADJUSTMENT_OUT``.
       **Cannot** be combined with ``target_section_overrides``.
    4. Creates ``MANUAL_IN`` transactions for each valid row.
       Uses per-row ``to_location_id`` from ``target_section_overrides``
       or ``item.target_section_id`` (fallback to ``location_id``).
       If ``item.completed_stages`` is non-empty, appends operation names
       to the transaction comment.
    5. Commits the database session.

    Args:
        db: Database session.
        location_id: Target ``Section`` id for import.
        items: Parsed ``RemainderItem`` list (product lookup done here).
        quality_state: Quality state for all imported items.
        user: User performing the import; used for ``created_by`` fields.
        clear_existing: If ``True``, zero existing balances for the target
            ``(location, quality_state)`` before importing.
        skip_invalid: If ``True``, skip invalid rows and continue with valid
            ones; if ``False``, abort on any invalid row.
        target_section_overrides: Optional dict mapping ``source_row_number``
            to ``section_id`` for per-row target override.  Takes precedence
            over ``item.target_section_id``.

    Returns:
        ``ImportResult`` with success status, counts, errors, and transaction ids.
    """
    errors: list[str] = []
    transaction_ids: list[int] = []

    # --- Validate location ---------------------------------------------------
    location = await db.get(Section, location_id)
    if location is None:
        return ImportResult(
            success=False,
            imported_count=0,
            errors=[f"Location with id={location_id} not found"],
            transaction_ids=[],
        )

    # --- Look up products ----------------------------------------------------
    await _lookup_products(db, items)

    valid_items = [it for it in items if it.status == "valid" and it.product_id is not None]
    invalid_items = [it for it in items if it.status == "invalid"]

    for it in invalid_items:
        errors.append(f"Row {it.source_row_number}: {', '.join(it.errors)} (SKU={it.sku})")

    # --- Abort if not skipping invalid ---------------------------------------
    if not skip_invalid and invalid_items:
        return ImportResult(
            success=False,
            imported_count=0,
            errors=errors,
            transaction_ids=[],
        )

    # --- Check clear_existing + per-row override incompatibility ------------
    if clear_existing and target_section_overrides is not None:
        return ImportResult(
            success=False,
            imported_count=0,
            errors=["clear_existing не поддерживается при per-row target sections"],
            transaction_ids=[],
        )

    svc = StockCommandService()

    # --- Clear existing balances if requested --------------------------------
    if clear_existing:
        rows = await db.execute(
            select(StockBalance).where(
                StockBalance.location_id == location_id,
                StockBalance.quality_state == quality_state,
            )
        )
        for bal in rows.scalars().all():
            if bal.balance_qty > 0:
                cmd = StockCommand(
                    product_id=bal.product_id,
                    from_location_id=location_id,
                    quantity=bal.balance_qty,
                    reason=Reason.ADJUSTMENT_OUT,
                    quality_state=quality_state,
                    comment="Очистка перед импортом остатков",
                    source_ref="import_remainders_excel",
                    created_by=user.id if user else 1,
                    created_by_user_name=(
                        user.full_name
                        if (user and user.full_name)
                        else (user.username if user else "system")
                    ),
                )
                tx = await svc.record(db, cmd)
                transaction_ids.append(tx.id)

    # --- Import valid items --------------------------------------------------
    imported_count = 0
    for item in valid_items:
        # Determine per-row to_location_id
        to_loc: int = location_id
        if target_section_overrides:
            to_loc = target_section_overrides.get(
                item.source_row_number, to_loc
            )
        if to_loc == location_id:
            to_loc = item.target_section_id or location_id

        # Build comment with completed operations
        final_comment: str | None = item.comment
        if item.completed_stages:
            ops_names = ", ".join(
                s["operation_name"] for s in item.completed_stages
            )
            sep = " | " if final_comment else ""
            final_comment = f"{final_comment or ''}{sep}операции: {ops_names}"

        cmd = StockCommand(
            product_id=item.product_id,  # type: ignore[arg-type]
            to_location_id=to_loc,
            quantity=Decimal(str(item.quantity)),
            reason=Reason.MANUAL_IN,
            quality_state=quality_state,
            comment=final_comment or "Импорт остатков из Excel",
            source_ref="import_remainders_excel",
            created_by=user.id if user else 1,
            created_by_user_name=(
                user.full_name
                if (user and user.full_name)
                else (user.username if user else "system")
            ),
        )
        tx = await svc.record(db, cmd)
        transaction_ids.append(tx.id)
        imported_count += 1

    await db.commit()

    return ImportResult(
        success=True,
        imported_count=imported_count,
        errors=errors,
        transaction_ids=transaction_ids,
    )


async def generate_remainders_template_for_location(
    db: AsyncSession,
    location_id: int,
) -> bytes:
    """Generate an Excel template (.xlsx) for remainders import.

    The template has five columns:
    ``SKU / Артикул | Количество | Целевая секция | Выполненные операции | Комментарий``
    with example rows.

    Args:
        db: Database session.
        location_id: Location to validate existence.

    Returns:
        Raw bytes of the .xlsx file.

    Raises:
        ValueError: If the location does not exist.
    """
    from openpyxl import Workbook

    location = await db.get(Section, location_id)
    if location is None:
        raise ValueError(f"Location with id={location_id} not found")

    # Получаем все значимые производственные операции
    ops_query = (
        select(SectionOperation)
        .join(Section, Section.id == SectionOperation.section_id)
        .where(
            SectionOperation.is_significant == True,
            SectionOperation.operation_type == "production",
        )
        .order_by(Section.sort_order, Section.id, SectionOperation.sort_order, SectionOperation.id)
    )
    ops = (await db.execute(ops_query)).scalars().all()

    op_names: list[str] = []
    seen: set[str] = set()
    for op in ops:
        if op.operation_name not in seen:
            seen.add(op.operation_name)
            op_names.append(op.operation_name)

    # Fallback если в БД нет операций
    if not op_names:
        op_names = ["Дробеструй", "Сверловка"]

    # Получаем доступные целевые секции (складские типы)
    sections_query = (
        select(Section)
        .where(
            Section.type.in_([
                "raw_stock", "wip_stock", "finished_stock",
                "scrap", "quarantine",
            ]),
            Section.is_active == True,
        )
        .order_by(Section.sort_order, Section.name)
    )
    sections = (await db.execute(sections_query)).scalars().all()
    section_names = [s.name for s in sections]

    wb = Workbook()
    ws = wb.active
    ws.title = "Импорт остатков"

    # Первая строка: Справочник доступных операций и секций
    hint_parts = [f"Доступные операции: {', '.join(op_names)}"]
    if section_names:
        hint_parts.append(f"Доступные секции: {', '.join(section_names)}")
    ws.append(["\n".join(hint_parts)])

    # Пять колонок: SKU / Артикул | Количество | Целевая секция | Выполненные операции | Комментарий
    ws.append(["SKU / Артикул", "Количество", "Целевая секция", "Выполненные операции", "Комментарий"])
    ws.append(["Пример-001", 100, section_names[0] if section_names else "", op_names[0] if op_names else "", ""])
    ws.append(["Пример-002", 50, "", "", ""])

    ws.column_dimensions["A"].width = 25
    ws.column_dimensions["B"].width = 15
    ws.column_dimensions["C"].width = 25
    ws.column_dimensions["D"].width = 30
    ws.column_dimensions["E"].width = 30

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()
