"""Разбор выгрузки 1С (ОСВ) в предпросмотре остатков (#458).

Спека: ``docs/stock-import-1c-spec.md`` §5.1–§8, §11, §13.

Проверяют:
- распознавание листа ОСВ по двухстрочной шапке и ручного шаблона;
- пропуск итогов/групповых счетов и строк с пустым количеством;
- матч «код 1С → артикул → группа алиасов», артикул в наименовании, конфликт;
- длину из наименования и приведение к нормальной ``length_mm``;
- метры → штуки, единицы м/шт/прочие;
- автоучасток по шапке листа;
- метадату листов и дополнения ответа предпросмотра.
"""
from __future__ import annotations

from io import BytesIO

import pytest
from app.models import (
    Product,
    Product1CCode,
    ProductLength,
    ProductType,
    Section,
)
from app.stock.import_1c_osv import (
    detect_1c_osv,
    detect_manual_template,
    parse_length_from_name,
    parse_remainders_1c_osv,
    resolve_normal_length,
)
from app.stock.import_service import parse_remainders_excel
from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession

# async-тесты помечает pytest-asyncio сам (`asyncio_mode = auto` в pytest.ini):
# модульный маркер вешал бы asyncio на синхронные тесты длины/определения.

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Шапка реальной выгрузки: группа «Конечное сальдо» стоит в колонке 10,
# подзаголовок «Количество» — в той же колонке. Поэтому количество берётся
# из индекса 10, а не из «Начального сальдо» (индекс 4).
OSV_HEADER = (
    "Код",
    "Наименование ТМЦ",
    "Ед. изм.",
    "Цена за ед.",
    "Начальное сальдо",
    None,
    "Оборот по дебету",
    None,
    "Оборот по кредиту",
    None,
    "Конечное сальдо",
    None,
)
OSV_SUBHEADER = (
    None,
    None,
    None,
    None,
    "Количество",
    "Стоимость, руб.",
    "Количество",
    "Стоимость, руб.",
    "Количество",
    "Стоимость, руб.",
    "Количество",
    "Стоимость, руб.",
)

SECTION_HEADER = "Завод КТМ СКЛАД СЫРОЙ"


# ─── Helpers ───────────────────────────────────────────────────────────────────


def _osv_row(
    code: object,
    name: object,
    unit: object,
    quantity: object,
    *,
    start_quantity: object = None,
    debit_quantity: object = None,
    credit_quantity: object = None,
) -> list:
    """Строка ОСВ шириной 12 колонок: количество в «Конечном сальдо» (10)."""
    return [
        code,
        name,
        unit,
        None,
        start_quantity,
        None,
        debit_quantity,
        None,
        credit_quantity,
        None,
        quantity,
        None,
    ]


def _osv_rows(
    data_rows: list[list],
    *,
    header: tuple = OSV_HEADER,
    subheader: tuple = OSV_SUBHEADER,
    section_header: str = SECTION_HEADER,
    title: str = "Оборотно-сальдовая ведомость по счету 10",
) -> list[list]:
    """Семь строк шапки листа, заголовки на 8-й, подзаголовки на 9-й."""
    return [
        [title],
        [],
        [section_header],
        [],
        [],
        [],
        [],
        list(header),
        list(subheader),
        *data_rows,
    ]


def _make_workbook_sheets(
    sheets: list[tuple[str, list[list]]],
) -> BytesIO:
    wb = Workbook()
    # openpyxl всегда создаёт первый лист — переиспользуем его под первый набор,
    # чтобы порядок листов совпадал с порядком в списке.
    for position, (name, rows) in enumerate(sheets):
        ws = wb.active if position == 0 else wb.create_sheet()
        ws.title = name
        for row in rows:
            ws.append(list(row))
    buf = BytesIO()
    wb.save(buf)
    return buf


def _make_osv_workbook(data_rows: list[list]) -> BytesIO:
    return _make_workbook_sheets([("Склад сырой", _osv_rows(data_rows))])


async def _make_product(
    session: AsyncSession,
    sku: str,
    *,
    name: str | None = None,
    aliases: list[str] | None = None,
    lengths: list[tuple[float, float | None, bool]] | None = None,
) -> Product:
    product = Product(
        sku=sku,
        name=name or sku,
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
        aliases=list(aliases or []),
    )
    session.add(product)
    await session.flush()
    for length_mm, raw_length_mm, is_primary in lengths or []:
        session.add(
            ProductLength(
                product_id=product.id,
                length_mm=length_mm,
                raw_length_mm=raw_length_mm,
                is_primary=is_primary,
            )
        )
    await session.flush()
    return product


async def _bind_1c_code(
    session: AsyncSession, product: Product, code: str
) -> Product1CCode:
    binding = Product1CCode(product_id=product.id, code=code)
    session.add(binding)
    await session.flush()
    return binding


# ─── Определение и разбор ─────────────────────────────────────────────────────


def test_detect_1c_osv_two_row_header() -> None:
    """Заголовки на 8-й строке, подзаголовки на 9-й, данные с 10-й."""
    rows = _osv_rows([_osv_row("20933", "Кант 2,70м", "м", 10)])

    layout = detect_1c_osv(rows)

    assert layout is not None
    assert layout.header_row_index == 7
    assert layout.data_start_index == 9
    assert layout.code_index == 0
    assert layout.name_index == 1
    assert layout.unit_index == 2
    assert layout.quantity_index == 10


def test_detect_1c_osv_supports_ostatok_na_konec() -> None:
    """Второе написание группы остатка: «Остаток на конец»."""
    header = (*OSV_HEADER[:10], "Остаток на конец", None)
    rows = _osv_rows([], header=header, subheader=OSV_SUBHEADER)

    layout = detect_1c_osv(rows)

    assert layout is not None
    assert layout.quantity_index == 10


def test_detect_1c_osv_rejects_manual_template() -> None:
    """Ручной шаблон (Артикул | Кол-во) режимом ОСВ не считается."""
    rows = [
        ["Артикул", "Кол-во", "Статус качества", "Операции", "Участок"],
        ["ЮП-2616", 12, "Годный", "", "Склад сырья"],
    ]

    assert detect_1c_osv(rows) is None
    assert detect_manual_template(rows) is True


async def test_parse_osv_skips_totals_group_codes_and_empty_quantities() -> None:
    """Итоги, групповые счета (10.1) и пустые количества в предпросмотр не идут."""
    rows = _osv_rows([
        _osv_row("10.1", "Сырьё, группа", "м", 500),
        _osv_row("", "Итого:", None, 500),
        _osv_row("20933.0", "Кант 26мм 2,70м (ЮП-2616)", "м", 100),
        _osv_row("20934", "Кант 26мм 2,70м (ЮП-2617)", "м", None),
        _osv_row("20935", "Уголок", "шт", 7),
    ])

    _sheet, _total, items, summary = await parse_remainders_1c_osv(
        _make_workbook_sheets([("Склад сырой", rows)]).getvalue()
    )

    assert [item.source_code for item in items] == ["20933", "20935"]
    assert summary.total == 2
    assert items[0].source_name == "Кант 26мм 2,70м (ЮП-2616)"
    assert items[0].source_unit == "м"
    assert items[0].source_quantity_m == pytest.approx(100.0)
    assert items[1].source_unit == "шт"
    # До матча артикула нет: sku заполняется только привязкой.
    assert items[0].product_id is None


async def test_parse_osv_skips_numeric_group_code_without_name() -> None:
    """Счёт/итог с числовым кодом и пустым наименованием — не позиция."""
    rows = _osv_rows([
        _osv_row("10", None, "м", 500),
        _osv_row("20933", "Кант 26мм 2,70м (ЮП-2616)", "м", 100),
    ])

    _sheet, _total, items, summary = await parse_remainders_1c_osv(
        _make_workbook_sheets([("Склад сырой", rows)]).getvalue()
    )

    assert [item.source_code for item in items] == ["20933"]
    assert summary.total == 1


async def test_parse_osv_takes_quantity_from_final_balance() -> None:
    """Количество — из «Конечного сальдо», а не из «Начального»."""
    rows = _osv_rows([
        _osv_row(
            "20933",
            "Кант 2,70м",
            "м",
            100,
            start_quantity=999,
            debit_quantity=50,
            credit_quantity=20,
        ),
    ])

    _sheet, _total, items, _summary = await parse_remainders_1c_osv(
        _make_workbook_sheets([("Склад сырой", rows)]).getvalue()
    )

    assert len(items) == 1
    assert items[0].source_quantity_m == pytest.approx(100.0)


async def test_parse_osv_negative_quantity_is_row_error() -> None:
    """Отрицательное количество — ошибка строки, а не пропуск."""
    rows = _osv_rows([_osv_row("20933", "Кант 2,70м", "м", -5)])

    _sheet, _total, items, summary = await parse_remainders_1c_osv(
        _make_workbook_sheets([("Склад сырой", rows)]).getvalue()
    )

    assert summary.total == 1
    assert items[0].status == "invalid"
    assert "Отрицательный остаток" in items[0].errors


async def test_parse_osv_ignores_extra_length_column() -> None:
    """Лишняя колонка «Длина, м.» не сдвигает количество и не задаёт длину."""
    header = (*OSV_HEADER, "Длина, м.")
    subheader = (*OSV_SUBHEADER, None)
    rows = _osv_rows(
        [_osv_row("20933", "Кант 26мм 2,70м", "м", 100) + [2.7]],
        header=header,
        subheader=subheader,
    )

    _sheet, _total, items, _summary = await parse_remainders_1c_osv(
        _make_workbook_sheets([("Склад сырой", rows)]).getvalue()
    )

    assert len(items) == 1
    assert items[0].source_quantity_m == pytest.approx(100.0)


async def test_parse_remainders_excel_autodetects_osv() -> None:
    """``parse_remainders_excel`` сам выбирает режим ОСВ (ручной путь не меняется)."""
    excel = _make_osv_workbook([
        _osv_row("20933", "Кант 26мм 2,70м", "м", 100),
    ])

    sheet_name, _total, items, _summary = await parse_remainders_excel(
        excel.getvalue()
    )

    assert sheet_name == "Склад сырой"
    assert len(items) == 1
    assert items[0].source_code == "20933"
    assert items[0].sku == ""


# ─── Длина из наименования ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "expected_mm"),
    [
        ("Плинтус 100 мм 2,55м", 2550),
        ("Профиль (ЮП-3098) 2,75м", 2750),
        ("Кант 2,7 м", 2700),
        ("Кант 2.7m", 2700),
        ("Кант 3м", 3000),
        ("Кант L=3,61 м", 3610),
        ("Профиль алюминиевый L=3000", 3000),
        ("Кв. труба 10*10 3,0 алюминий", 3000),
        ("Круглая труба 16 мм 2,75", 2750),
        ("Кабель-канал 0,18мм", None),
        ("Уголок 60*32,4", None),
        ("Кант 26мм 20*20*1,5", None),
        ("Крепёж без длины", None),
    ],
)
def test_parse_length_from_name(name: str, expected_mm: int | None) -> None:
    assert parse_length_from_name(name) == expected_mm


# ─── Нормальная длина ─────────────────────────────────────────────────────────


def _lengths(*rows: tuple[float, float | None, bool]) -> list[ProductLength]:
    return [
        ProductLength(length_mm=length_mm, raw_length_mm=raw, is_primary=primary)
        for length_mm, raw, primary in rows
    ]


def test_resolve_normal_length_exact_length() -> None:
    resolved = resolve_normal_length(2500, _lengths((2500, None, True)))

    assert resolved.length_mm == 2500
    assert resolved.error is None
    assert resolved.warning is None


def test_resolve_normal_length_raw_maps_to_normal_without_warning() -> None:
    """`2,75` из наименования — сырьевая длина 2750 при нормальной 2700."""
    resolved = resolve_normal_length(2750, _lengths((2700, 2750, True)))

    assert resolved.length_mm == 2700
    assert resolved.warning is None


def test_resolve_normal_length_nearest_lower_with_warning() -> None:
    """Расхождение больше 100 мм (ADR-0077 п.5) — предупреждение, не ошибка."""
    resolved = resolve_normal_length(2610, _lengths((2500, None, True)))

    assert resolved.length_mm == 2500
    assert resolved.warning == "Длина 2,61 приведена к 2,5"


def test_resolve_normal_length_small_deviation_is_silent() -> None:
    """Порог предупреждения — больше 100 мм: 2,55 → 2,5 молчит (ADR-0077 п.5)."""
    resolved = resolve_normal_length(2550, _lengths((2500, None, True)))

    assert resolved.length_mm == 2500
    assert resolved.warning is None


def test_resolve_normal_length_smaller_than_minimum_is_error() -> None:
    resolved = resolve_normal_length(2000, _lengths((2500, None, True)))

    assert resolved.length_mm is None
    assert resolved.error == "Длина 2,0 меньше минимальной длины артикула (2,5)"


def test_resolve_normal_length_without_product_lengths_is_error() -> None:
    """У артикула нет ни одной длины: ошибка строки, а не ``IndexError``."""
    resolved = resolve_normal_length(2700, [])

    assert resolved.length_mm is None
    assert resolved.error == "У артикула не указана длина"


def test_resolve_normal_length_without_name_uses_primary() -> None:
    resolved = resolve_normal_length(
        None, _lengths((2700, None, True), (3000, None, False))
    )

    assert resolved.length_mm == 2700


def test_resolve_normal_length_without_name_single_length() -> None:
    resolved = resolve_normal_length(None, _lengths((3050, None, False)))

    assert resolved.length_mm == 3050


def test_resolve_normal_length_without_name_several_without_primary_is_error() -> None:
    resolved = resolve_normal_length(
        None, _lengths((2700, None, False), (3000, None, False))
    )

    assert resolved.length_mm is None
    assert resolved.error == (
        "В наименовании не указана длина, у артикула несколько длин"
    )


# ─── Сопоставление с артикулом ────────────────────────────────────────────────


def _items(data_rows: list[list]) -> list:
    from app.stock.import_1c_osv import parse_1c_osv_rows

    items, _summary = parse_1c_osv_rows(_osv_rows(data_rows))
    return items


async def test_lookup_1c_matches_by_code(session: AsyncSession) -> None:
    """Код номенклатуры 1С (20933.0 → 20933) ведёт к артикулу."""
    from app.stock.import_1c_osv import _lookup_1c_products

    product = await _make_product(session, "ЮП-2616", name="Кант универсальный")
    await _bind_1c_code(session, product, "20933")
    items = _items([
        _osv_row("20933.0", "Кант 26мм 2,70м (ЮП-2616)", "м", 6391),
    ])

    await _lookup_1c_products(session, items)

    assert items[0].product_id == product.id
    assert items[0].sku == "ЮП-2616"
    assert items[0].product_name == "Кант универсальный"
    assert items[0].status == "valid"
    assert items[0].errors == []


async def test_lookup_1c_matches_sku_in_name_and_keeps_canon(session: AsyncSession) -> None:
    """`#033-00 (ЮП-2630)` — две записи одной группы → канон группы."""
    from app.stock.import_1c_osv import _lookup_1c_products

    canon = await _make_product(session, "033", aliases=["ЮП-2630"])
    alias = await _make_product(session, "ЮП-2630")
    items = _items([
        _osv_row("22069", "#033-00 (ЮП-2630)", "м", 100),
    ])

    await _lookup_1c_products(session, items)

    assert items[0].product_id == canon.id
    assert items[0].product_id != alias.id
    assert items[0].status == "valid"
    assert items[0].warnings == []


async def test_lookup_1c_different_groups_is_ambiguous(session: AsyncSession) -> None:
    """Кандидаты из разных групп эквивалентов — ошибка «неоднозначно»."""
    from app.stock.import_1c_osv import _lookup_1c_products

    await _make_product(session, "ALS-1103")
    await _make_product(session, "ЮП-3773")
    items = _items([
        _osv_row("16944", "Кант (ALS-1103 / ЮП-3773)", "м", 100),
    ])

    await _lookup_1c_products(session, items)

    assert items[0].product_id is None
    assert items[0].status == "invalid"
    assert items[0].errors == ["Артикул неоднозначен: ALS-1103, ЮП-3773"]


async def test_lookup_1c_without_match_reports_code(session: AsyncSession) -> None:
    """Ни кода, ни артикула в наименовании — ошибка с кодом из файла."""
    from app.stock.import_1c_osv import _lookup_1c_products

    items = _items([
        _osv_row("16944", "Упаковка пакет 40*60", "шт", 100),
    ])

    await _lookup_1c_products(session, items)

    assert items[0].status == "invalid"
    assert items[0].errors == [
        "Код 16944 не привязан к артикулу, в наименовании артикул не найден"
    ]


async def test_lookup_1c_code_conflicts_with_name_group(session: AsyncSession) -> None:
    """Код привязан к одной группе, наименование указывает на другую."""
    from app.stock.import_1c_osv import _lookup_1c_products

    bound = await _make_product(session, "ЮП-2616")
    await _make_product(session, "АТ-7121")
    await _bind_1c_code(session, bound, "16944")
    items = _items([
        _osv_row("16944", "Кант (АТ-7121)", "м", 100),
    ])

    await _lookup_1c_products(session, items)

    assert items[0].product_id is None
    assert items[0].status == "invalid"
    assert items[0].errors == [
        "Код 16944 привязан к ЮП-2616, в наименовании АТ-7121"
    ]


async def test_lookup_1c_exact_name_warns(session: AsyncSession) -> None:
    """Точное наименование артикула — матч с предупреждением."""
    from app.stock.import_1c_osv import _lookup_1c_products

    product = await _make_product(
        session, "KANT-26", name="Кант универсальный 26мм"
    )
    items = _items([
        _osv_row("20999", "Кант универсальный 26мм", "шт", 10),
    ])

    await _lookup_1c_products(session, items)

    assert items[0].product_id == product.id
    assert items[0].status == "valid"
    assert items[0].warnings == ["Сопоставлено по наименованию"]


async def test_lookup_1c_exact_name_ignores_nbsp_and_extra_spaces(
    session: AsyncSession,
) -> None:
    """Точное имя: NBSP и двойные пробелы в БД не мешают нормализованному имени."""
    from app.stock.import_1c_osv import _lookup_1c_products

    product = await _make_product(
        session, "KANT-NBSP", name="Кант\u00a0универсальный  26мм"
    )
    items = _items([
        _osv_row("21007", "кант универсальный 26мм", "шт", 10),
    ])

    await _lookup_1c_products(session, items)

    assert items[0].product_id == product.id
    assert items[0].status == "valid"
    assert items[0].warnings == ["Сопоставлено по наименованию"]


async def test_lookup_1c_code_conflict_lists_all_group_candidates(
    session: AsyncSession,
) -> None:
    """Конфликт кода и группы перечисляет всех кандидатов, а не первого."""
    from app.stock.import_1c_osv import _lookup_1c_products

    bound = await _make_product(session, "ЮП-2616")
    await _bind_1c_code(session, bound, "16944")
    # Две карточки — одна группа эквивалентов, отличная от группы кода.
    await _make_product(session, "ALS-1103", aliases=["ЮП-3773"])
    await _make_product(session, "ЮП-3773")
    items = _items([
        _osv_row("16944", "Кант (ALS-1103 / ЮП-3773)", "м", 100),
    ])

    await _lookup_1c_products(session, items)

    assert items[0].product_id is None
    assert items[0].status == "invalid"
    assert items[0].errors == [
        "Код 16944 привязан к ЮП-2616, в наименовании ALS-1103, ЮП-3773"
    ]


# ─── Длина и штуки ────────────────────────────────────────────────────────────


async def _resolve_quantities(session: AsyncSession, items: list) -> None:
    from app.stock.import_1c_osv import _lookup_1c_products, resolve_1c_osv_quantities

    await _lookup_1c_products(session, items)
    await resolve_1c_osv_quantities(session, items)


async def test_resolve_quantities_meters_to_pieces_by_normal_length(
    session: AsyncSession,
) -> None:
    """5084,1 м при нормальной 2,7 м → 1883 шт (сырьевая 2,75 — точное raw)."""
    product = await _make_product(
        session, "ЮП-3098", lengths=[(2700, 2750, True)]
    )
    await _bind_1c_code(session, product, "20933")
    items = _items([
        _osv_row("20933", "Профиль (ЮП-3098) 2,75м", "м", 5084.1),
    ])

    await _resolve_quantities(session, items)

    item = items[0]
    assert item.status == "valid"
    assert item.quantity == 1883
    assert item.dimensions == {"length_mm": 2700}
    assert item.dimensions_label == "2,7 м"
    assert item.source_quantity_m == pytest.approx(5084.1)
    assert item.warnings == []


async def test_resolve_quantities_nearest_lower_length_warns(
    session: AsyncSession,
) -> None:
    """Наибольшая нормальная ≤ написанной (2,61 → 2,5) — штуки и предупреждение."""
    product = await _make_product(session, "PLINTH-100", lengths=[(2500, None, True)])
    await _bind_1c_code(session, product, "22069")
    items = _items([
        _osv_row("22069", "Плинтус 100 мм 2,61м", "м", 5084.1),
    ])

    await _resolve_quantities(session, items)

    item = items[0]
    assert item.status == "valid"
    assert item.quantity == 2033
    assert item.dimensions == {"length_mm": 2500}
    assert item.warnings == ["Длина 2,61 приведена к 2,5"]


async def test_resolve_quantities_without_name_length_uses_primary(
    session: AsyncSession,
) -> None:
    product = await _make_product(
        session,
        "KANT-NOLEN",
        lengths=[(2700, None, True), (3000, None, False)],
    )
    await _bind_1c_code(session, product, "20933")
    items = _items([_osv_row("20933", "Кант 26мм алюминий", "м", 2700)])

    await _resolve_quantities(session, items)

    assert items[0].quantity == 1000
    assert items[0].dimensions == {"length_mm": 2700}


async def test_resolve_quantities_without_name_length_and_primary_is_error(
    session: AsyncSession,
) -> None:
    product = await _make_product(
        session,
        "KANT-MANY",
        lengths=[(2700, None, False), (3000, None, False)],
    )
    await _bind_1c_code(session, product, "20933")
    items = _items([_osv_row("20933", "Кант 26мм алюминий", "м", 2700)])

    await _resolve_quantities(session, items)

    assert items[0].status == "invalid"
    assert items[0].quantity is None
    assert "В наименовании не указана длина, у артикула несколько длин" in items[0].errors


async def test_resolve_quantities_product_without_lengths_is_error(
    session: AsyncSession,
) -> None:
    """Артикул без ``ProductLength`` и метры в файле — ошибка строки, не 500."""
    product = await _make_product(session, "KANT-NOLENGTHS")
    await _bind_1c_code(session, product, "20933")
    items = _items([_osv_row("20933", "Кант 2,70м", "м", 5400)])

    await _resolve_quantities(session, items)

    assert items[0].status == "invalid"
    assert items[0].quantity is None
    assert items[0].errors == ["У артикула не указана длина"]


async def test_resolve_quantities_less_than_one_piece_is_error(
    session: AsyncSession,
) -> None:
    product = await _make_product(session, "KANT-27", lengths=[(2700, None, True)])
    await _bind_1c_code(session, product, "20933")
    items = _items([_osv_row("20933", "Кант 2,70м", "м", 2.5)])

    await _resolve_quantities(session, items)

    assert items[0].status == "invalid"
    assert items[0].quantity is None
    assert "Остаток меньше одной штуки" in items[0].errors


async def test_resolve_quantities_pieces_unit_keeps_quantity(
    session: AsyncSession,
) -> None:
    """`шт` — штуки как есть, без пересчёта и без длины."""
    product = await _make_product(session, "UGOLOK", lengths=[(3000, None, True)])
    await _bind_1c_code(session, product, "20935")
    items = _items([_osv_row("20935", "Уголок 10*10 3,0", "шт.", 485)])

    await _resolve_quantities(session, items)

    assert items[0].status == "valid"
    assert items[0].quantity == 485
    assert items[0].dimensions is None
    assert items[0].source_quantity_m is None


@pytest.mark.parametrize("unit", ["м", "м.п.", "п.м.", "мп"])
async def test_resolve_quantities_all_meter_unit_spellings(
    session: AsyncSession, unit: str
) -> None:
    """Все написания метров из спеки §6.3 пересчитываются в штуки."""
    product = await _make_product(session, "KANT-M", lengths=[(2700, None, True)])
    await _bind_1c_code(session, product, "20933")
    items = _items([_osv_row("20933", "Кант 2,70м", unit, 5400)])

    await _resolve_quantities(session, items)

    assert items[0].status == "valid"
    assert items[0].quantity == 2000
    assert items[0].source_quantity_m == pytest.approx(5400.0)


async def test_resolve_quantities_unsupported_unit_is_error(
    session: AsyncSession,
) -> None:
    product = await _make_product(session, "KANT-KG", lengths=[(2700, None, True)])
    await _bind_1c_code(session, product, "20933")
    items = _items([_osv_row("20933", "Кант 2,70м", "кг", 100)])

    await _resolve_quantities(session, items)

    assert items[0].status == "invalid"
    assert items[0].quantity is None
    assert items[0].errors == ["Единица измерения 'кг' не поддерживается"]


# ─── Автоучасток ──────────────────────────────────────────────────────────────


async def _make_section(
    session: AsyncSession,
    code: str,
    name: str,
    *,
    section_type: str = "raw_stock",
    is_active: bool = True,
) -> Section:
    section = Section(
        code=code,
        name=name,
        type=section_type,
        is_active=is_active,
        sort_order=0,
    )
    session.add(section)
    await session.flush()
    return section


async def test_resolve_storage_section_exact_name(session: AsyncSession) -> None:
    from app.stock.import_1c_osv import resolve_1c_storage_section

    section = await _make_section(session, "RAW_STOCK", "Склад сырья")
    rows = [["Оборотно-сальдовая ведомость"], ["Склад сырья"]]

    detected = await resolve_1c_storage_section(session, rows)

    assert detected == (section.id, "Склад сырья")


async def test_resolve_storage_section_by_synonym(session: AsyncSession) -> None:
    from app.stock.import_1c_osv import resolve_1c_storage_section

    section = await _make_section(
        session, "PREP_STOCK", "Склад подготовки", section_type="wip_stock"
    )
    rows = [["Оборотно-сальдовая ведомость"], ["Подготовительный участок"]]

    detected = await resolve_1c_storage_section(session, rows)

    assert detected == (section.id, "Склад подготовки")


async def test_resolve_storage_section_two_candidates_is_no_auto(
    session: AsyncSession,
) -> None:
    """Два разных склада в шапке — автоопределения нет (ручной выбор)."""
    from app.stock.import_1c_osv import resolve_1c_storage_section

    await _make_section(session, "RAW_STOCK", "Склад сырья")
    await _make_section(
        session, "PREP_STOCK", "Склад подготовки", section_type="wip_stock"
    )
    rows = [["Завод КТМ СКЛАД СЫРОЙ"], ["Подготовительный участок"]]

    detected = await resolve_1c_storage_section(session, rows)

    assert detected == (None, None)


async def test_resolve_storage_section_ignores_inactive(session: AsyncSession) -> None:
    from app.stock.import_1c_osv import resolve_1c_storage_section

    await _make_section(session, "RAW_STOCK", "Склад сырья", is_active=False)

    detected = await resolve_1c_storage_section(session, [["Завод КТМ СКЛАД СЫРОЙ"]])

    assert detected == (None, None)


# ─── API: метадата листов и предпросмотр ──────────────────────────────────────


async def test_sheets_endpoint_reports_kinds_and_sections(
    client: AsyncClient, session: AsyncSession
) -> None:
    section = await _make_section(session, "RAW_STOCK", "Склад сырья")
    await session.commit()

    manual_rows = [
        ["Артикул", "Кол-во", "Статус качества", "Операции", "Участок"],
        ["ЮП-2616", 12, "Годный", "", "Склад сырья"],
    ]
    excel = _make_workbook_sheets([
        ("Импорт остатков", manual_rows),
        ("Склад сырой", _osv_rows([_osv_row("20933", "Кант 2,70м", "м", 100)])),
        ("Пусто", [["Ничего интересного"]]),
    ])

    resp = await client.post(
        "/api/stock/import/remainders/sheets",
        files={"file": ("osv.xlsx", excel, XLSX_MIME)},
    )

    assert resp.status_code == 200, resp.text
    sheets = resp.json()["sheets"]
    assert [sheet["kind"] for sheet in sheets] == [
        "manual_template",
        "1c_osv",
        "unknown",
    ]
    assert sheets[1]["index"] == 1
    assert sheets[1]["name"] == "Склад сырой"
    assert sheets[1]["detected_section_id"] == section.id
    assert sheets[1]["detected_section_name"] == "Склад сырья"
    assert sheets[0]["detected_section_id"] is None
    assert sheets[0]["detected_section_name"] is None


async def test_sheets_endpoint_broken_xlsx_is_422(client: AsyncClient) -> None:
    """Битый файл — 422 с понятным текстом, а не 500 из недр calamine."""
    resp = await client.post(
        "/api/stock/import/remainders/sheets",
        files={"file": ("osv.xlsx", b"definitely not a workbook", XLSX_MIME)},
    )

    assert resp.status_code == 422, resp.text
    assert "Excel" in resp.json()["detail"]


async def test_preview_osv_returns_source_fields_and_pieces(
    client: AsyncClient, session: AsyncSession
) -> None:
    section = await _make_section(session, "RAW_STOCK", "Склад сырья")
    product = await _make_product(
        session,
        "ЮП-3098",
        name="Профиль П-образный",
        lengths=[(2700, 2750, True)],
    )
    await _bind_1c_code(session, product, "20933")
    unit_product = await _make_product(
        session, "PROF-KG", lengths=[(2700, None, True)]
    )
    await _bind_1c_code(session, unit_product, "22069")
    await session.commit()

    excel = _make_osv_workbook([
        _osv_row("20933", "Профиль (ЮП-3098) 2,75м", "м", 5084.1),
        _osv_row("16944", "Упаковка пакет", "шт", 10),
        _osv_row("22069", "Другой профиль", "кг", 5),
    ])

    resp = await client.post(
        "/api/stock/import/remainders/preview",
        files={"file": ("osv.xlsx", excel, XLSX_MIME)},
        data={"sheet_index": "0"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source_kind"] == "1c_osv"
    assert body["detected_section_id"] == section.id
    assert body["detected_section_name"] == "Склад сырья"

    matched = body["items"][0]
    assert matched["source_code"] == "20933"
    assert matched["source_name"] == "Профиль (ЮП-3098) 2,75м"
    assert matched["source_unit"] == "м"
    assert matched["source_quantity_m"] == pytest.approx(5084.1)
    assert matched["sku"] == "ЮП-3098"
    assert matched["product_name"] == "Профиль П-образный"
    assert matched["quantity"] == 1883
    assert matched["dimensions"] == {"length_mm": 2700}
    assert matched["dimensions_label"] == "2,7 м"
    assert matched["target_section_id"] == section.id
    assert matched["status"] == "valid"

    unmatched = body["items"][1]
    assert unmatched["status"] == "invalid"
    assert unmatched["errors"] == [
        "Код 16944 не привязан к артикулу, в наименовании артикул не найден"
    ]

    unsupported_unit = body["items"][2]
    assert unsupported_unit["status"] == "invalid"
    assert unsupported_unit["errors"] == ["Единица измерения 'кг' не поддерживается"]


async def test_preview_osv_search_finds_source_code(
    client: AsyncClient, session: AsyncSession
) -> None:
    product = await _make_product(session, "ЮП-3098", lengths=[(2700, 2750, True)])
    await _bind_1c_code(session, product, "20933")
    await session.commit()

    excel = _make_osv_workbook([
        _osv_row("20933", "Профиль (ЮП-3098) 2,75м", "м", 5084.1),
        _osv_row("22069", "Другой профиль без артикула", "м", 10),
    ])

    resp = await client.post(
        "/api/stock/import/remainders/preview",
        files={"file": ("osv.xlsx", excel, XLSX_MIME)},
        data={"sheet_index": "0", "search": "20933"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items_total"] == 1
    assert body["items"][0]["source_code"] == "20933"


async def test_preview_manual_template_reports_manual_kind(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Ручной шаблон работает как раньше и получает ``manual_template``."""
    product = await _make_product(session, "MAN-1")
    await session.commit()

    excel = _make_workbook_sheets([
        (
            "Остатки",
            [
                ["SKU", "Количество", "Комментарий"],
                ["MAN-1", 7, None],
            ],
        )
    ])

    resp = await client.post(
        "/api/stock/import/remainders/preview",
        files={"file": ("manual.xlsx", excel, XLSX_MIME)},
        data={"sheet_index": "0"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source_kind"] == "manual_template"
    assert body["detected_section_id"] is None
    assert body["detected_section_name"] is None
    item = body["items"][0]
    assert item["product_id"] == product.id
    assert item["quantity"] == 7
    assert item["source_code"] is None
    assert item["source_quantity_m"] is None


