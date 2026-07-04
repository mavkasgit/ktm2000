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

_OPERATIONS_COMMENT_RE = re.compile(r"операции:\s*([^|]+)", re.IGNORECASE)


def parse_operations_from_comment(comment: str | None) -> list[str]:
    """Извлекает названия операций из комментария транзакции импорта остатков."""
    if not comment:
        return []
    match = _OPERATIONS_COMMENT_RE.search(comment)
    if not match:
        return []
    return [part.strip() for part in re.split(r"[,;|]+", match.group(1).strip()) if part.strip()]


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
    # Сырое значение и резолвнутый статус качества из колонки «Статус качества»
    quality_state_raw: str | None = None
    quality_state: QualityState = QualityState.GOOD


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
    "целевой участок", "целевая участок", "участок",
})
_QUALITY_STATE_ALIASES = frozenset({
    "quality_state", "quality", "качество",
    "статус качества", "состояние качества", "quality status",
})
_FINAL_SCRAP_ALIASES = frozenset({
    "окончательный брак",
    "оконч брак",
    "окончательный",
    "оконч",
    "final scrap",
    "final_scrap",
})
_DEFECT_SCRAP_ALIASES = frozenset({
    "брак",
    "дефект",
    "defect",
    "scrap",
})
_QUALITY_VALUE_MAP: dict[str, QualityState] = {
    "good": QualityState.GOOD,
    "годный": QualityState.GOOD,
    "годные": QualityState.GOOD,
    "г": QualityState.GOOD,
    "ok": QualityState.GOOD,
}


def _norm_hdr(value: str) -> str:
    """Normalise a header string for comparison (lowercase, collapse whitespace)."""
    return " ".join(str(value).lower().replace("\xa0", " ").strip().split())


# Порядок столбцов в шаблоне Excel (позиционный режим без заголовков):
# Артикул | Кол-во | Статус качества | Операции | Участок | Коммент.
_TEMPLATE_COL_SKU = 0
_TEMPLATE_COL_QTY = 1
_TEMPLATE_COL_QUALITY_STATE = 2
_TEMPLATE_COL_COMPLETED_OPS = 3
_TEMPLATE_COL_TARGET_SECTION = 4
_TEMPLATE_COL_COMMENT = 5


def _template_column_indices() -> tuple[int, int | None, int | None, int | None, int | None, int | None]:
    """Fixed column indices matching the downloadable Excel template."""
    return (
        _TEMPLATE_COL_SKU,
        _TEMPLATE_COL_QTY,
        _TEMPLATE_COL_COMMENT,
        _TEMPLATE_COL_COMPLETED_OPS,
        _TEMPLATE_COL_TARGET_SECTION,
        _TEMPLATE_COL_QUALITY_STATE,
    )


def _row_has_known_headers(row: list[str]) -> bool:
    """Return True if the row contains recognizable spreadsheet column headers."""
    normed = {_norm_hdr(c) for c in row if c}
    if (
        _SKU_ALIASES & normed
        or _QTY_ALIASES & normed
        or _COMPLETED_OPS_ALIASES & normed
        or _TARGET_SECTION_ALIASES & normed
        or _QUALITY_STATE_ALIASES & normed
        or _COMMENT_ALIASES & normed
    ):
        return True
    joined = _norm_hdr("".join(row))
    return "артикул" in joined and ("операц" in joined or "выполнен" in joined)


def _find_cols(
    headers: list[str],
) -> tuple[int, int | None, int | None, int | None, int | None, int | None]:
    """Find column indices for SKU, quantity, comment, completed_ops, target_section, quality.

    Returns
    ``(sku_idx, qty_idx, comment_idx, completed_ops_idx, target_section_idx, quality_state_idx)``.
    ``sku_idx`` defaults to 0 if not found.
    Other indices default to ``None`` if not found.
    """
    sku_idx: int = 0
    qty_idx: int | None = None
    comment_idx: int | None = None
    completed_ops_idx: int | None = None
    target_section_idx: int | None = None
    quality_state_idx: int | None = None
    found_sku = False
    normed = [_norm_hdr(h) for h in headers]
    for i, h in enumerate(normed):
        if h in _SKU_ALIASES:
            sku_idx = i
            found_sku = True
        elif h in _QTY_ALIASES:
            qty_idx = i
        elif h in _COMMENT_ALIASES:
            comment_idx = i
        elif h in _COMPLETED_OPS_ALIASES:
            completed_ops_idx = i
        elif h in _TARGET_SECTION_ALIASES:
            target_section_idx = i
        elif h in _QUALITY_STATE_ALIASES:
            quality_state_idx = i
    if not found_sku and len(headers) == 1:
        sku_idx = 0
    return sku_idx, qty_idx, comment_idx, completed_ops_idx, target_section_idx, quality_state_idx


def parse_quality_state_cell(
    value: str | None,
    *,
    default: QualityState = QualityState.GOOD,
) -> tuple[QualityState, str | None]:
    """Resolve a spreadsheet cell to ``QualityState``.

    Empty cells use ``default``. Unknown values return an error message.
    """
    if not value or value.strip() in ("", "—", "-"):
        return default, None
    norm = _norm_hdr(value)
    if norm in _FINAL_SCRAP_ALIASES:
        return QualityState.FINAL_SCRAP, None
    if norm in _DEFECT_SCRAP_ALIASES:
        return QualityState.SCRAP, None
    if norm in {"rework", "переделка", "доработка"}:
        return default, "Статус «Переделка» не поддерживается при импорте"
    resolved = _QUALITY_VALUE_MAP.get(norm)
    if resolved is not None:
        return resolved, None
    return default, f"Неизвестный статус качества: '{value.strip()}'"


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


def _rows_to_cell_grid(raw_rows: list[list]) -> list[list[str]]:
    """Normalise raw cell rows to string grid."""
    return [[_cell_txt(c) for c in row] for row in raw_rows]


def _detect_header_row_idx(rows: list[list[str]], scan_limit: int = 10) -> int | None:
    """Find the header row by column aliases.

    Returns ``None`` when no header row is found — caller should use the
    template column order instead.
    """
    for idx, row in enumerate(rows[:scan_limit]):
        if _row_has_known_headers(row):
            return idx
    return None


def _parse_remainders_grid(
    rows: list[list],
    row_selection: str | None = None,
    *,
    header_row_idx: int | None = None,
) -> tuple[list[RemainderItem], SheetSummary]:
    """Parse a 2D grid of cells into remainder items."""
    cell_rows = _rows_to_cell_grid(rows)
    if not cell_rows:
        raise ValueError("Нет данных для импорта")

    if header_row_idx is not None:
        resolved_header_idx: int | None = header_row_idx
        use_positional = False
    else:
        resolved_header_idx = _detect_header_row_idx(cell_rows)
        use_positional = resolved_header_idx is None

    if use_positional:
        (
            sku_idx,
            qty_idx,
            comment_idx,
            completed_ops_idx,
            target_section_idx,
            quality_state_idx,
        ) = _template_column_indices()
    else:
        headers = cell_rows[resolved_header_idx]  # type: ignore[index]
        (
            sku_idx,
            qty_idx,
            comment_idx,
            completed_ops_idx,
            target_section_idx,
            quality_state_idx,
        ) = _find_cols(headers)

    selected_rows: set[int] | None = None
    if row_selection:
        selected_rows = parse_row_selection(row_selection)

    data_rows: list[tuple[int, list[str]]] = []
    if selected_rows is not None:
        for rn in sorted(selected_rows):
            idx_0 = rn - 1
            if 0 <= idx_0 < len(cell_rows):
                if not use_positional and idx_0 == resolved_header_idx:
                    continue
                data_rows.append((rn, cell_rows[idx_0]))
    elif use_positional:
        for i, row in enumerate(cell_rows, start=1):
            data_rows.append((i, row))
    else:
        for i, row in enumerate(
            cell_rows[resolved_header_idx + 1 :],  # type: ignore[operator]
            start=resolved_header_idx + 2,  # type: ignore[operator]
        ):
            data_rows.append((i, row))

    items: list[RemainderItem] = []
    valid_count = 0
    invalid_count = 0
    quantity_total = 0.0

    for row_num, row in data_rows:
        raw = list(row)

        sku_raw = row[sku_idx] if sku_idx < len(row) else ""
        qty_val = (
            row[qty_idx]
            if qty_idx is not None and qty_idx < len(row)
            else None
        )
        comment_raw = (
            row[comment_idx]
            if comment_idx is not None and comment_idx < len(row)
            else ""
        )
        completed_ops_raw = (
            row[completed_ops_idx]
            if completed_ops_idx is not None and completed_ops_idx < len(row)
            else None
        ) or None
        target_section_name = (
            row[target_section_idx]
            if target_section_idx is not None and target_section_idx < len(row)
            else None
        ) or None
        quality_state_raw = (
            row[quality_state_idx]
            if quality_state_idx is not None and quality_state_idx < len(row)
            else None
        ) or None

        sku = sku_raw.strip() if sku_raw else ""
        comment = comment_raw if comment_raw else None
        parsed_qty = _parse_qty(qty_val)
        if parsed_qty is None and sku:
            qty_missing_or_empty = (
                qty_idx is None
                or qty_idx >= len(row)
                or not _cell_txt(qty_val).strip()
            )
            if qty_idx is None or (use_positional and qty_missing_or_empty):
                parsed_qty = Decimal("1")

        has_raw_content = any(str(v).strip() for v in raw)

        errors: list[str] = []
        if not sku:
            if has_raw_content:
                errors.append("Не удалось распознать артикул в строке")
            else:
                errors.append("Не указан артикул")
        if parsed_qty is None:
            errors.append("Количество отсутствует, равно нулю или не является числом")

        resolved_quality, quality_error = parse_quality_state_cell(quality_state_raw)
        if quality_error:
            errors.append(quality_error)

        if not sku and parsed_qty is None and not comment and not has_raw_content:
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
            quality_state_raw=quality_state_raw,
            quality_state=resolved_quality,
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
    return items, summary


_HEADER_SPLIT_MARKERS: tuple[tuple[str, str], ...] = (
    ("артикул", "выполненные операции"),
    ("артикул", "операции"),
    ("sku", "completed_operations"),
    ("sku", "операции"),
)


def _try_split_known_header(line: str) -> list[str] | None:
    """Split a concatenated header like «АртикулВыполненные операции»."""
    lower = line.lower().replace("\xa0", " ")
    for left, right in _HEADER_SPLIT_MARKERS:
        li = lower.find(left)
        ri = lower.find(right)
        if li >= 0 and ri > li:
            return [line[:ri].strip(), line[ri:].strip()]
    return None


def _try_split_sku_ops_line(line: str, sku_prefix: str | None = None) -> list[str] | None:
    """Split a concatenated data row «ЮП-460Окно, Дробеструй» into SKU + operations."""
    if sku_prefix and line.startswith(sku_prefix):
        rest = line[len(sku_prefix) :].strip()
        if rest:
            return [sku_prefix, rest]
    # SKU обычно заканчивается цифрой, операции начинаются с заглавной буквы
    match = re.match(r"^(.+?)(?<=\d)(?=[А-ЯЁA-Z])", line)
    if match:
        rest = line[match.end() :].strip()
        if rest:
            return [match.group(1), rest]
    match = re.match(r"^([\w./-]+?)(?=[А-ЯЁA-Z][а-яёa-z,])", line)
    if match:
        rest = line[match.end() :].strip()
        if rest:
            return [match.group(1), rest]
    return None


def _clipboard_text_to_rows(text: str) -> list[list[str]]:
    """Parse TSV/CSV clipboard text into a cell grid."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise ValueError("Буфер обмена пуст")

    lines = [line for line in normalized.split("\n") if line.strip()]
    if not lines:
        raise ValueError("Буфер обмена пуст")

    has_tabs = any("\t" in line for line in lines)
    has_semicolons = any(";" in line for line in lines) and not has_tabs

    if not has_tabs and not has_semicolons:
        split_rows: list[list[str]] = []
        sku_prefix: str | None = None
        for i, line in enumerate(lines):
            if i == 0:
                header_cells = _try_split_known_header(line)
                if header_cells:
                    split_rows.append(header_cells)
                    continue
            cells = _try_split_sku_ops_line(line, sku_prefix)
            if cells:
                if sku_prefix is None:
                    sku_prefix = cells[0]
                split_rows.append(cells)
                continue
            split_rows.append([line])
        if split_rows and any(len(r) > 1 for r in split_rows):
            return split_rows

    rows: list[list[str]] = []
    for line in lines:
        if "\t" in line:
            cells = line.split("\t")
        elif ";" in line:
            cells = line.split(";")
        elif re.search(r"  +", line):
            cells = re.split(r"  +", line)
        else:
            cells = [line]
        rows.append([cell.strip() for cell in cells])
    return rows


# ─── Core functions ────────────────────────────────────────────────────────────


async def parse_remainders_clipboard(
    text: str,
    row_selection: str | None = None,
) -> tuple[str, int, list[RemainderItem], SheetSummary]:
    """Parse tab-separated clipboard data copied from Excel or a spreadsheet."""
    rows = _clipboard_text_to_rows(text)
    items, summary = _parse_remainders_grid(rows, row_selection)
    return "Буфер обмена", len(rows), items, summary


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

    items, summary = _parse_remainders_grid(rows, row_selection)
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
    ``sequence`` is the route-level section order (``section.sort_order``), so
    operations from different sections never appear as «совмещено» in the UI.
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
            "sequence": section.sort_order,
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
            item_errors.append(f"Участок '{norm_name}' не найден")
        return (None, None)

    if section.type == "production":
        if item_errors is not None:
            item_errors.append(
                f"Участок '{norm_name}' имеет тип production, "
                f"нельзя использовать как цель импорта"
            )
        return (None, None)

    return (section.id, section.name)


def _resolve_item_quality_state(
    item: RemainderItem,
    default_quality_state: QualityState,
    quality_state_overrides: dict[int, QualityState] | None,
) -> QualityState:
    if quality_state_overrides and item.source_row_number in quality_state_overrides:
        return quality_state_overrides[item.source_row_number]
    return item.quality_state or default_quality_state


async def apply_remainders_import(
    db: AsyncSession,
    location_id: int,
    items: list[RemainderItem],
    quality_state: QualityState = QualityState.GOOD,
    user: User | None = None,
    clear_existing: bool = False,
    skip_invalid: bool = True,
    target_section_overrides: dict[int, int] | None = None,
    quality_state_overrides: dict[int, QualityState] | None = None,
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
        quality_state: Default quality state for rows without a column value.
        quality_state_overrides: Optional dict mapping ``source_row_number``
            to ``QualityState`` for per-row UI override.
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
            errors=["clear_existing не поддерживается при построчном указании участков"],
            transaction_ids=[],
        )

    svc = StockCommandService()

    # --- Clear existing balances if requested --------------------------------
    if clear_existing:
        qualities_to_clear = {
            _resolve_item_quality_state(item, quality_state, quality_state_overrides)
            for item in valid_items
        }
        rows = await db.execute(
            select(StockBalance).where(
                StockBalance.location_id == location_id,
                StockBalance.quality_state.in_(qualities_to_clear),
            )
        )
        for bal in rows.scalars().all():
            if bal.balance_qty > 0:
                cmd = StockCommand(
                    product_id=bal.product_id,
                    from_location_id=location_id,
                    quantity=bal.balance_qty,
                    reason=Reason.ADJUSTMENT_OUT,
                    quality_state=bal.quality_state,
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

        row_quality = _resolve_item_quality_state(
            item, quality_state, quality_state_overrides
        )
        cmd = StockCommand(
            product_id=item.product_id,  # type: ignore[arg-type]
            to_location_id=to_loc,
            quantity=Decimal(str(item.quantity)),
            reason=Reason.MANUAL_IN,
            quality_state=row_quality,
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


_TEMPLATE_SECTION_FALLBACKS: dict[str, str] = {
    "WH": "Склад сырья",
    "PREP_STOCK": "Склад подготовки",
    "WIP_WH": "Склад полуфабриката",
}
_TEMPLATE_ROW3_OPERATION_NAMES = ("Дробеструй", "Чёрный", "Стрейч")


async def _template_section_name(db: AsyncSession, code: str) -> str:
    result = await db.execute(
        select(Section.name).where(Section.code == code, Section.is_active.is_(True))
    )
    name = result.scalar_one_or_none()
    return name or _TEMPLATE_SECTION_FALLBACKS[code]


async def _template_example_row3_operations(db: AsyncSession) -> str:
    ops_dict = await resolve_operations_dictionary(db)
    known = {op["operation_name"] for op in ops_dict}
    resolved = [name for name in _TEMPLATE_ROW3_OPERATION_NAMES if name in known]
    if resolved:
        return ", ".join(resolved)
    return ", ".join(_TEMPLATE_ROW3_OPERATION_NAMES)


async def generate_remainders_template_for_location(
    db: AsyncSession,
    location_id: int,
) -> bytes:
    """Generate an Excel template (.xlsx) for remainders import.

    Те же примеры строк, что в UI модалки импорта остатков:
    ``Артикул | Кол-во | Статус качества | Операции | Участок | Коммент.``

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

    raw_name = await _template_section_name(db, "WH")
    prep_name = await _template_section_name(db, "PREP_STOCK")
    wip_name = await _template_section_name(db, "WIP_WH")
    row3_ops = await _template_example_row3_operations(db)

    wb = Workbook()
    ws = wb.active
    ws.title = "Импорт остатков"

    ws.append(["Артикул", "Кол-во", "Статус качества", "Операции", "Участок", "Коммент."])
    ws.append(["361", 200, "Годный", "", raw_name, ""])
    ws.append(["ALS-1289", 150, "Годный", "Дробеструй", prep_name, "Партия A"])
    ws.append(["ЮП-2630", 80, "Окончательный брак", row3_ops, wip_name, "Срочный заказ"])

    ws.column_dimensions["A"].width = 25
    ws.column_dimensions["B"].width = 15
    ws.column_dimensions["C"].width = 25
    ws.column_dimensions["D"].width = 18
    ws.column_dimensions["E"].width = 40
    ws.column_dimensions["F"].width = 30

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()
