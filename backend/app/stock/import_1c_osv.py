"""Разбор выгрузки 1С — оборотно-сальдовой ведомости (ОСВ).

Спека: ``docs/stock-import-1c-spec.md`` §6–§8, §11. Модуль отвечает за три
вещи, которых нет у ручного шаблона:

* распознавание листа ОСВ по двухстрочной шапке (``Код`` + ``Наименование``
  и группа ``Конечное сальдо`` с подзаголовком ``Количество``);
* сопоставление строки с артикулом: код номенклатуры 1С → артикул в
  наименовании → точное наименование, с приведением к канону группы алиасов;
* нормальную длину и штуки: метры из «Конечного сальдо» делятся на
  нормальную ``length_mm`` артикула.

Ручной шаблон (``Артикул | Кол-во``) этот модуль не разбирает — он живёт в
``import_service``; здесь только автоопределение, что лист — ОСВ.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import TYPE_CHECKING, Literal

from sqlalchemy import func, or_, select

from app.domain.dimensions import (
    LENGTH_MM,
    canonicalize_dimensions,
    format_dimensions,
    format_mm_as_meters,
)
from app.models.product import Product, Product1CCode, ProductLength
from app.models.product_1c_skipped import SKIP_REASON_LABELS, Product1CSkipped
from app.models.section import Section
from app.services.import_normalization import match_sku_cell, normalize_sku, sku_entry
from app.services.product_alias_groups import (
    AliasGroups,
    load_alias_groups,
)
from app.services.route_storage_classifier import STOCK_TYPES
from app.stock.import_service import (
    _EMPTY_CELL_VALUES,
    RemainderItem,
    SheetSummary,
    _attach_remainder_product,
    _rows_to_cell_grid,
    load_remainders_default_mapping,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.import_normalization import SkuEntry

SOURCE_KIND_1C_OSV = "1c_osv"
SOURCE_KIND_MANUAL_TEMPLATE = "manual_template"
SOURCE_KIND_UNKNOWN = "unknown"

SourceKind = Literal["1c_osv", "manual_template", "unknown"]

# Группы остатка в шапке, между которыми выбирается количество.
_FINAL_BALANCE_MARKERS = ("конечное сальдо", "остаток на конец")


def _norm_cell(value: object) -> str:
    """Нормализация ячейки для сравнения заголовков: lowercase, без NBSP."""
    return " ".join(str(value or "").replace("\xa0", " ").lower().split())


def _cell(row: Sequence, index: int | None) -> str:
    """Текст ячейки по индексу (``None``/за границей строки — пусто)."""
    if index is None or index < 0 or index >= len(row):
        return ""
    return str(row[index] if row[index] is not None else "").strip()


# ─── Определение режима ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class OsvLayout:
    """Где в листе лежат шапка и нужные колонки ОСВ (все индексы 0-based)."""

    header_row_index: int
    data_start_index: int
    code_index: int
    name_index: int
    unit_index: int | None
    quantity_index: int


def _find_index(cells: Sequence[str], predicate) -> int | None:
    return next((index for index, cell in enumerate(cells) if predicate(cell)), None)


def detect_1c_osv(rows: Sequence[Sequence]) -> OsvLayout | None:
    """Распознать лист ОСВ по двухстрочной шапке.

    Обязательны: ячейка ``Код``, ``Наименование``/``Наименование ТМЦ`` и
    группа ``Конечное сальдо``/``Остаток на конец``, у которой в следующей
    строке есть подзаголовок ``Количество``. Возвращает ``None``, если лист
    не похож на выгрузку 1С.
    """
    for header_index, row in enumerate(rows):
        if header_index + 1 >= len(rows):
            break
        cells = [_norm_cell(value) for value in row]
        code_index = _find_index(cells, lambda cell: cell == "код")
        if code_index is None:
            continue
        name_index = _find_index(cells, lambda cell: cell.startswith("наименование"))
        if name_index is None:
            continue
        group_index = _find_index(
            cells,
            lambda cell: any(marker in cell for marker in _FINAL_BALANCE_MARKERS),
        )
        if group_index is None:
            continue
        sub_cells = [_norm_cell(value) for value in rows[header_index + 1]]
        quantity_index = next(
            (
                index
                for index, cell in enumerate(sub_cells)
                if index >= group_index and cell.startswith("количество")
            ),
            None,
        )
        if quantity_index is None:
            continue
        unit_index = _find_index(cells, lambda cell: cell.startswith("ед"))
        return OsvLayout(
            header_row_index=header_index,
            data_start_index=header_index + 2,
            code_index=code_index,
            name_index=name_index,
            unit_index=unit_index,
            quantity_index=quantity_index,
        )
    return None


def detect_manual_template(rows: Sequence[Sequence]) -> bool:
    """Похож ли лист на ручной шаблон остатков: артикул + количество.

    Решение принимает тот же резолвер колонок, что и разбор шаблона
    (``remainders_columns.json``): заголовки ``Артикул``/``SKU`` и
    ``Кол-во``/``Количество`` — один источник правды, а не второй список
    псевдонимов.
    """
    from app.services.import_column_resolver import detect_header_row, resolve_columns

    grid = _rows_to_cell_grid(list(rows))
    if not grid:
        return False
    mapping = load_remainders_default_mapping()
    header_index = detect_header_row(grid, mapping)
    if header_index is None:
        return False
    resolved = resolve_columns(mapping, grid[header_index])
    return "sku" in resolved and "quantity" in resolved


# ─── Строки ОСВ ───────────────────────────────────────────────────────────────


def _normalize_1c_code(raw: str) -> str | None:
    """Код номенклатуры 1С из ячейки; ``None`` — не код номенклатуры.

    Коды приходят как ``20933`` и ``20933.0`` (Excel-число) — оба дают
    ``20933``. Групповые счета (``10.1``) и итоги (пусто) кодом номенклатуры
    не являются и строку не дают.
    """
    text = raw.strip().replace("\xa0", "").replace(" ", "")
    if not text:
        return None
    if re.fullmatch(r"\d+", text):
        return text
    fractional_zero = re.fullmatch(r"(\d+)[.,]0+", text)
    return fractional_zero.group(1) if fractional_zero else None


def _classify_unit(raw: str) -> Literal["m", "pcs", "other"]:
    """Единица измерения по спеке §6.3: метры, штуки, всё прочее."""
    normalized = "".join(
        char for char in raw.lower().replace("\xa0", "") if not char.isspace() and char != "."
    )
    if normalized in {"м", "мп", "пм"}:
        return "m"
    if normalized == "шт":
        return "pcs"
    return "other"


def _parse_osv_quantity(raw: str) -> Decimal | None:
    """Количество из «Конечного сальдо»; ``None`` — не число."""
    text = raw.replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_1c_osv_rows(
    rows: Sequence[Sequence],
    row_selection: str | None = None,
) -> tuple[list[RemainderItem], SheetSummary]:
    """Разобрать строки листа ОСВ в ``RemainderItem`` без обращения к БД."""
    from app.services.excel_import import parse_row_selection

    layout = detect_1c_osv(rows)
    if layout is None:
        raise ValueError("Лист не похож на выгрузку 1С (ОСВ)")

    grid = _rows_to_cell_grid(list(rows))
    if not grid:
        raise ValueError("Нет данных для импорта")

    selected_rows = parse_row_selection(row_selection) if row_selection else None

    items: list[RemainderItem] = []
    valid_count = 0
    invalid_count = 0
    quantity_total = Decimal(0)

    for offset, row in enumerate(
        grid[layout.data_start_index :], start=layout.data_start_index + 1
    ):
        if selected_rows is not None and offset not in selected_rows:
            continue
        code = _normalize_1c_code(_cell(row, layout.code_index))
        if code is None:
            # Итоги, групповые счета и пустые строки — не позиции номенклатуры.
            continue
        name = _cell(row, layout.name_index)
        if not name:
            # Групповой счёт/итог с числовым кодом (``10``) и без названия —
            # не строка номенклатуры, в предпросмотр не попадает.
            continue
        quantity_raw = _cell(row, layout.quantity_index)
        if not quantity_raw or quantity_raw in _EMPTY_CELL_VALUES:
            # Пустое количество — не остаток, но и не ошибка строки.
            continue

        unit_raw = _cell(row, layout.unit_index)
        unit_kind = _classify_unit(unit_raw)

        errors: list[str] = []
        quantity = _parse_osv_quantity(quantity_raw)
        if quantity is None:
            errors.append("Количество не является числом")
        elif quantity < 0:
            errors.append("Отрицательный остаток")

        item = RemainderItem(
            source_row_number=offset,
            # Артикул появится после матча; до него sku пуст.
            sku="",
            quantity=(
                float(quantity)
                if quantity is not None and quantity >= 0 and unit_kind == "pcs"
                else None
            ),
            comment=None,
            product_id=None,
            product_name=None,
            status="invalid" if errors else "valid",
            errors=errors,
            raw_values=list(row),
            source_code=code,
            source_name=name or None,
            source_unit=unit_raw or None,
            source_quantity_m=(
                float(quantity)
                if quantity is not None and quantity >= 0 and unit_kind == "m"
                else None
            ),
        )

        if errors:
            invalid_count += 1
        else:
            valid_count += 1
            if quantity is not None and unit_kind == "pcs":
                quantity_total += quantity
        items.append(item)

    summary = SheetSummary(
        total=len(items),
        valid=valid_count,
        invalid=invalid_count,
        quantity_total=float(round(quantity_total, 3)),
    )
    return items, summary


async def parse_remainders_1c_osv(
    content: bytes,
    sheet_index: int = 0,
    row_selection: str | None = None,
) -> tuple[str, int, list[RemainderItem], SheetSummary]:
    """Разобрать лист ОСВ из файла: ``(имя листа, строк, элементы, сводка)``."""
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
    items, summary = parse_1c_osv_rows(rows, row_selection)
    return sheet.name, len(rows), items, summary


# ─── Длина из наименования ────────────────────────────────────────────────────

_METER_SUFFIX_RE = re.compile(
    r"(?<![\d.,*x×])(\d+(?:[.,]\d+)?)\s*(м\.?п\.?|п\.?м\.?|мм|м|m)(?![а-яёa-z0-9²³])",
    re.IGNORECASE,
)
# Миллиметры — размер сечения/толщина, а не длина заготовки.
_MILLIMETRE_SIZE_RE = re.compile(
    r"(?<![\d.,*x×])\d+(?:[.,]\d+)?\s*(?:мм|mm)(?![а-яёa-z0-9²³])",
    re.IGNORECASE,
)
_EXPLICIT_LENGTH_RE = re.compile(r"l\s*=\s*(\d+(?:[.,]\d+)?)", re.IGNORECASE)
# Одиночное число с дробной частью без единицы: «10*10 3,0 алюминий».
# Число не должно примыкать к буквам, цифрам, дефису или слэшу: иначе дробь
# внутри кода изделия («РП-АКП-09,10», «03,04-15») читается как длина.
_BARE_METERS_RE = re.compile(r"(?<![\w.,*x×/-])(\d+[.,]\d+)(?![\w.,*x×/-])")


def _meters_to_mm(raw: str) -> int | None:
    try:
        meters = Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None
    if meters <= 0:
        return None
    return round(meters * 1000)


def _explicit_length_to_mm(raw: str) -> int | None:
    """Длина из ``L=…``: значение от 100 — уже миллиметры (``L=3000``)."""
    try:
        value = Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None
    if value >= 100:
        return int(value) if value == int(value) else None
    return _meters_to_mm(raw)


def parse_length_from_name(name: str | None) -> int | None:
    """Длина из наименования в миллиметрах; ``None`` — длины нет.

    Поддержаны ``2,70м``, ``2,7 м``, ``2.7m``, ``3м``, ``L=3,61 м`` и
    одиночное ``2,7``/``3,0`` без единицы. Миллиметры (``0,18мм``) и размеры
    сечений (``10*10``, ``60*32,4``, ``20*20*1,5``) длиной не считаются.
    """
    if not name:
        return None
    explicit = _EXPLICIT_LENGTH_RE.search(name)
    if explicit is not None:
        length = _explicit_length_to_mm(explicit.group(1))
        if length is not None:
            return length

    # Миллиметры — размер, а не длина заготовки: вырезаем их вместе с числом,
    # чтобы «Круглая труба 16 мм 2,75» искала 2,75, а «Кабель 0,18мм» — ничего.
    without_mm = _MILLIMETRE_SIZE_RE.sub(" ", name)
    for match in _METER_SUFFIX_RE.finditer(without_mm):
        length = _meters_to_mm(match.group(1))
        if length is not None:
            return length

    bare = _BARE_METERS_RE.search(without_mm)
    if bare is not None:
        return _meters_to_mm(bare.group(1))
    return None


# ─── Нормальная длина ─────────────────────────────────────────────────────────


def _format_mm_as_meters(length_mm: float) -> str:
    """Миллиметры в метры для сообщений: 2500 → «2,5», 3000 → «3,0».

    Форматирование числа — общее с габаритами (``app.domain.dimensions``);
    здесь только «хотя бы один знак после запятой», чтобы сообщение не читалось
    как целое число метров.
    """
    text = format_mm_as_meters(length_mm)
    return text if "," in text else f"{text},0"


@dataclass(frozen=True)
class NormalLength:
    """Результат приведения длины к нормальной ``length_mm`` артикула."""

    length_mm: int | None
    warning: str | None = None
    error: str | None = None


def resolve_normal_length(
    written_mm: int | None,
    lengths: Sequence[ProductLength],
) -> NormalLength:
    """Привести длину из наименования к нормальной ``length_mm`` (спека §8.2).

    Точное ``length_mm`` → она; точное ``raw_length_mm`` → соответствующая
    нормальная; иначе — наибольшая ``length_mm`` не больше написанной.
    Расхождение больше 100 мм (кроме точного raw) — предупреждение.
    """
    normal = sorted({round(length.length_mm) for length in lengths if length.length_mm})
    if written_mm is None:
        if len(normal) == 1:
            return NormalLength(normal[0])
        if not normal:
            return NormalLength(None, error="У артикула не указана длина")
        primary = [
            round(length.length_mm)
            for length in lengths
            if length.is_primary and length.length_mm
        ]
        if primary:
            return NormalLength(min(primary))
        return NormalLength(
            None,
            error="В наименовании не указана длина, у артикула несколько длин",
        )

    if written_mm in normal:
        return NormalLength(written_mm)
    if not normal:
        # У артикула нет ни одной ``length_mm``: приводить не к чему, и
        # сравнивать написанную длину не с чем (иначе ``normal[0]`` падал бы).
        return NormalLength(None, error="У артикула не указана длина")
    for length in lengths:
        if length.raw_length_mm is None or not length.length_mm:
            continue
        if round(length.raw_length_mm) == written_mm:
            return NormalLength(round(length.length_mm))

    candidates = [value for value in normal if value <= written_mm]
    if not candidates:
        return NormalLength(
            None,
            error=(
                f"Длина {_format_mm_as_meters(written_mm)} меньше минимальной "
                f"длины артикула ({_format_mm_as_meters(normal[0])})"
            ),
        )
    chosen = max(candidates)
    if written_mm - chosen > 100:
        return NormalLength(
            chosen,
            warning=(
                f"Длина {_format_mm_as_meters(written_mm)} приведена к "
                f"{_format_mm_as_meters(chosen)}"
            ),
        )
    return NormalLength(chosen)


def build_length_dimensions(length_mm: int) -> dict | None:
    """Габариты строки ОСВ: ``{"length_mm": …}`` в канонической форме."""
    return canonicalize_dimensions({LENGTH_MM: length_mm})


def describe_length(length_mm: int | None) -> str:
    """Подпись габарита для предпросмотра («2,7 м» / «—»)."""
    return format_dimensions(build_length_dimensions(length_mm) if length_mm else None)


@dataclass
class ParsedRemainders:
    """Результат разбора листа: элементы, сводка и источник строк.

    ``header_rows`` — первые строки листа (до шапки), по ним определяется
    склад → участок; для ручного шаблона список пуст.
    """

    sheet_name: str
    total_rows: int
    items: list[RemainderItem]
    summary: SheetSummary
    source_kind: SourceKind
    header_rows: list[list] = field(default_factory=list)
    detected_section_id: int | None = None
    detected_section_name: str | None = None


async def parse_remainders_sheet(
    content: bytes,
    sheet_index: int = 0,
    row_selection: str | None = None,
    column_mapping: dict | None = None,
) -> ParsedRemainders:
    """Разобрать лист, сам выбрав режим: ОСВ 1С или ручной шаблон."""
    from python_calamine import load_workbook

    from app.stock.import_service import _parse_remainders_grid

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

    if detect_1c_osv(rows) is not None:
        items, summary = parse_1c_osv_rows(rows, row_selection)
        source_kind: SourceKind = SOURCE_KIND_1C_OSV
        header_rows = rows[:_SECTION_SCAN_ROWS]
    else:
        items, summary = _parse_remainders_grid(
            rows, row_selection, column_mapping=column_mapping
        )
        source_kind = (
            SOURCE_KIND_MANUAL_TEMPLATE
            if detect_manual_template(rows)
            else SOURCE_KIND_UNKNOWN
        )
        header_rows = []
    return ParsedRemainders(
        sheet_name=sheet.name,
        total_rows=len(rows),
        items=items,
        summary=summary,
        source_kind=source_kind,
        header_rows=header_rows,
    )


@dataclass(frozen=True)
class RemainderSheetInfo:
    """Метадата листа файла остатков для вкладок диалога импорта."""

    index: int
    name: str
    kind: SourceKind
    detected_section_id: int | None = None
    detected_section_name: str | None = None


async def describe_remainder_sheets(
    db: AsyncSession,
    content: bytes,
) -> list[RemainderSheetInfo]:
    """Тип каждого листа файла и участок ОСВ-листов без разбора строк."""
    from python_calamine import load_workbook

    workbook = load_workbook(BytesIO(content))
    sections = await _load_stock_sections(db)
    sheets: list[RemainderSheetInfo] = []
    for index, name in enumerate(workbook.sheet_names):
        rows = list(workbook.get_sheet_by_index(index).iter_rows())
        if detect_1c_osv(rows) is not None:
            section_id, section_name = _pick_storage_section(sections, rows)
            sheets.append(
                RemainderSheetInfo(
                    index=index,
                    name=name,
                    kind=SOURCE_KIND_1C_OSV,
                    detected_section_id=section_id,
                    detected_section_name=section_name,
                )
            )
        elif detect_manual_template(rows):
            sheets.append(
                RemainderSheetInfo(
                    index=index, name=name, kind=SOURCE_KIND_MANUAL_TEMPLATE
                )
            )
        else:
            sheets.append(
                RemainderSheetInfo(index=index, name=name, kind=SOURCE_KIND_UNKNOWN)
            )
    return sheets


# ─── Склад → участок ──────────────────────────────────────────────────────────

# Синонимы склада в шапке листа (спека §6.2) → код складского участка.
_SECTION_SYNONYMS: tuple[tuple[str, str], ...] = (
    ("завод ктм склад сырой", "RAW_STOCK"),
    ("склад сыр", "RAW_STOCK"),
    ("подготовительный участок", "PREP_STOCK"),
    ("склад подготовки", "PREP_STOCK"),
    ("склад полуфабриката", "WIP_STOCK"),
    ("склад готовой продукции", "FINISHED_STOCK"),
    ("склад гп", "FINISHED_STOCK"),
)

# Строки шапки, в которых ищется склад (спека §6.2: первые 25 строк).
_SECTION_SCAN_ROWS = 25


async def _load_stock_sections(db: AsyncSession) -> list[Section]:
    """Активные складские участки: raw/wip/finished (без брака и терминала)."""
    rows = await db.execute(
        select(Section)
        .where(Section.is_active.is_(True), Section.type.in_(sorted(STOCK_TYPES)))
        .order_by(Section.id)
    )
    return list(rows.scalars().all())


def _pick_storage_section(
    sections: Sequence[Section],
    rows: Sequence[Sequence],
) -> tuple[int | None, str | None]:
    """Участок по имени склада в шапке; два разных кандидата — авто нет."""
    if not sections:
        return (None, None)
    by_code = {section.code: section for section in sections}
    by_name = {_norm_cell(section.name): section for section in sections}

    candidates: dict[int, Section] = {}
    for row in rows[:_SECTION_SCAN_ROWS]:
        for value in row:
            cell = _norm_cell(value)
            if not cell:
                continue
            exact = by_name.get(cell)
            if exact is not None:
                candidates[exact.id] = exact
            for marker, code in _SECTION_SYNONYMS:
                if marker in cell and (section := by_code.get(code)) is not None:
                    candidates[section.id] = section

    if len(candidates) != 1:
        return (None, None)
    section = next(iter(candidates.values()))
    return (section.id, section.name)


async def resolve_1c_storage_section(
    db: AsyncSession,
    rows: Sequence[Sequence],
) -> tuple[int | None, str | None]:
    """Автоучасток листа ОСВ по названию склада в шапке (спека §6.2)."""
    return _pick_storage_section(await _load_stock_sections(db), rows)


# ─── Матч к артикулу ──────────────────────────────────────────────────────────

# Группы в скобках: «(ЮП-2616)», «(ALS-1103, ЮП-3773)», «(033-00 / ЮП-2630)».
_PARENS_RE = re.compile(r"\(([^()]*)\)")
# Токены вида ЮП-2616 / ALS-917 / АТ-7121 / КП5096.
_SKU_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё]{2,5}[-–]?\d{3,6}")
# «#033-00» → код «033» (последний сегмент — вариант поставки).
_HASH_CODE_RE = re.compile(r"#\s*(\d+)(?:-\d+)?")
# Разделители внутри скобок: «(ALS-1103, ЮП-3773)», «(033 / ЮП-2630)».
_CANDIDATE_SPLIT_RE = re.compile(r"[,/]")


def _extract_paren_candidates(name: str | None) -> list[str]:
    """Артикулы в скобках: «(ЮП-2616)», «(ALS-1103, ЮП-3773)», «(033-00 / ЮП-2630)».

    Скобки в наименованиях 1С несут авторский артикул — «Профиль алюм.
    #318-00(ЮП-3123)» означает именно ЮП-3123, а «#318-00» — код поставщика.
    """
    if not name:
        return []
    candidates: list[str] = []
    for group in _PARENS_RE.findall(name):
        for chunk in _CANDIDATE_SPLIT_RE.split(group):
            candidate = chunk.strip()
            if candidate:
                candidates.append(candidate)
    return candidates


def _extract_sku_candidates(name: str | None) -> list[str]:
    """Кандидаты-артикулы из наименования 1С (порядок: скобки, токены, ``#N``)."""
    if not name:
        return []
    candidates: list[str] = []

    for group in _PARENS_RE.findall(name):
        for chunk in _CANDIDATE_SPLIT_RE.split(group):
            candidate = chunk.strip()
            if candidate:
                candidates.append(candidate)
    candidates.extend(match.group(0) for match in _SKU_TOKEN_RE.finditer(name))
    candidates.extend(match.group(1) for match in _HASH_CODE_RE.finditer(name))

    unique: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in unique:
            unique.append(candidate)
    return unique


@dataclass(frozen=True)
class _Catalog:
    """Плоский справочник артикулов для каскада ``match_sku_cell``."""

    entries: list[SkuEntry]
    product_ids: list[int]
    sku_by_id: dict[int, str]
    groups: AliasGroups
    #: База «артикул + короткое числовое исполнение» → id артикулов:
    #: ``ЮП-2464-1`` даёт ``{"юп-2464": [71]}``. 1С пишет полуфабрикат
    #: ``ЮП-2464-01 ПФ``, токен наименования обрезается до ``ЮП-2464`` —
    #: без этого индекса строка не находит артикул (см. ``variant_products``).
    variant_ids: dict[str, list[int]] = field(default_factory=dict)

    def variant_products(self, candidate: str) -> list[int]:
        """Артикулы, у которых ``candidate`` — база исполнения (``ЮП-2464``)."""
        return self.variant_ids.get(normalize_sku(candidate), [])

    def canonical_id(self, product_id: int) -> int:
        """Представитель группы алиасов (минимальный ``product_id``)."""
        group = self.groups.group_for(product_id)
        if group is None:
            return product_id
        return group.product_ids[0]

    def group_key(self, product_id: int) -> int:
        return self.groups.group_key(product_id) or product_id

    def sku(self, product_id: int) -> str:
        return self.sku_by_id.get(product_id, str(product_id))


_VARIANT_SUFFIX_RE = re.compile(r"^(?P<base>.+)-(?P<variant>\d{1,2})$")


def _variant_base_key(sku: str) -> str | None:
    """База артикула с коротким числовым исполнением: ``ЮП-2464-1`` → ``юп-2464``.

    Исполнение — последний сегмент из одной-двух цифр (``-1``, ``-05``).
    Четырёхзначный номер (``АТ-7121``) — это сам артикул, а не исполнение:
    иначе база ``ат`` склеила бы разные артикулы. Если на одну базу приходится
    два артикула (``МС16-20`` и ``МС16-25``), индекс отдаст оба — вызывающий
    обязан считать это неоднозначностью, а не выбирать первый.
    """
    match = _VARIANT_SUFFIX_RE.match(normalize_sku(sku))
    if match is None:
        return None
    return match.group("base")


async def _load_catalog(db: AsyncSession) -> _Catalog:
    groups = await load_alias_groups(db)
    # Алиас — это ещё одно написание артикула, поэтому он участвует в разборе
    # наименования так же, как SKU. Но только если такого SKU нет отдельной
    # записью: тогда он уже представлен собой, и его группа решает каскад.
    alias_rows = (await db.execute(select(Product.id, Product.aliases))).all()
    aliases_by_id: dict[int, set[str]] = {
        int(product_id): {
            normalize_sku(str(alias)) for alias in (aliases or ()) if alias
        }
        for product_id, aliases in alias_rows
    }
    sku_keys = {
        normalize_sku(sku) for group in groups.groups for sku in group.skus
    }
    entries: list[SkuEntry] = []
    product_ids: list[int] = []
    sku_by_id: dict[int, str] = {}
    for group in groups.groups:
        for product_id, sku in zip(group.product_ids, group.skus, strict=True):
            extra = aliases_by_id.get(product_id, set()) - sku_keys
            entries.append(sku_entry(sku, extra))
            product_ids.append(product_id)
            sku_by_id[product_id] = sku
    variant_ids: dict[str, list[int]] = {}
    for product_id, sku in sku_by_id.items():
        base = _variant_base_key(sku)
        if base is not None:
            variant_ids.setdefault(base, []).append(product_id)
    return _Catalog(
        entries=entries,
        product_ids=product_ids,
        sku_by_id=sku_by_id,
        groups=groups,
        variant_ids=variant_ids,
    )


@dataclass
class _MatchDecision:
    """Решение по строке до загрузки объекта артикула.

    ``unmatched`` — каталог не нашёл ничего (ни кода, ни артикула в
    наименовании, ни точного имени). Только такая строка может получить
    статус ``skipped`` из реестра исключений: неоднозначность и конфликт кода
    с наименованием остаются ошибками — это дефект данных, а не решение
    «строка не наша».
    """

    product_id: int | None = None
    warning: str | None = None
    errors: list[str] | None = None
    unmatched: bool = False


@dataclass
class _NameMatch:
    """Что нашлось в наименовании: группы, id кандидатов, отвергнутые id."""

    group_keys: set[int]
    product_ids: list[int]
    ambiguous_ids: list[int]

    @property
    def ambiguous(self) -> bool:
        return bool(self.ambiguous_ids)

    @property
    def found(self) -> bool:
        return bool(self.group_keys)


def _match_name_candidates(name: str | None, catalog: _Catalog) -> _NameMatch:
    """Сопоставить кандидатов из наименования через ``match_sku_cell``.

    Скобки разбираются первыми и, если дали артикул, код поставщика вне скобок
    не участвует: в «Профиль алюм.#318-00(ЮП-3123)» номер ``318`` из кода
    совпадает с отдельным артикулом ``318``, и без приоритета скобок строка
    становится ложно неоднозначной.
    """
    group_keys: set[int] = set()
    matched_ids: list[int] = []
    ambiguous_ids: list[int] = []

    def collect(candidates: list[str]) -> None:
        for candidate in candidates:
            match = match_sku_cell(candidate, catalog.entries)
            if match.rejected:
                ambiguous_ids.extend(
                    catalog.product_ids[index] for index in match.ambiguous_indexes
                )
                continue
            if match.found and match.index is not None:
                product_id = catalog.product_ids[match.index]
                group_keys.add(catalog.group_key(product_id))
                matched_ids.append(product_id)
                continue
            # Исполнение полуфабриката: токен ``ЮП-2464`` — база артикула
            # ``ЮП-2464-1``, 1С пишет ``ЮП-2464-01 ПФ``. Берём только
            # единственного кандидата: два артикула на одну базу —
            # неоднозначность, а не выбор первого по порядку справочника.
            variants = catalog.variant_products(candidate)
            if len(variants) == 1:
                product_id = variants[0]
                group_keys.add(catalog.group_key(product_id))
                matched_ids.append(product_id)
            elif len(variants) > 1:
                ambiguous_ids.extend(variants)

    paren_candidates = _extract_paren_candidates(name)
    collect(paren_candidates)
    if not group_keys and not ambiguous_ids:
        collect([
            candidate
            for candidate in _extract_sku_candidates(name)
            if candidate not in paren_candidates
        ])
    return _NameMatch(
        group_keys=group_keys,
        product_ids=matched_ids,
        ambiguous_ids=ambiguous_ids,
    )


def _ambiguous_message(catalog: _Catalog, product_ids: list[int]) -> str:
    skus = sorted({catalog.sku(product_id) for product_id in product_ids})
    return f"Артикул неоднозначен: {', '.join(skus)}"


def _ambiguous_decision(catalog: _Catalog, name: _NameMatch) -> _MatchDecision:
    ids = name.ambiguous_ids or name.product_ids
    return _MatchDecision(errors=[_ambiguous_message(catalog, ids)])


def _decide_code_match(
    item: RemainderItem,
    *,
    code_product_id: int,
    name: _NameMatch,
    catalog: _Catalog,
) -> _MatchDecision:
    """Код приоритетен: расхождение с наименованием — ошибка, не перепривязка."""
    if name.ambiguous:
        return _ambiguous_decision(catalog, name)
    code_group = catalog.group_key(code_product_id)
    if name.found and name.group_keys != {code_group}:
        # Все кандидаты группы, а не первый: иначе сообщение прячет, что
        # наименование указывает на несколько карточек одной группы.
        name_skus = sorted({catalog.sku(product_id) for product_id in name.product_ids})
        return _MatchDecision(
            errors=[
                f"Код {item.source_code} привязан к {catalog.sku(code_product_id)}, "
                f"в наименовании {', '.join(name_skus)}"
            ]
        )
    return _MatchDecision(product_id=catalog.canonical_id(code_product_id))


def _decide_name_match(
    item: RemainderItem,
    *,
    name: _NameMatch,
    catalog: _Catalog,
) -> _MatchDecision | None:
    """Матч без кода: одна группа из наименования или ``None`` (нужно имя)."""
    if name.ambiguous:
        return _ambiguous_decision(catalog, name)
    if len(name.group_keys) > 1:
        return _ambiguous_decision(catalog, name)
    if name.found:
        return _MatchDecision(product_id=catalog.canonical_id(name.product_ids[0]))
    return None


def _normalized_name_sql():
    """``Product.name`` в том же виде, что :func:`_norm_cell`.

    Сравнивать нормализованное в Python имя с сырым ``Product.name`` нельзя:
    NBSP и двойные пробелы в БД дают «не найдено» на ровном месте. Поэтому та
    же нормализация (lower, NBSP → пробел, схлопывание пробелов, trim)
    выполняется в SQL — одна форма с обеих сторон.
    """
    return func.trim(
        func.regexp_replace(
            func.lower(func.replace(Product.name, "\xa0", " ")),
            r"\s+",
            " ",
            "g",
        )
    )


async def _load_exact_name_products(
    db: AsyncSession,
    items: Sequence[RemainderItem],
) -> dict[str, list[Product]]:
    """Артикулы с точным (нормализованным) наименованием, сгруппированные по нему."""
    names = list({_norm_cell(item.source_name) for item in items if item.source_name})
    if not names:
        return {}
    rows = (
        await db.execute(select(Product).where(_normalized_name_sql().in_(names)))
    ).scalars()
    by_name: dict[str, list[Product]] = {}
    for product in rows:
        by_name.setdefault(_norm_cell(product.name), []).append(product)
    return by_name


@dataclass(frozen=True)
class _SkippedRegistry:
    """Прочитанный реестр исключений: код первичен, имя — запасной ключ.

    Строка ищется сначала по коду номенклатуры 1С, потом по нормализованному
    наименованию: код — стабильный ключ, имя — способ поймать позицию, у
    которой в 1С поменялся код.
    """

    by_code: dict[str, Product1CSkipped]
    by_name: dict[str, Product1CSkipped]

    def match(self, item: RemainderItem) -> Product1CSkipped | None:
        if item.source_code:
            entry = self.by_code.get(item.source_code)
            if entry is not None:
                return entry
        name_norm = _norm_cell(item.source_name)
        if not name_norm:
            return None
        return self.by_name.get(name_norm)


async def _load_skipped(
    db: AsyncSession,
    items: Sequence[RemainderItem],
) -> _SkippedRegistry:
    """Реестр исключений (#464) только по ключам строк, которые не нашлись.

    Читаются лишь записи, способные совпасть: полная выгрузка реестра на
    каждом предпросмотре росла бы вместе с ним, а строки файла дают точный
    набор кодов и имён.
    """
    codes = {item.source_code for item in items if item.source_code}
    names = {_norm_cell(item.source_name) for item in items if item.source_name}
    conditions = []
    if codes:
        conditions.append(Product1CSkipped.code.in_(codes))
    if names:
        conditions.append(Product1CSkipped.name_norm.in_(names))
    if not conditions:
        return _SkippedRegistry(by_code={}, by_name={})

    rows = (
        await db.scalars(select(Product1CSkipped).where(or_(*conditions)))
    ).all()
    by_code: dict[str, Product1CSkipped] = {}
    by_name: dict[str, Product1CSkipped] = {}
    for row in rows:
        if row.code:
            by_code[row.code] = row
        if row.name_norm:
            by_name[row.name_norm] = row
    return _SkippedRegistry(by_code=by_code, by_name=by_name)


async def _lookup_1c_products(
    db: AsyncSession,
    items: Sequence[RemainderItem],
) -> None:
    """Привязать строки ОСВ к артикулам (спека §7), in-place.

    Порядок: код номенклатуры 1С → артикул в наименовании → точное
    наименование ``Product.name``. Любой матч приводится к канону группы
    алиасов; кандидаты из разных групп и конфликт кода с наименованием —
    ошибка строки. Артикулы не создаются.

    Каталог главнее реестра исключений (#464): найденная строка остаётся
    ``valid``, даже если её код или имя записаны в ``product_1c_skipped``.
    Реестр применяется последним и только к строкам, которые каталог не
    нашёл вовсе (``_MatchDecision.unmatched``); тогда строка получает статус
    ``skipped`` с причиной и перестаёт быть ошибкой. Неоднозначность и
    конфликт кода с наименованием реестр не глушит — это дефект данных.
    """
    rows_items = [item for item in items if item.source_code]
    if not rows_items:
        return

    catalog = await _load_catalog(db)
    codes = list({item.source_code for item in rows_items if item.source_code})
    code_rows = (
        await db.execute(
            select(Product1CCode.code, Product1CCode.product_id).where(
                Product1CCode.code.in_(codes)
            )
        )
    ).all()
    code_products = {str(code): int(product_id) for code, product_id in code_rows}

    decisions: dict[int, _MatchDecision] = {}
    pending: list[RemainderItem] = []
    for item in rows_items:
        name = _match_name_candidates(item.source_name, catalog)
        code_product_id = code_products.get(item.source_code or "")
        if code_product_id is not None:
            decisions[id(item)] = _decide_code_match(
                item,
                code_product_id=code_product_id,
                name=name,
                catalog=catalog,
            )
            continue
        decision = _decide_name_match(item, name=name, catalog=catalog)
        if decision is not None:
            decisions[id(item)] = decision
        else:
            pending.append(item)

    # Третий шаг — точное наименование; только для строк без артикула в тексте.
    if pending:
        by_name = await _load_exact_name_products(db, pending)
        for item in pending:
            matches = by_name.get(_norm_cell(item.source_name), [])
            if not matches:
                decisions[id(item)] = _MatchDecision(
                    errors=[
                        f"Код {item.source_code} не привязан к артикулу, "
                        "в наименовании артикул не найден"
                    ],
                    unmatched=True,
                )
                continue
            group_keys = {catalog.group_key(product.id) for product in matches}
            if len(group_keys) > 1:
                decisions[id(item)] = _MatchDecision(
                    errors=[
                        _ambiguous_message(catalog, [product.id for product in matches])
                    ]
                )
                continue
            canonical = min(
                (product for product in matches),
                key=lambda product: catalog.canonical_id(product.id),
            )
            canonical_id = catalog.canonical_id(canonical.id)
            decisions[id(item)] = _MatchDecision(
                product_id=canonical_id,
                warning="Сопоставлено по наименованию",
            )

    product_ids = {
        decision.product_id
        for decision in decisions.values()
        if decision.product_id is not None
    }
    by_id: dict[int, Product] = {}
    if product_ids:
        loaded = await db.execute(select(Product).where(Product.id.in_(product_ids)))
        by_id = {product.id: product for product in loaded.scalars()}

    # Реестр исключений (#464) читается только под строки, которые каталог не
    # нашёл и которые не имеют собственных ошибок разбора: запись реестра —
    # решение «строка не наша», а не способ скрыть отрицательный остаток.
    unmatched_items = [
        item
        for item in rows_items
        if (decision := decisions.get(id(item))) is not None
        and decision.unmatched
        and not item.errors
    ]
    skipped = (
        await _load_skipped(db, unmatched_items)
        if unmatched_items
        else _SkippedRegistry(by_code={}, by_name={})
    )

    for item in rows_items:
        decision = decisions.get(id(item))
        if decision is None:
            continue
        if decision.errors:
            entry = skipped.match(item) if decision.unmatched and not item.errors else None
            if entry is not None:
                # Разобранная строка: не ошибка и не импорт. Причина остаётся в
                # строке — в предпросмотре её видно рядом с прочерком в ошибках.
                item.status = "skipped"
                item.skip_reason = entry.reason
                item.skip_reason_label = SKIP_REASON_LABELS.get(
                    entry.reason, entry.reason
                )
                item.skip_note = entry.note
                continue
            item.errors.extend(decision.errors)
            item.status = "invalid"
            continue
        product = by_id.get(decision.product_id) if decision.product_id else None
        if product is None:
            continue
        _attach_remainder_product(item, product, warning=decision.warning)
        # Для ОСВ колонка «Артикул» предпросмотра — найденный артикул:
        # кода артикула в выгрузке нет, `sku` до матча пуст.
        item.sku = product.sku or ""


# ─── Метры → штуки ────────────────────────────────────────────────────────────


async def _load_lengths_by_product(
    db: AsyncSession,
    product_ids: Sequence[int],
) -> dict[int, list[ProductLength]]:
    if not product_ids:
        return {}
    rows = (
        await db.execute(
            select(ProductLength)
            .where(ProductLength.product_id.in_(list(product_ids)))
            .order_by(ProductLength.id)
        )
    ).scalars()
    by_product: dict[int, list[ProductLength]] = {}
    for length in rows:
        by_product.setdefault(length.product_id, []).append(length)
    return by_product


def _unit_error(unit_raw: str | None) -> str:
    if not unit_raw or not unit_raw.strip():
        return "Не указана единица измерения"
    return f"Единица измерения '{unit_raw.strip()}' не поддерживается"


async def resolve_1c_osv_quantities(
    db: AsyncSession,
    items: Sequence[RemainderItem],
) -> None:
    """Длина, штуки и единицы строк ОСВ (спека §6.3, §8), in-place.

    Требует уже выполненного ``_lookup_1c_products``: длина приводится к
    ``length_mm`` найденного артикула, штуки — ``floor(метры / длина)``.
    """
    lengths_by_product = await _load_lengths_by_product(
        db, [item.product_id for item in items if item.product_id is not None]
    )

    for item in items:
        if item.product_id is None:
            # Артикул не найден — его ошибка уже стоит, единицы не добавляем.
            continue
        unit_kind = _classify_unit(item.source_unit or "")
        if unit_kind == "other":
            # Плёнки, м², кг и прочие единицы MES не ведёт: это не дефект
            # данных, а строка «не наша». Ошибка заставила бы разбирать её
            # руками каждый прогон; пропуск с причиной — честное решение
            # заказчика (26.11.2026), а не тихое проглатывание.
            item.status = "skipped"
            item.skip_reason = "not_mes"
            item.skip_reason_label = SKIP_REASON_LABELS.get("not_mes", "not_mes")
            item.skip_note = _unit_error(item.source_unit)
            continue
        if unit_kind == "pcs":
            # Штуки как есть: количества уже в item.quantity, длина не нужна.
            continue

        meters = item.source_quantity_m
        if meters is None:
            continue

        written_mm = parse_length_from_name(item.source_name)
        resolved = resolve_normal_length(
            written_mm, lengths_by_product.get(item.product_id, [])
        )
        if resolved.warning:
            item.warnings.append(resolved.warning)
        if resolved.error or resolved.length_mm is None:
            item.errors.append(resolved.error or "Не удалось определить длину артикула")
            item.status = "invalid"
            continue

        length_mm = resolved.length_mm
        pieces = int(Decimal(str(meters)) / (Decimal(length_mm) / Decimal(1000)))
        if pieces <= 0:
            item.errors.append("Остаток меньше одной штуки")
            item.status = "invalid"
            continue

        item.quantity = float(pieces)
        item.dimensions = build_length_dimensions(length_mm)
        item.dimensions_label = describe_length(length_mm)
