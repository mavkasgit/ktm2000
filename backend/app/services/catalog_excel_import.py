"""Импорт справочника сырья из Excel (#63).

Чистый парсер без БД: чтение книги через python_calamine, строгая
валидация ячеек, отчёт об ошибках строк (row, sku, message). Поиск
артикула и применение изменений — на стороне эндпоинтов.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any

from app.models.product import Product, _length_key
from app.services.excel_import import validate_excel_extension

TEMPLATE_HEADERS = [
    "Артикул",
    "Наименование",
    "Периметр, мм",
    "Габарит, мм",
    "Длины, мм",
    "Сырьевые длины, мм",
    "Кол-во на подвесе",
    "Примечания",
    "Не дробеструится",
    "Ламируется",
    "Эквиваленты",
    "Парный профиль",
]

_HEADER_FIELDS = {
    "артикул": "sku",
    "наименование": "name",
    "примечания": "notes",
    "длины, мм": "lengths_mm",
    "сырьевые длины, мм": "raw_lengths_mm",
    "периметр, мм": "perimeter_mm",
    "габарит, мм": "mount_width_mm",
    "кол-во на подвесе": "quantities",
    "не дробеструится": "skip_shot_blast",
    "ламируется": "is_laminated",
    "эквиваленты": "aliases",
    "парный профиль": "pair_partners",
}

_TEXT_FIELDS = ("name", "notes")
_NUMBER_FIELDS = ("perimeter_mm", "mount_width_mm")
_BOOL_FIELDS = ("skip_shot_blast", "is_laminated")
_BOOL_HEADERS = {"skip_shot_blast": "Не дробеструится", "is_laminated": "Ламируется"}


@dataclass(slots=True)
class ParsedCatalogRow:
    row: int
    sku: str
    fields: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _norm_header(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).lower().replace("\xa0", " ").split())


_FIELD_HEADERS = {_HEADER_FIELDS[_norm_header(header)]: header for header in TEMPLATE_HEADERS}


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _parse_number(value: Any) -> float | None:
    """Число с запятой или точкой как дробным разделителем; мусор → None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number == number and number not in (float("inf"), float("-inf")) else None
    text = str(value).replace(" ", "").replace(",", ".").strip()
    if not text:
        return None
    try:
        return float(Decimal(text))
    except (InvalidOperation, ValueError):
        return None


def _parse_int(value: Any) -> int | None:
    """Целое > 0; допустимы «72» и «72,0»; мусор/дробные/≤0 → None."""
    number = _parse_number(value)
    if number is None or number <= 0:
        return None
    if abs(number - round(number)) > 1e-9:
        return None
    return int(round(number))


def _parse_bool(value: Any) -> bool | None:
    """«да»/«нет» без учёта регистра; пусто → None (не трогаем); иное → ошибка."""
    text = _cell_text(value).lower()
    if not text:
        return None
    if text in ("да", "нет"):
        return text == "да"
    raise ValueError(text)


def _find_header_index(rows: list[list[Any]]) -> int | None:
    for idx, row in enumerate(rows[:30]):
        known = {_norm_header(cell) for cell in row} & set(_HEADER_FIELDS)
        if "артикул" in known and len(known) >= 2:
            return idx
    return None


def parse_catalog_excel(content: bytes, filename: str) -> tuple[list[ParsedCatalogRow], list[dict[str, Any]], int]:
    """Разобрать книгу справочника.

    Возвращает ``(rows, errors, total_data_rows)``: валидные строки,
    ошибки ``{row, sku, message}`` и число заполненных строк данных.
    """
    validate_excel_extension(filename)

    try:
        from python_calamine import load_workbook
    except ImportError as exc:  # pragma: no cover - deployment guard
        raise RuntimeError("python-calamine is not installed") from exc

    workbook = load_workbook(BytesIO(content))
    sheet = workbook.get_sheet_by_index(0)
    rows = list(sheet.iter_rows())
    if not rows:
        raise ValueError("Лист книги пуст")

    header_index = _find_header_index(rows)
    if header_index is None:
        raise ValueError("Строка заголовков не найдена: ожидается колонка «Артикул» (скачайте шаблон)")

    column_map: dict[int, str] = {}
    for col, cell in enumerate(rows[header_index]):
        field_name = _HEADER_FIELDS.get(_norm_header(cell))
        if field_name and field_name not in column_map.values():
            column_map[col] = field_name

    parsed: list[ParsedCatalogRow] = []
    errors: list[dict[str, Any]] = []
    seen_skus: set[str] = set()
    total_data_rows = 0

    for row_number, raw in enumerate(rows[header_index + 1 :], start=header_index + 2):
        cells = {name: raw[col] if col < len(raw) else None for col, name in column_map.items()}
        if all(_cell_text(value) == "" for value in cells.values()):
            continue
        total_data_rows += 1

        sku = _cell_text(cells.get("sku"))
        if not sku:
            errors.append({"row": row_number, "sku": "", "message": "Не указан артикул"})
            continue
        if sku in seen_skus:
            errors.append({"row": row_number, "sku": sku, "message": "Дубликат артикула в файле"})
            continue
        seen_skus.add(sku)

        row_errors: list[str] = []
        fields: dict[str, Any] = {}

        for key in _TEXT_FIELDS:
            text = _cell_text(cells.get(key))
            if text:
                fields[key] = text

        for key in _NUMBER_FIELDS:
            text = _cell_text(cells.get(key))
            if not text:
                continue
            number = _parse_number(cells.get(key))
            if number is None:
                row_errors.append(f"{_header_of(key)}: ожидается число, получено «{text}»")
            elif number <= 0:
                row_errors.append(f"{_header_of(key)}: ожидается значение > 0, получено «{text}»")
            else:
                fields[key] = number

        lengths_text = _cell_text(cells.get("lengths_mm"))
        if lengths_text:
            lengths: list[float] = []
            for segment in lengths_text.split(","):
                segment = segment.strip()
                if not segment:
                    continue
                number = _parse_number(segment)
                if number is None or number <= 0:
                    row_errors.append(f"Длины, мм: ожидается число > 0, получено «{segment}»")
                    lengths = []
                    break
                lengths.append(number)
            if not lengths and not row_errors:
                row_errors.append("Длины, мм: список пуст")
            elif lengths:
                fields["lengths_mm"] = lengths

        # Отсутствие колонки и пустой сегмент — разные состояния:
        # отсутствие означает preserve при partial update, а пустой сегмент
        # явно очищает raw_length_mm до SQL NULL. Полностью пустая ячейка без
        # normal-длин остаётся маркером provided-column: validate/diff раскрывают
        # его в позиционный список NULL по длинам существующего артикула.
        if "raw_lengths_mm" in cells:
            raw_text = _cell_text(cells.get("raw_lengths_mm"))
            if raw_text or "lengths_mm" in fields:
                segments = raw_text.split(",") if raw_text else [""] * len(fields.get("lengths_mm") or [])
                raw_lengths: list[float | None] = []
                raw_bad = False
                for segment in segments:
                    segment = segment.strip()
                    if not segment:
                        raw_lengths.append(None)
                        continue
                    number = _parse_number(segment)
                    if number is None or number <= 0:
                        row_errors.append(
                            f"Сырьевые длины, мм: ожидается число > 0, получено «{segment}»"
                        )
                        raw_bad = True
                        break
                    raw_lengths.append(number)
                if not raw_bad:
                    fields["raw_lengths_mm"] = raw_lengths
            else:
                fields["raw_lengths_mm"] = []
        quantities_text = _cell_text(cells.get("quantities"))
        if quantities_text:
            if "+" in quantities_text:
                row_errors.append(
                    "Кол-во на подвесе: композит «45+10» не поддерживается — только симметричные пары")
            else:
                segments = [s.strip() for s in quantities_text.split(",")]
                quantities: list[int | None] = []
                bad = False
                for segment in segments:
                    if not segment:
                        quantities.append(None)
                        continue
                    quantity = _parse_int(segment)
                    if quantity is None:
                        row_errors.append(f"Кол-во на подвесе: ожидается целое число > 0, получено «{segment}»")
                        bad = True
                        break
                    quantities.append(quantity)
                if not bad:
                    fields["quantities"] = quantities

        partners_text = _cell_text(cells.get("pair_partners"))
        if partners_text:
            partner_skus = [item.strip() for item in partners_text.split(";")]
            partner_skus = [item for item in partner_skus if item]
            if any("," in item for item in partner_skus):
                row_errors.append(
                    "Парный профиль: норма пары правится через pairs-API — укажите только «SKU»")
            elif sku in partner_skus:
                row_errors.append("Парный профиль: нельзя указать сам артикул строки")
            elif len(set(partner_skus)) != len(partner_skus):
                row_errors.append("Парный профиль: дубликат партнёра в строке")
            elif partner_skus:
                fields["pair_partners"] = partner_skus

        for key in _BOOL_FIELDS:
            try:
                value = _parse_bool(cells.get(key))
            except ValueError:
                row_errors.append(
                    f"{_BOOL_HEADERS[key]}: ожидается «да»/«нет», получено «{_cell_text(cells.get(key))}»"
                )
                continue
            if value is not None:
                fields[key] = value

        aliases_text = _cell_text(cells.get("aliases"))
        if aliases_text:
            aliases = [part.strip() for part in aliases_text.split(";")]
            fields["aliases"] = [part for part in aliases if part]

        if row_errors:
            for message in row_errors:
                errors.append({"row": row_number, "sku": sku, "message": message})
            continue

        row = ParsedCatalogRow(row=row_number, sku=sku, fields=fields)
        if not fields or fields == {"raw_lengths_mm": []}:
            row.warnings.append("Строка без данных: будет создан пустой артикул")
        parsed.append(row)

    return parsed, errors, total_data_rows


def _header_of(field_name: str) -> str:
    return _FIELD_HEADERS.get(field_name, field_name)


def resolve_raw_lengths(
    row: ParsedCatalogRow, lengths: list[float] | None
) -> list[float | None] | None:
    """Развернуть provided raw-колонку в позиционный список по normal-длинам."""
    if "raw_lengths_mm" not in row.fields:
        return None
    values = row.fields["raw_lengths_mm"]
    if values == [] and lengths:
        return [None] * len(lengths)
    return values

def validate_row_counts(
    row: ParsedCatalogRow,
    existing_lengths: list[float] | None,
    dimension_state: str | None = None,
) -> list[str]:
    """Проверить позиционные списки длин, сырьевых длин и норм.

    Отсутствующая колонка сырьевых длин не участвует в проверке: это
    режим preserve. Присутствующая колонка, включая пустые сегменты,
    должна покрывать ровно список нормальных длин.
    """
    errors: list[str] = []
    lengths = row.fields.get("lengths_mm")
    if lengths is None:
        lengths = existing_lengths or None

    quantities = row.fields.get("quantities")
    if quantities is not None:
        if lengths is None:
            if len(quantities) != 1:
                errors.append(
                    "Кол-во на подвесе: заполните «Длины, мм» — количества привязываются к длинам по индексу"
                )
        elif len(quantities) != len(lengths):
            errors.append(
                f"Кол-во на подвесе: число значений ({len(quantities)}) не совпадает с числом длин ({len(lengths)})"
            )

    raw_lengths = resolve_raw_lengths(row, lengths)
    if raw_lengths is not None:
        has_raw_value = any(value is not None for value in raw_lengths)
        if not lengths and not has_raw_value:
            # Пустая raw-колонка без нормальных длин не задаёт mapping;
            # это допустимо для чернового артикула и не ошибка count.
            pass
        elif dimension_state not in (None, "length"):
            if has_raw_value:
                errors.append("Сырьевые длины, мм: допустимы только для линейных артикулов")
        elif lengths is None:
            errors.append(
                "Сырьевые длины, мм: заполните «Длины, мм» — значения привязываются к длинам по индексу"
            )
        elif len(raw_lengths) != len(lengths):
            errors.append(
                f"Сырьевые длины, мм: число значений ({len(raw_lengths)}) не совпадает с числом длин ({len(lengths)})"
            )
        else:
            for index, (normal, raw) in enumerate(zip(lengths, raw_lengths), start=1):
                if raw is not None and raw < normal:
                    errors.append(
                        f"Сырьевые длины, мм: значение {index} ({_format_number(raw)}) меньше нормальной длины ({_format_number(normal)})"
                    )
    return errors


def build_quantity_dict(lengths: list[float], quantities: list[int | None]) -> dict[str, dict[str, int | None]]:
    return {
        _length_key(length): {"auto": None, "manual": quantity}
        for length, quantity in zip(lengths, quantities)
    }


def format_lengths_cell(lengths: list[float]) -> float | str | None:
    """«Длины, мм» для выгрузки: одиночная длина — числом, несколько — «2500, 2700».

    Формат читается :func:`parse_catalog_excel` без ручной правки файла.
    """
    if not lengths:
        return None
    if len(lengths) == 1:
        return float(lengths[0])
    return ", ".join(_format_number(length) for length in lengths)


def format_quantities_cell(
    lengths: list[float], quantities: dict[str, dict[str, int | None]] | None
) -> int | str | None:
    """«Кол-во на подвесе» для выгрузки: ручная норма позиционно по длинам.

    Норма, которой нет, выгружается пустым сегментом («48, , 48») — парсер
    читает его как None, не подставляя чужое значение. Норм нет ни по одной
    длине — ячейка пуста: иначе re-import материализовал бы пустые записи
    и round-trip перестал бы быть неотличимым от исходного справочника.
    Длин нет вовсе — тоже None: норму без длин (legacy-скаляр, #177 Q2)
    подставляет вызывающий, у которого есть доступ к самому артикулу.
    """
    if not lengths:
        return None
    values = [((quantities or {}).get(_length_key(length)) or {}).get("manual") for length in lengths]
    if all(value is None for value in values):
        return None
    if len(values) == 1:
        return int(values[0])
    return ", ".join("" if value is None else str(int(value)) for value in values)


def format_raw_lengths_cell(
    lengths: list[float], raw_lengths: list[float | None] | None
) -> float | str | None:
    """``Сырьевые длины, мм`` with explicit empty positional segments."""
    if not lengths:
        return None
    values = list(raw_lengths or [None] * len(lengths))
    if len(values) < len(lengths):
        values.extend([None] * (len(lengths) - len(values)))
    if all(value is None for value in values):
        return None
    if len(lengths) == 1:
        value = values[0]
        return None if value is None else float(value)
    return ", ".join("" if value is None else _format_number(value) for value in values)


def _format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def effective_lengths(row: ParsedCatalogRow, existing_lengths: list[float] | None) -> list[float] | None:
    if row.fields.get("lengths_mm") is not None:
        return row.fields["lengths_mm"]
    return existing_lengths or None


def diff_catalog_row(product: Product, row: ParsedCatalogRow) -> dict[str, Any]:
    """Какие поля изменились бы применением строки (для preview/счётчиков)."""
    changes: dict[str, Any] = {}
    fields = row.fields

    # Черновик без длин импорт не активирует (#177, Q3): активация — признак
    # доведённого до рабочего состояния артикула, а строка без длин его не даёт.
    row_lengths = fields.get("lengths_mm")
    if not product.is_active and (row_lengths or product.lengths):
        changes["is_active"] = True

    for key in _TEXT_FIELDS:
        value = fields.get(key)
        if value is not None and value != getattr(product, key):
            changes[key] = value

    for key in _NUMBER_FIELDS:
        value = fields.get(key)
        if value is None:
            continue
        current = getattr(product, key)
        if current is None or float(value) != float(current):
            changes[key] = value

    lengths = row_lengths
    if lengths is not None:
        current_lengths = sorted(length.length_mm for length in product.lengths)
        if sorted(lengths) != current_lengths:
            changes["lengths_mm"] = lengths
    if "raw_lengths_mm" in fields:
        base = lengths if lengths is not None else sorted(length.length_mm for length in product.lengths)
        raw_lengths = resolve_raw_lengths(row, base)
        if base or any(value is not None for value in raw_lengths):
            current_raw = {length.length_mm: length.raw_length_mm for length in product.lengths}
            new_raw = dict(zip(base, raw_lengths, strict=True))
            if new_raw != current_raw:
                changes["raw_lengths_mm"] = raw_lengths

    quantities = fields.get("quantities")
    if quantities is not None:
        base = lengths if lengths is not None else sorted(length.length_mm for length in product.lengths)
        if base:
            new_dict = build_quantity_dict(base, quantities)
            current = product.quantity_per_hanger_by_length or {}
            # Импорт пишет только ручные значения (#127): вычисленное авто
            # сохраняем по совпадающим длинам, чтобы не обнулять его режимом.
            for key, entry in new_dict.items():
                prev = current.get(key)
                if isinstance(prev, dict):
                    entry["auto"] = prev.get("auto")
            if new_dict != current:
                changes["quantity_per_hanger"] = new_dict

    flag_codes = {flag.code for flag in product.processing_flags}
    for key, code in (("skip_shot_blast", "skip_shot_blast"), ("is_laminated", "is_laminated")):
        value = fields.get(key)
        if value is not None and bool(value) != (code in flag_codes):
            changes[key] = value

    aliases = fields.get("aliases")
    if aliases is not None and set(aliases) != set(product.aliases or []):
        changes["aliases"] = aliases

    return changes
