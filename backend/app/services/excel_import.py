from __future__ import annotations

import hashlib
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import Any

from app.domain.dimensions import (
    LENGTH_MM,
    DimensionsValidationError,
    canonicalize_dimensions,
    dimensions_equal,
    parse_length_m_to_mm,
)
from app.services.color_extraction import resolve_payload_color

SUPPORTED_EXCEL_EXTENSIONS = {".xls", ".xlsx", ".xlsm", ".xlsb", ".ods"}

HEADER_ALIASES = {
    "sku": "Артикул",
    "replenishment": "пополнение",
    "product_name": "Наименование",
    "raw_stock_ktm": "остатки сырья на КТМ",
    "color": "Цвет",
    "input_quantity": "кол-во шт. в 2,7",
    "input_length": "Длина, м",
    "operation": "Пробивка/сверловка",
    "packaging": "Упаковка",
    "note": "Примечание",
    "output_length": "Длина после упак, м",
    "output_quantity": "кол-во штук готовой продукции",
    "west_quantity": "Запад",
    "east_quantity": "Восток",
    "output_kind": "Вид конечного продукта",
    "comments": "Комментарии",
    "packaging_1_8_quantity": "Упаковка в 1,8",
    "add_quantity": "добавить",
    "due_date": "Срок готовности",
    "customer": "Клиент",
    "priority": "Приоритет",
    "order_ref": "Заказ",
}

MONTHS_RU = {
    "январ": 1,
    "феврал": 2,
    "март": 3,
    "апрел": 4,
    "ма": 5,
    "июн": 6,
    "июл": 7,
    "август": 8,
    "сентябр": 9,
    "октябр": 10,
    "ноябр": 11,
    "декабр": 12,
}


@dataclass(slots=True)
class ParsedPlanRow:
    source_row_numbers: list[int]
    source_sku: str
    source_name: str | None
    quantity: Decimal
    source_ref: str
    source_fingerprint: str
    source_row_hash: str
    payload: dict[str, Any]
    warnings: list[str]
    errors: list[str]
    # Операция группы строк (ADR-0003): один вход, 1..N выходов.
    input_quantity: Decimal | None = None
    input_dimensions: dict[str, Any] | None = None
    outputs: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ParsedWorkbook:
    sheet_name: str
    header_row_number: int
    total_rows: int
    parsed_rows: list[ParsedPlanRow]
    period_start: date | None
    period_end: date | None
    warnings: list[str]
    row_selection: str | None = None
    selected_row_numbers: list[int] | None = None
    auto_included_row_numbers: list[int] | None = None
    normalize_hanger_quantity: bool = True


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def validate_excel_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXCEL_EXTENSIONS:
        raise ValueError(f"Unsupported Excel file extension: {ext or '<none>'}")
    return ext


def detect_workbook_format(content: bytes, filename: str) -> str:
    if content.startswith(b"\xD0\xCF\x11\xE0"):
        return "xls-ole-biff"
    if content.startswith(b"PK\x03\x04"):
        return "zip-workbook"
    return Path(filename).suffix.lower().lstrip(".") or "unknown"


def _normalize_column_mapping(mapping: dict[str, Any] | None) -> dict[str, str]:
    """Normalize column_mapping to dict[str, str], supporting both old (str) and new (object) formats."""
    if not mapping:
        return {}
    result = {}
    for key, value in mapping.items():
        if isinstance(value, dict):
            result[key] = str(value.get("header", key))
        else:
            result[key] = str(value)
    return result


def parse_factory_plan_workbook(
    content: bytes,
    filename: str,
    sheet_index: int = 0,
    column_mapping: dict[str, str] | None = None,
    row_selection: str | None = None,
    normalize_hanger_quantity: bool = True,
) -> ParsedWorkbook:
    validate_excel_extension(filename)

    try:
        from python_calamine import load_workbook
    except ImportError as exc:  # pragma: no cover - deployment guard
        raise RuntimeError("python-calamine is not installed") from exc

    workbook = load_workbook(BytesIO(content))
    if sheet_index < 0 or sheet_index >= len(workbook.sheet_names):
        raise ValueError(f"Sheet index {sheet_index} not found")

    sheet = workbook.get_sheet_by_index(sheet_index)
    rows = list(sheet.iter_rows())
    if not rows:
        raise ValueError("Workbook sheet is empty")

    effective_mapping = {**HEADER_ALIASES, **_normalize_column_mapping(column_mapping)}
    header_index = _find_header_row(rows, effective_mapping)
    headers = [_cell_text(cell) for cell in rows[header_index]]
    column_map = _build_column_map(headers, effective_mapping)
    _ensure_required_columns(column_map)

    period_start, period_end = _parse_period(rows[:header_index], sheet.name)
    merged_anchors = _merged_cell_anchors(sheet)
    parsed_rows = _parse_rows(
        rows,
        header_index,
        headers,
        column_map,
        period_start,
        period_end,
        merged_anchors,
    )
    selected_rows = parse_row_selection(row_selection) if row_selection else None
    auto_included_rows: set[int] = set()
    if selected_rows is not None:
        filtered_rows: list[ParsedPlanRow] = []
        for parsed_row in parsed_rows:
            row_numbers = parsed_row.source_row_numbers
            if any(row_no in selected_rows for row_no in row_numbers):
                missing = sorted(row_no for row_no in row_numbers if row_no not in selected_rows)
                if missing:
                    marker = f"paired_row_auto_included:{','.join(str(row_no) for row_no in missing)}"
                    if marker not in parsed_row.warnings:
                        parsed_row.warnings.append(marker)
                    auto_included_rows.update(missing)
                filtered_rows.append(parsed_row)
        parsed_rows = filtered_rows

    warnings = []
    if selected_rows is not None:
        warnings.append(f"row_selection_applied:{','.join(str(row_no) for row_no in sorted(selected_rows))}")
        if auto_included_rows:
            warnings.append(
                f"row_selection_auto_included:{','.join(str(row_no) for row_no in sorted(auto_included_rows))}"
            )

    return ParsedWorkbook(
        sheet_name=sheet.name,
        header_row_number=header_index + 1,
        total_rows=len(rows),
        parsed_rows=parsed_rows,
        period_start=period_start,
        period_end=period_end,
        warnings=warnings,
        row_selection=row_selection.strip() if row_selection else None,
        selected_row_numbers=sorted(selected_rows) if selected_rows is not None else None,
        auto_included_row_numbers=sorted(auto_included_rows) if auto_included_rows else None,
        normalize_hanger_quantity=normalize_hanger_quantity,
    )


def parse_row_selection(value: str) -> set[int]:
    """Parse selection string like `5,7,12-15` into a set of 1-based row numbers."""
    selected: set[int] = set()
    normalized = value.strip()
    if not normalized:
        raise ValueError("row_selection must not be empty")

    for token in normalized.split(","):
        part = token.strip()
        if not part:
            raise ValueError("row_selection has an empty segment")
        if "-" in part:
            bounds = [x.strip() for x in part.split("-", maxsplit=1)]
            if len(bounds) != 2 or not bounds[0].isdigit() or not bounds[1].isdigit():
                raise ValueError(f"Invalid row range '{part}'")
            start = int(bounds[0])
            end = int(bounds[1])
            if start <= 0 or end <= 0:
                raise ValueError(f"Row numbers must be positive in '{part}'")
            if end < start:
                raise ValueError(f"Invalid row range '{part}': end is less than start")
            selected.update(range(start, end + 1))
            continue

        if not part.isdigit():
            raise ValueError(f"Invalid row number '{part}'")
        row_no = int(part)
        if row_no <= 0:
            raise ValueError(f"Row number must be positive: '{part}'")
        selected.add(row_no)

    return selected


def _find_header_row(rows: list[list[Any]], mapping: dict[str, str]) -> int:
    required_keys = ["sku", "product_name"]
    quantity_key = "quantity" if "quantity" in mapping else "output_quantity"
    required_keys.append(quantity_key)
    required_headers = {_normalize_header(mapping[key]) for key in required_keys if key in mapping}
    if len(required_headers) < len(required_keys):
        raise ValueError("Could not determine required headers from mapping")
    for idx, row in enumerate(rows[:30]):
        values = {_normalize_header(_cell_text(cell)) for cell in row}
        if required_headers.issubset(values):
            return idx

    # Build diagnostic info for better error message
    found_headers: set[str] = set()
    for idx, row in enumerate(rows[:30]):
        values = {_normalize_header(_cell_text(cell)) for cell in row}
        if values & required_headers:  # If any required headers found
            found_headers.update(values & required_headers)

    missing = required_headers - found_headers

    # Collect all unique headers found for debugging
    all_found_headers: set[str] = set()
    for idx, row in enumerate(rows[:30]):
        values = {_normalize_header(_cell_text(cell)) for cell in row if _normalize_header(_cell_text(cell))}
        all_found_headers.update(values)

    raise ValueError(
        f"Required header row not found. "
        f"Missing headers: {', '.join(sorted(missing))}. "
        f"Searched first {min(30, len(rows))} rows. "
        f"Found headers: {', '.join(sorted(all_found_headers))}"
    )


def _build_column_map(headers: list[str], mapping: dict[str, str]) -> dict[str, int]:
    result = {}
    for key, header in mapping.items():
        normalized = _normalize_header(header)
        for index, candidate in enumerate(headers):
            if _normalize_header(candidate) == normalized:
                result[key] = index
                break
    return result


def _ensure_required_columns(column_map: dict[str, int]) -> None:
    missing = [name for name in ("sku",) if name not in column_map]
    if "quantity" not in column_map and "output_quantity" not in column_map:
        missing.append("quantity/output_quantity")
    if missing:
        raise ValueError(f"Required columns are missing: {', '.join(missing)}")


def _parse_rows(
    rows: list[list[Any]],
    header_index: int,
    headers: list[str],
    column_map: dict[str, int],
    period_start: date | None,
    period_end: date | None,
    merged_anchors: dict[tuple[int, int], int] | None = None,
) -> list[ParsedPlanRow]:
    parsed: list[ParsedPlanRow] = []
    last_full_by_sku: dict[str, dict[str, Any]] = {}
    merged_anchors = merged_anchors or {}
    # Группа строк = одна позиция (ADR-0003): строка с собственным входом
    # открывает группу, строка-продолжение (вход пуст/в merged-диапазоне) —
    # ещё один выход той же группы. Группировка активна только при наличии
    # входных колонок в шаблоне (упаковочный план).
    grouping_enabled = "input_quantity" in column_map or "input_length" in column_map
    open_group: ParsedPlanRow | None = None
    open_group_raws: list[dict[str, Any]] = []

    for row_number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        raw = {key: _cell(row, index) for key, index in column_map.items()}
        raw_columns = _raw_columns(headers, row)
        raw_columns_meta = _raw_columns_meta(headers, row)
        sku = _cell_text(raw.get("sku"))
        quantity = _decimal_or_none(raw.get("quantity") or raw.get("output_quantity"))

        merged_continuation = (
            grouping_enabled
            and open_group is not None
            and _is_merged_continuation(open_group, raw, row_number, column_map, merged_anchors)
        )

        if not sku and quantity is None:
            # Пустая строка внутри листа закрывает группу, если не накрыта
            # merged-диапазоном входа текущей группы.
            if not merged_continuation:
                open_group, open_group_raws = None, []
            continue
        if not sku and not merged_continuation:
            continue
        if quantity is None or quantity <= 0:
            # Строка без выхода: хвост merged-диапазона/пустой вход группу не рвёт,
            # строка с собственным входом — новая операция, закрывает предыдущую.
            if not merged_continuation and _has_own_input(raw):
                open_group, open_group_raws = None, []
            continue

        if (
            grouping_enabled
            and open_group is not None
            and (merged_continuation or _is_adjacent_continuation(open_group, sku, raw, row_number))
        ):
            open_group_raws.append(_jsonable(raw))
            _append_group_output(
                open_group,
                open_group_raws,
                row_number,
                raw,
                raw_columns,
                raw_columns_meta,
                quantity,
            )
            continue

        enriched, inherited = _inherit_same_sku_context(raw, last_full_by_sku.get(sku))
        if _is_full_context(raw):
            last_full_by_sku[sku] = raw

        candidate = _make_plan_row(
            row_number,
            enriched,
            raw_columns,
            raw_columns_meta,
            quantity,
            period_start,
            period_end,
            inherited,
        )

        if parsed and _can_join_as_paired_profile(parsed[-1], candidate):
            _join_paired_component(parsed[-1], candidate)
            open_group, open_group_raws = None, []
            continue

        parsed.append(candidate)
        open_group = candidate
        open_group_raws = [_jsonable(enriched)]

    _check_group_balances(parsed)
    return parsed


def _merged_cell_anchors(sheet: Any) -> dict[tuple[int, int], int]:
    """Карта merged-ячеек листа: (row0, col0) → row0 якоря диапазона.

    Объединённая ячейка входа, растянутая на несколько строк, — признак
    группы «одна операция, несколько выходов» (ADR-0003). Форматы без
    merged-метаданных (xls/ods) дают пустую карту — тогда работает только
    эвристика «тот же артикул + пустой вход».
    """
    try:
        ranges = sheet.merged_cell_ranges
    except Exception:  # pragma: no cover - формат без merged-метаданных
        return {}
    anchors: dict[tuple[int, int], int] = {}
    for cell_range in ranges or []:
        try:
            (start_row, start_col), (end_row, end_col) = cell_range
        except (TypeError, ValueError):
            continue
        for row_idx in range(int(start_row), int(end_row) + 1):
            for col_idx in range(int(start_col), int(end_col) + 1):
                anchors[(row_idx, col_idx)] = int(start_row)
    return anchors


def _has_own_input(raw: dict[str, Any]) -> bool:
    return bool(_cell_text(raw.get("input_quantity")) or _cell_text(raw.get("input_length")))


def _is_merged_continuation(
    group: ParsedPlanRow,
    raw: dict[str, Any],
    row_number: int,
    column_map: dict[str, int],
    merged_anchors: dict[tuple[int, int], int],
) -> bool:
    """Строка накрыта merged-диапазоном входа/артикула, якорь которого — в группе."""
    if group.payload.get("paired_profile"):
        return False
    if _has_own_input(raw):
        return False
    row0 = row_number - 1
    group_rows0 = {number - 1 for number in group.source_row_numbers}
    for key in ("input_quantity", "input_length", "sku"):
        col = column_map.get(key)
        if col is None:
            continue
        anchor = merged_anchors.get((row0, col))
        if anchor is not None and anchor != row0 and anchor in group_rows0:
            return True
    return False


def _is_adjacent_continuation(
    group: ParsedPlanRow, sku: str, raw: dict[str, Any], row_number: int
) -> bool:
    """Соседняя строка того же SKU без собственного входа — ещё один выход.

    Соседние строки того же SKU С собственным входом — отдельные операции
    (ADR-0003), поэтому требуем пустой вход и непустой вход у открывающей строки.
    """
    if group.payload.get("paired_profile"):
        return False
    if _has_own_input(raw):
        return False
    if not sku or sku != group.source_sku:
        return False
    if row_number != group.source_row_numbers[-1] + 1:
        return False
    return group.input_quantity is not None


def _parse_length_cell(value: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Ячейка длины Excel (метры) → канонические dimensions в мм либо текст ошибки.

    Пустая ячейка — легальные «безразмерные» (None, None); мусор → (None, текст),
    импорт не падает, строка получает warning.
    """
    if value is None or _cell_text(value) == "":
        return None, None
    try:
        return canonicalize_dimensions({LENGTH_MM: parse_length_m_to_mm(value)}), None
    except DimensionsValidationError as exc:
        return None, str(exc)


def _append_group_output(
    group: ParsedPlanRow,
    group_raws: list[dict[str, Any]],
    row_number: int,
    raw: dict[str, Any],
    raw_columns: dict[str, str],
    raw_columns_meta: list[dict[str, Any]],
    quantity: Decimal,
) -> None:
    """Строка-продолжение группы: ещё один выход той же операции (ADR-0003)."""
    output_dims, length_warning = _parse_length_cell(raw.get("output_length"))
    if length_warning is not None:
        group.warnings.append(f"invalid_output_length:row={row_number}")

    group.outputs.append(
        {
            "row_number": row_number,
            "quantity": _decimal_to_str(quantity),
            "dimensions": output_dims,
        }
    )
    group.quantity = group.quantity + quantity
    group.source_row_numbers.append(row_number)
    group.payload["row_numbers"] = group.source_row_numbers
    group.payload["outputs"] = group.outputs
    group.source_ref = f"rows:{group.source_row_numbers[0]}-{group.source_row_numbers[-1]}"

    # Входная длина, унаследованная от единственного выхода («вход без резки»),
    # перестаёт быть верной при появлении второго выхода с другой длиной —
    # сбрасываем, типовой размер подставит сервис импорта.
    input_info = dict(group.payload.get("input") or {})
    if input_info.get("inferred") and not dimensions_equal(group.input_dimensions, output_dims):
        group.input_dimensions = None
        input_info["dimensions"] = None
        input_info["inferred"] = False
        group.payload["input"] = input_info

    raw_columns_by_row = dict(group.payload.get("raw_columns_by_row") or {})
    raw_columns_by_row.setdefault(str(group.source_row_numbers[0]), group.payload.get("raw_columns") or {})
    raw_columns_by_row[str(row_number)] = raw_columns
    group.payload["raw_columns_by_row"] = raw_columns_by_row
    raw_columns_meta_by_row = dict(group.payload.get("raw_columns_meta_by_row") or {})
    raw_columns_meta_by_row.setdefault(str(group.source_row_numbers[0]), group.payload.get("raw_columns_meta") or [])
    raw_columns_meta_by_row[str(row_number)] = raw_columns_meta
    group.payload["raw_columns_meta_by_row"] = raw_columns_meta_by_row

    group.source_fingerprint = _hash_json(
        _fingerprint_payload(group.source_sku, group.quantity, group.payload)
    )
    group.source_row_hash = _hash_json(
        {"row_numbers": group.source_row_numbers, "raws": group_raws}
    )


def _check_group_balances(parsed: list[ParsedPlanRow]) -> None:
    """Баланс группы: вход × длина = Σ(выход × длина) — всегда сходится точно
    (ADR-0003). Расхождение — warning, не ошибка: импорт терпим к аномалиям
    данных завода, решение остаётся за оператором на предпросмотре.
    Проверяем только группы (2+ выхода): у одиночных строк входное количество
    может быть унаследовано из контекста и не обязано биться с выходом."""
    for row in parsed:
        if len(row.outputs) < 2:
            continue
        if row.input_quantity is None or not row.input_dimensions:
            continue
        input_length = row.input_dimensions.get(LENGTH_MM)
        if not isinstance(input_length, (int, float)):
            continue
        total_out = Decimal("0")
        complete = bool(row.outputs)
        for entry in row.outputs:
            out_dims = entry.get("dimensions") or {}
            out_length = out_dims.get(LENGTH_MM)
            out_quantity = _decimal_or_none(entry.get("quantity"))
            if not isinstance(out_length, (int, float)) or out_quantity is None:
                complete = False
                break
            total_out += out_quantity * Decimal(str(out_length))
        if not complete:
            continue
        total_in = row.input_quantity * Decimal(str(input_length))
        if total_in != total_out:
            marker = f"plan_group_balance_mismatch:in={total_in.normalize()}mm,out={total_out.normalize()}mm"
            if marker not in row.warnings:
                row.warnings.append(marker)


def _inherit_same_sku_context(raw: dict[str, Any], previous: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    if previous is None or _cell_text(raw.get("product_name")):
        return raw, False

    enriched = dict(raw)
    inherited = False
    for key in ("product_name", "raw_stock_ktm", "input_quantity", "input_length"):
        if not _cell_text(enriched.get(key)) and _cell_text(previous.get(key)):
            enriched[key] = previous.get(key)
            inherited = True
    return enriched, inherited


def _is_full_context(raw: dict[str, Any]) -> bool:
    return bool(
        _cell_text(raw.get("sku"))
        and _cell_text(raw.get("product_name"))
        and _cell_text(raw.get("raw_stock_ktm"))
        and _cell_text(raw.get("input_quantity"))
    )


def _make_plan_row(
    row_number: int,
    raw: dict[str, Any],
    raw_columns: dict[str, str],
    raw_columns_meta: list[dict[str, Any]],
    quantity: Decimal,
    period_start: date | None,
    period_end: date | None,
    inherited: bool,
) -> ParsedPlanRow:
    component = _component_from_raw(row_number, raw)
    raw_operation = _cell_text(raw.get("operation")) or None
    raw_output_kind = _cell_text(raw.get("output_kind")) or None
    product_name = _cell_text(raw.get("product_name")) or None
    # Габариты операции (ADR-0003): Excel-метры → мм через доменный парсер.
    input_quantity = _decimal_or_none(raw.get("input_quantity"))
    input_dims, input_length_warning = _parse_length_cell(raw.get("input_length"))
    output_dims, output_length_warning = _parse_length_cell(raw.get("output_length"))
    # Пустая «Длина, м» при заполненном выходе — вход без резки: входная длина
    # совпадает с выходной. Помечаем inferred: при втором выходе с другой длиной
    # догадка сбрасывается, типовой размер подставит сервис импорта.
    input_inferred = False
    if input_dims is None and input_length_warning is None and output_dims is not None:
        input_dims = output_dims
        input_inferred = True
    outputs: list[dict[str, Any]] = [
        {
            "row_number": row_number,
            "quantity": _decimal_to_str(quantity),
            "dimensions": output_dims,
        }
    ]
    payload = {
        "row_numbers": [row_number],
        "components": [component],
        "source_name": product_name,
        "color": resolve_payload_color(_cell_text(raw.get("color")) or None, product_name),
        "input_length": _decimal_to_str(_decimal_or_none(raw.get("input_length"))),
        "operation": raw_operation,
        "operation_code": None,
        "operation_name": None,
        "additional_pack_operations": [],
        "normalized_pack_op_family": "NONE",
        "packaging": _cell_text(raw.get("packaging")) or None,
        "note": _cell_text(raw.get("note")) or None,
        "output_length": _decimal_to_str(_decimal_or_none(raw.get("output_length"))),
        "output_kind": raw_output_kind,
        "output_kind_raw": raw_output_kind,
        "shipping": {
            "west_quantity": _decimal_to_str(_decimal_or_none(raw.get("west_quantity"))),
            "east_quantity": _decimal_to_str(_decimal_or_none(raw.get("east_quantity"))),
        },
        "comments": _cell_text(raw.get("comments")) or None,
        "packaging_1_8_quantity": _decimal_to_str(_decimal_or_none(raw.get("packaging_1_8_quantity"))),
        "add_quantity": _decimal_to_str(_decimal_or_none(raw.get("add_quantity"))),
        "due_date": (_parse_date(raw.get("due_date")).isoformat() if _parse_date(raw.get("due_date")) else None),
        "customer": _cell_text(raw.get("customer")) or None,
        "priority": _int_or_none(raw.get("priority")),
        "order_ref": _cell_text(raw.get("order_ref")) or None,
        "period_start": period_start.isoformat() if period_start else None,
        "period_end": period_end.isoformat() if period_end else None,
        "context_inherited": inherited,
        "paired_profile": False,
        "input": {
            "quantity": _decimal_to_str(input_quantity),
            "dimensions": input_dims,
            "inferred": input_inferred,
        },
        "outputs": outputs,
        "raw_columns": raw_columns,
        "raw_columns_meta": raw_columns_meta,
        "raw_excel_row": {k: _cell_text(v) for k, v in raw.items()},
    }

    source_sku = component["sku"]
    source_ref = f"rows:{row_number}"
    warnings = []
    errors = []
    if not _cell_text(raw.get("product_name")):
        warnings.append("product_name_missing")
    if input_length_warning is not None:
        warnings.append(f"invalid_input_length:row={row_number}")
    if output_length_warning is not None:
        warnings.append(f"invalid_output_length:row={row_number}")
    fingerprint_payload = _fingerprint_payload(source_sku, quantity, payload)
    row_hash = _hash_json({"row_number": row_number, "raw": _jsonable(raw)})
    return ParsedPlanRow(
        source_row_numbers=[row_number],
        source_sku=source_sku,
        source_name=_cell_text(raw.get("product_name")) or None,
        quantity=quantity,
        source_ref=source_ref,
        source_fingerprint=_hash_json(fingerprint_payload),
        source_row_hash=row_hash,
        payload=payload,
        warnings=warnings,
        errors=errors,
        input_quantity=input_quantity,
        input_dimensions=input_dims,
        outputs=outputs,
    )


def _component_from_raw(row_number: int, raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "row_number": row_number,
        "sku": _cell_text(raw.get("sku")),
        "name": _cell_text(raw.get("product_name")) or None,
        "raw_stock_ktm": _decimal_to_str(_decimal_or_none(raw.get("raw_stock_ktm"))),
        "input_quantity": _decimal_to_str(_decimal_or_none(raw.get("input_quantity"))),
        "input_length": _decimal_to_str(_decimal_or_none(raw.get("input_length"))),
        "replenishment": _cell_text(raw.get("replenishment")) or None,
    }


def _raw_columns(headers: list[str], row: list[Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for index, header in enumerate(headers):
        key = _cell_text(header)
        if not key:
            key = f"column_{index + 1}"
        result[key] = _cell_text(_cell(row, index))
    return result


def _raw_columns_meta(headers: list[str], row: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, header in enumerate(headers):
        header_text = _cell_text(header)
        if not header_text:
            header_text = f"column_{index + 1}"
        result.append(
            {
                "index": index + 1,
                "letter": _excel_column_letter(index + 1),
                "header": header_text,
                "value": _cell_text(_cell(row, index)),
            }
        )
    return result


def _excel_column_letter(index: int) -> str:
    if index <= 0:
        return ""
    letters: list[str] = []
    value = index
    while value > 0:
        value, rem = divmod(value - 1, 26)
        letters.append(chr(ord("A") + rem))
    return "".join(reversed(letters))


def _can_join_as_paired_profile(previous: ParsedPlanRow, current: ParsedPlanRow) -> bool:
    if previous.payload.get("paired_profile"):
        return False
    if previous.source_sku == current.source_sku:
        return False
    if current.source_name:
        return False

    comparable_fields = ("color", "output_length", "output_kind")
    same_output = all(previous.payload.get(field) == current.payload.get(field) for field in comparable_fields)
    same_quantity = previous.quantity == current.quantity
    return same_output and same_quantity


def _join_paired_component(previous: ParsedPlanRow, current: ParsedPlanRow) -> None:
    previous.source_row_numbers.extend(current.source_row_numbers)
    previous.payload["row_numbers"] = previous.source_row_numbers
    previous.payload["components"].extend(current.payload["components"])
    previous.payload["paired_profile"] = True
    raw_columns_by_row = dict(previous.payload.get("raw_columns_by_row") or {})
    raw_columns_by_row[str(previous.source_row_numbers[0])] = previous.payload.get("raw_columns") or {}
    raw_columns_by_row[str(current.source_row_numbers[0])] = current.payload.get("raw_columns") or {}
    previous.payload["raw_columns_by_row"] = raw_columns_by_row
    raw_columns_meta_by_row = dict(previous.payload.get("raw_columns_meta_by_row") or {})
    raw_columns_meta_by_row[str(previous.source_row_numbers[0])] = previous.payload.get("raw_columns_meta") or []
    raw_columns_meta_by_row[str(current.source_row_numbers[0])] = current.payload.get("raw_columns_meta") or []
    previous.payload["raw_columns_meta_by_row"] = raw_columns_meta_by_row
    previous.source_sku = "+".join(component["sku"] for component in previous.payload["components"])
    previous.source_ref = f"rows:{previous.source_row_numbers[0]}-{previous.source_row_numbers[-1]}"
    previous.warnings = [warning for warning in previous.warnings if warning != "product_name_missing"]
    if "paired_profile_product_unmapped" not in previous.warnings:
        previous.warnings.append("paired_profile_product_unmapped")
    previous.source_fingerprint = _hash_json(_fingerprint_payload(previous.source_sku, previous.quantity, previous.payload))
    previous.source_row_hash = _hash_json({"row_numbers": previous.source_row_numbers, "payload": previous.payload})


def _parse_period(header_rows: list[list[Any]], sheet_name: str) -> tuple[date | None, date | None]:
    text = " ".join([sheet_name, *(_cell_text(cell) for row in header_rows for cell in row)])
    lower = text.lower()
    month = None
    for token, value in MONTHS_RU.items():
        if token in lower:
            month = value
            break
    if month is None:
        return None, None

    year = 2026
    for candidate in ("2026", "26"):
        if candidate in lower:
            year = 2000 + int(candidate) if len(candidate) == 2 else int(candidate)
            break

    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    return start, end


def _cell(row: list[Any], index: int) -> Any:
    return row[index] if index < len(row) else None


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _normalize_header(value: str) -> str:
    return " ".join(_cell_text(value).lower().replace("\xa0", " ").split())


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, Decimal):
            return value
        if isinstance(value, int):
            return Decimal(value)
        if isinstance(value, float):
            return Decimal(str(value))
        normalized = str(value).replace(" ", "").replace(",", ".").strip()
        if not normalized:
            return None
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None


def _decimal_to_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        return _excel_date_to_date(value)
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _excel_date_to_date(serial: int | float) -> date:
    return date(1899, 12, 30) + timedelta(days=int(serial))


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


def _fingerprint_payload(source_sku: str, quantity: Decimal, payload: dict[str, Any]) -> dict[str, Any]:
    result = {
        "source_sku": source_sku,
        "quantity": _decimal_to_str(quantity),
        "components": [component["sku"] for component in payload.get("components", [])],
        "color": payload.get("color"),
        "input_length": payload.get("input_length"),
        "operation": payload.get("operation"),
        "operation_code": payload.get("operation_code"),
        "additional_pack_operations": payload.get("additional_pack_operations"),
        "packaging": payload.get("packaging"),
        "output_length": payload.get("output_length"),
        "output_kind": payload.get("output_kind"),
        "period_start": payload.get("period_start"),
        "period_end": payload.get("period_end"),
    }
    # Fingerprint группы включает состав выходов; для одиночных строк ключи
    # не добавляются, чтобы хэши ранее импортированных позиций не менялись
    # (идемпотентность повторного импорта).
    outputs = payload.get("outputs") or []
    if len(outputs) > 1:
        result["outputs"] = [
            {"quantity": entry.get("quantity"), "dimensions": entry.get("dimensions")}
            for entry in outputs
        ]
        input_info = payload.get("input") or {}
        result["input"] = {
            "quantity": input_info.get("quantity"),
            "dimensions": input_info.get("dimensions"),
        }
    return result


def _hash_json(value: Any) -> str:
    import json

    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, Decimal):
        return _decimal_to_str(value)
    return value
