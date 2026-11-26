"""Маркеры ОСВ: цвет, пресс и ПФ из наименования 1С (#468).

Спека: ``docs/stock-import-1c-spec.md``; тикет #468 «выполненные операции —
цвет, пресс, ПФ → префикс маршрута».

Первый срез — чистый разбор наименования: слово и суффикс цвета, пресс,
полуфабрикат. Правила цвета/пресса берутся из справочника (``anod_colors`` /
``press_types``), поэтому тест подаёт их явно, как это делает загрузчик из БД.
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
from app.models.route import ProductionRoute
from app.seeds.canon.registry import build_plant_config
from app.seeds.seeders.route_rule_profile_seeder import seed_route_rule_profile
from app.seeds.seeders.sections_seeder import seed_section_operations, seed_sections
from app.seeds.seeders.selection_rules_seeder import seed_selection_rules
from app.stock.import_1c_markers import (
    ColorVocabulary,
    extract_osv_markers,
)
from app.stock.import_1c_osv import resolve_1c_osv_completed_operations
from app.stock.import_service import RemainderItem
from app.stock.models import StockTransaction
from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

VOCABULARY = ColorVocabulary(
    color_keywords=(
        ("старое золото", "S120-2"),
        ("серебр", "ANOD_01"),
        ("золот", "ANOD_02"),
        ("бронз", "ANOD_03"),
        ("чёрн", "ANOD_05"),
        ("черн", "ANOD_05"),
        ("шампань", "ANOD_06"),
        ("мед", "ANOD_07"),
        ("титан", "ANOD_08"),
    ),
    color_names={
        "ANOD_01": "Серебро",
        "ANOD_02": "Золото",
        "ANOD_03": "Бронза",
        "ANOD_05": "Чёрный",
        "ANOD_06": "Шампань",
        "ANOD_07": "Медь",
        "ANOD_08": "Титан",
        "S120-2": "Старое золото",
    },
    press_keywords=(("окн", "PRESS_WINDOW"), ("греб", "PRESS_COMB")),
)


@pytest.mark.parametrize(
    ("name", "anchors", "color_code", "press_code", "semi_finished"),
    [
        # Суффикс сразу после артикула: ALS-917-01 → серебро.
        ("ALS-917-01 ПФ 2,7м", {"ALS-917"}, "ANOD_01", None, True),
        # Отдельная группа «– 02(золото)»: суффикс и слово совпадают.
        ("Уголок 15*15 3,0 – 02(золото)  ПФ", set(), "ANOD_02", None, True),
        # Слово и суффикс после артикула: чёрный.
        ("Профиль 1515-05 черный ПФ", {"1515"}, "ANOD_05", None, True),
        # Пресс-маркер «гребенка» → PRESS_COMB.
        ("АТ-4863-02 гребенка ПФ 2,7м", {"АТ-4863"}, "ANOD_02", "PRESS_COMB", True),
        # После переименования SKU база ЮП-2464, суффикс -01 — серебро.
        ("ЮП-2464-01 ПФ 2,5м", {"ЮП-2464"}, "ANOD_01", None, True),
        # Дефисное написание артикула в 1С: ALS1103, суффикс у алиаса ЮП-3773.
        (
            "ALS1103/ЮП-3773-05 ПФ 2,5м",
            {"ALS-1103", "ЮП-3773"},
            "ANOD_05",
            None,
            True,
        ),
        # Суффикс чужого артикула (РП-АКП) цветом не становится.
        ("РП-АКП-08 (ЮП-2183) 2,70", {"ЮП-2183"}, None, None, False),
        # Исполнение без ANOD_04 — не цвет: молча не трогаем.
        ("ЮП-003-04 ПФ 3м", {"ЮП-003"}, None, None, True),
        # «01,02» — диапазон исполнений, а не цвет.
        (
            "РП-АКП-01,02 (КП5179/ АТ-4863) 2,7",
            {"АТ-4863"},
            None,
            None,
            False,
        ),
    ],
)
def test_extract_markers_from_osv_name(
    name: str,
    anchors: set[str],
    color_code: str | None,
    press_code: str | None,
    semi_finished: bool,
) -> None:
    markers = extract_osv_markers(name, anchors=anchors, vocabulary=VOCABULARY)

    assert markers.color_code == color_code
    assert markers.press_code == press_code
    assert markers.is_semi_finished is semi_finished
    assert markers.errors == ()


def test_color_name_comes_from_operation_dictionary() -> None:
    markers = extract_osv_markers(
        "ALS-917-01 ПФ 2,7м", anchors={"ALS-917"}, vocabulary=VOCABULARY
    )

    assert markers.color_name == "Серебро"


def test_longest_color_word_wins() -> None:
    markers = extract_osv_markers(
        "Профиль – старое золото", anchors=set(), vocabulary=VOCABULARY
    )

    assert markers.color_code == "S120-2"


def test_word_and_suffix_disagree_is_error() -> None:
    markers = extract_osv_markers(
        "Профиль 1515-05 золото ПФ", anchors={"1515"}, vocabulary=VOCABULARY
    )

    assert markers.color_code is None
    assert len(markers.errors) == 1
    assert "Цвет" in markers.errors[0]
    assert "-05" in markers.errors[0]
    assert "золот" in markers.errors[0]


def test_two_press_markers_are_error() -> None:
    markers = extract_osv_markers(
        "Профиль 1515-05 окно гребенка ПФ", anchors={"1515"}, vocabulary=VOCABULARY
    )

    assert markers.press_code is None
    assert len(markers.errors) == 1
    assert "Пресс" in markers.errors[0]


def test_two_color_words_same_length_are_ambiguous() -> None:
    markers = extract_osv_markers(
        "Профиль бронза золото", anchors=set(), vocabulary=VOCABULARY
    )

    assert markers.color_code is None
    assert markers.errors
    assert "неоднозначен" in markers.errors[0]


def test_name_without_markers_has_no_markers() -> None:
    markers = extract_osv_markers(
        "Профиль (ЮП-3098) 2,75м", anchors={"ЮП-3098"}, vocabulary=VOCABULARY
    )

    assert markers.has_markers is False
    assert markers.errors == ()


# ─── Префикс маршрута по реальному справочнику ────────────────────────────────


async def _seed_packaging_route(session: AsyncSession) -> Section:
    """Секции, операции, профиль и правила ``packaging_map_rp`` из сидов."""
    config = build_plant_config()
    sections = await seed_sections(session, config.production.sections)
    await seed_section_operations(session, sections, config.production)
    profile_def = next(
        profile
        for profile in config.routing.route_rule_profiles
        if profile.code == "packaging_map_rp"
    )
    profile = await seed_route_rule_profile(session, profile_def)
    rules = [
        rule
        for rule in config.routing.selection_rules
        if rule.profile_code == "packaging_map_rp"
    ]
    await seed_selection_rules(session, rules, profile, sections)
    await session.flush()
    return sections["FINISHED_STOCK"]


async def _make_product(
    session: AsyncSession,
    sku: str,
    *,
    aliases: list[str] | None = None,
) -> Product:
    product = Product(
        sku=sku,
        name=sku,
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
        aliases=aliases or [],
    )
    session.add(product)
    await session.flush()
    session.add(
        ProductLength(
            product_id=product.id,
            length_mm=2700,
            raw_length_mm=2750,
            is_primary=True,
        )
    )
    await session.flush()
    return product


def _item(row: int, name: str, product_id: int) -> RemainderItem:
    return RemainderItem(
        source_row_number=row,
        sku="",
        quantity=10.0,
        comment=None,
        product_id=product_id,
        product_name=None,
        status="valid",
        errors=[],
        raw_values=[],
        source_code=str(row),
        source_name=name,
        source_unit="м",
        source_quantity_m=27.0,
    )


async def test_semi_finished_row_gets_anodizing_prefix_and_finished_stock(
    session: AsyncSession,
) -> None:
    finished = await _seed_packaging_route(session)
    product = await _make_product(session, "ALS-917")
    item = _item(1, "ALS-917-01 ПФ 2,7м", product.id)

    await resolve_1c_osv_completed_operations(session, [item])

    assert item.status == "valid", item.errors
    assert item.errors == []
    assert "Серебро" in (item.completed_operations_raw or "")
    assert "Спанбонд" in (item.completed_operations_raw or "")
    assert item.target_section_id == finished.id
    assert item.target_section_name == finished.name


async def test_press_and_color_row_prefix_includes_press_operation(
    session: AsyncSession,
) -> None:
    await _seed_packaging_route(session)
    product = await _make_product(session, "АТ-4863")
    item = _item(1, "АТ-4863-02 гребенка ПФ 2,7м", product.id)

    await resolve_1c_osv_completed_operations(session, [item])

    assert item.status == "valid", item.errors
    raw = item.completed_operations_raw or ""
    assert "Гребенка" in raw
    assert "Золото" in raw
    assert "Спанбонд" in raw


async def test_color_without_pf_keeps_sheet_section_and_stretch_pack(
    session: AsyncSession,
) -> None:
    await _seed_packaging_route(session)
    product = await _make_product(session, "ALS-917")
    item = _item(1, "ALS-917-01 2,7м", product.id)

    await resolve_1c_osv_completed_operations(session, [item])

    assert item.status == "valid", item.errors
    assert "Стрейч" in (item.completed_operations_raw or "")
    assert item.target_section_id is None


async def test_row_without_markers_gets_empty_prefix(
    session: AsyncSession,
) -> None:
    await _seed_packaging_route(session)
    product = await _make_product(session, "ЮП-2183")
    item = _item(1, "РП-АКП-08 (ЮП-2183) 2,70", product.id)

    await resolve_1c_osv_completed_operations(session, [item])

    assert item.status == "valid", item.errors
    assert item.completed_operations_raw == ""
    assert item.target_section_id is None


async def test_marker_conflict_makes_row_invalid_with_reason(
    session: AsyncSession,
) -> None:
    await _seed_packaging_route(session)
    product = await _make_product(session, "1515")
    item = _item(1, "Профиль 1515-05 золото ПФ 2,7м", product.id)

    await resolve_1c_osv_completed_operations(session, [item])

    assert item.status == "invalid"
    assert item.completed_operations_raw is None
    assert any("Цвет не совпадает" in error for error in item.errors)


async def test_color_suffix_after_alias_group_member_is_recognized(
    session: AsyncSession,
) -> None:
    """1С пишет ``ЮП-3473-06``, канон группы — ``ЮП-2910``: суффикс читается."""
    await _seed_packaging_route(session)
    canon = await _make_product(session, "ЮП-2910", aliases=["ЮП-3473"])
    await _make_product(session, "ЮП-3473", aliases=["ЮП-2910"])
    item = _item(1, "ЮП-3473-06 ПФ 2,7м", canon.id)

    await resolve_1c_osv_completed_operations(session, [item])

    assert item.status == "valid", item.errors
    assert "Шампань" in (item.completed_operations_raw or "")


async def test_route_prefix_does_not_persist_a_route(
    session: AsyncSession,
) -> None:
    await _seed_packaging_route(session)
    product = await _make_product(session, "ALS-917")
    item = _item(1, "ALS-917-01 ПФ 2,7м", product.id)

    await resolve_1c_osv_completed_operations(session, [item])

    routes = await session.scalar(select(func.count()).select_from(ProductionRoute))
    assert routes == 0


# ─── API: предпросмотр и заливка ──────────────────────────────────────────────

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
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


def _osv_row(code: object, name: object, unit: object, quantity: object) -> list:
    return [code, name, unit, None, None, None, None, None, None, None, quantity, None]


def _make_osv_workbook(data_rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Склад сырой"
    for row in [
        ["Оборотно-сальдовая ведомость по счету 10"],
        [],
        ["Завод КТМ СКЛАД СЫРОЙ"],
        [],
        [],
        [],
        [],
        list(OSV_HEADER),
        list(OSV_SUBHEADER),
        *data_rows,
    ]:
        ws.append(row)
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


async def test_preview_and_apply_semi_finished_row_to_finished_stock(
    client: AsyncClient, session: AsyncSession
) -> None:
    """ПФ-строка: префикс маршрута в оси, участок — Склад ГП, а не лист."""
    finished = await _seed_packaging_route(session)
    raw_stock = (
        await session.execute(select(Section).where(Section.code == "RAW_STOCK"))
    ).scalar_one()
    product = await _make_product(session, "ALS-917")
    session.add(Product1CCode(product_id=product.id, code="22063"))
    await session.commit()

    content = _make_osv_workbook(
        [_osv_row("22063", "ALS-917-01 ПФ 2,7м", "м", 27)]
    )
    preview = await client.post(
        "/api/stock/import/remainders/preview",
        files={"file": ("osv.xlsx", content, XLSX_MIME)},
        data={"sheet_index": "0"},
    )
    assert preview.status_code == 200, preview.text
    item = preview.json()["items"][0]
    assert item["status"] == "valid", item["errors"]
    assert item["target_section_id"] == finished.id
    assert item["target_section_name"] == finished.name
    assert {
        stage["operation_code"] for stage in item["completed_stages"]
    } >= {"SHOT", "ANOD_01", "PACK_SPUNBOND"}

    applied = await client.post(
        "/api/stock/import/remainders",
        files={"file": ("osv.xlsx", content, XLSX_MIME)},
        data={
            "location_id": str(raw_stock.id),
            "sheet_index": "0",
            "skip_invalid": "true",
        },
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["success"] is True, body
    assert body["imported_count"] == 1

    transactions = (
        await session.scalars(
            select(StockTransaction).where(
                StockTransaction.to_location_id == finished.id
            )
        )
    ).all()
    assert len(transactions) == 1
    assert transactions[0].completed_operations == [
        "ANOD_01",
        "PACK_SPUNBOND",
        "SHOT",
    ]
