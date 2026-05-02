from __future__ import annotations

import hashlib
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import Any


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


@dataclass(slots=True)
class ParsedWorkbook:
    sheet_name: str
    header_row_number: int
    total_rows: int
    parsed_rows: list[ParsedPlanRow]
    period_start: date | None
    period_end: date | None
    warnings: list[str]


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


def parse_factory_plan_workbook(content: bytes, filename: str, sheet_index: int = 0) -> ParsedWorkbook:
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

    header_index = _find_header_row(rows)
    headers = [_cell_text(cell) for cell in rows[header_index]]
    column_map = _build_column_map(headers)
    _ensure_required_columns(column_map)

    period_start, period_end = _parse_period(rows[:header_index], sheet.name)
    parsed_rows = _parse_rows(rows, header_index, column_map, period_start, period_end)

    warnings = []
    if period_start is None:
        warnings.append("period_not_detected")

    return ParsedWorkbook(
        sheet_name=sheet.name,
        header_row_number=header_index + 1,
        total_rows=len(rows),
        parsed_rows=parsed_rows,
        period_start=period_start,
        period_end=period_end,
        warnings=warnings,
    )


def _find_header_row(rows: list[list[Any]]) -> int:
    required = {"Артикул", "Наименование", "кол-во штук готовой продукции"}
    for idx, row in enumerate(rows[:30]):
        values = {_cell_text(cell) for cell in row}
        if required.issubset(values):
            return idx
    raise ValueError("Required header row not found")


def _build_column_map(headers: list[str]) -> dict[str, int]:
    result = {}
    for key, header in HEADER_ALIASES.items():
        normalized = _normalize_header(header)
        for index, candidate in enumerate(headers):
            if _normalize_header(candidate) == normalized:
                result[key] = index
                break
    return result


def _ensure_required_columns(column_map: dict[str, int]) -> None:
    missing = [name for name in ("sku", "output_quantity") if name not in column_map]
    if missing:
        raise ValueError(f"Required columns are missing: {', '.join(missing)}")


def _parse_rows(
    rows: list[list[Any]],
    header_index: int,
    column_map: dict[str, int],
    period_start: date | None,
    period_end: date | None,
) -> list[ParsedPlanRow]:
    parsed: list[ParsedPlanRow] = []
    last_full_by_sku: dict[str, dict[str, Any]] = {}

    for row_number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        raw = {key: _cell(row, index) for key, index in column_map.items()}
        sku = _cell_text(raw.get("sku"))
        quantity = _decimal_or_none(raw.get("output_quantity"))

        if not sku and quantity is None:
            continue
        if not sku:
            continue
        if quantity is None or quantity <= 0:
            continue

        enriched, inherited = _inherit_same_sku_context(raw, last_full_by_sku.get(sku))
        if _is_full_context(raw):
            last_full_by_sku[sku] = raw

        candidate = _make_plan_row(row_number, enriched, quantity, period_start, period_end, inherited)

        if parsed and _can_join_as_paired_profile(parsed[-1], candidate):
            _join_paired_component(parsed[-1], candidate)
            continue

        parsed.append(candidate)

    return parsed


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
    quantity: Decimal,
    period_start: date | None,
    period_end: date | None,
    inherited: bool,
) -> ParsedPlanRow:
    component = _component_from_raw(row_number, raw)
    payload = {
        "row_numbers": [row_number],
        "components": [component],
        "color": _cell_text(raw.get("color")) or None,
        "input_length": _decimal_to_str(_decimal_or_none(raw.get("input_length"))),
        "operation": _cell_text(raw.get("operation")) or None,
        "packaging": _cell_text(raw.get("packaging")) or None,
        "note": _cell_text(raw.get("note")) or None,
        "output_length": _decimal_to_str(_decimal_or_none(raw.get("output_length"))),
        "output_kind": _normalize_output_kind(_cell_text(raw.get("output_kind"))),
        "output_kind_raw": _cell_text(raw.get("output_kind")) or None,
        "shipping": {
            "west_quantity": _decimal_to_str(_decimal_or_none(raw.get("west_quantity"))),
            "east_quantity": _decimal_to_str(_decimal_or_none(raw.get("east_quantity"))),
        },
        "comments": _cell_text(raw.get("comments")) or None,
        "packaging_1_8_quantity": _decimal_to_str(_decimal_or_none(raw.get("packaging_1_8_quantity"))),
        "add_quantity": _decimal_to_str(_decimal_or_none(raw.get("add_quantity"))),
        "period_start": period_start.isoformat() if period_start else None,
        "period_end": period_end.isoformat() if period_end else None,
        "context_inherited": inherited,
        "paired_profile": False,
    }

    source_sku = component["sku"]
    source_ref = f"rows:{row_number}"
    warnings = []
    errors = []
    if not _cell_text(raw.get("product_name")):
        warnings.append("product_name_missing")
    if period_start is None:
        warnings.append("period_not_detected")

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


def _normalize_output_kind(value: str) -> str | None:
    if not value:
        return None
    normalized = value.lower().replace("/", "").replace(" ", "")
    if normalized in {"гп", "гп."}:
        return "finished_good"
    if normalized in {"пф", "пф."}:
        return "semi_finished_shipment"
    return value


def _fingerprint_payload(source_sku: str, quantity: Decimal, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_sku": source_sku,
        "quantity": _decimal_to_str(quantity),
        "components": [component["sku"] for component in payload.get("components", [])],
        "color": payload.get("color"),
        "input_length": payload.get("input_length"),
        "operation": payload.get("operation"),
        "packaging": payload.get("packaging"),
        "output_length": payload.get("output_length"),
        "output_kind": payload.get("output_kind"),
        "period_start": payload.get("period_start"),
        "period_end": payload.get("period_end"),
    }


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
