from io import BytesIO

import pytest
from app.core.config import settings
from app.models.import_template import ImportTemplate
from app.models.imports import ImportBatch, ImportFile
from app.models.production_plan import PlanChangeItem, PlanChangeSet, ProductionPlan
from app.models.route import RouteRuleProfile
from app.services.excel_import import parse_factory_plan_workbook, parse_row_selection
from openpyxl import Workbook

from tests.test_integrity_invariants import assert_no_invariants_violations


def _workbook_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "План май 26 05"
    ws.append(["", "", "Комментарий"])
    ws.append(["Заявка № 05", "май"])
    ws.append([])
    ws.append(["", "", "", "", "", "", "", "", "", "", "", "", "Формирование ящиков"])
    ws.append(
        [
            "Артикул",
            "пополнение",
            "Наименование",
            "остатки сырья на КТМ",
            "Цвет",
            "кол-во шт. в 2,7",
            "Длина, м",
            "Пробивка/сверловка",
            "Упаковка",
            "Примечание ",
            "Длина после упак, м",
            "кол-во штук готовой продукции",
            "Запад",
            "Восток",
            "Вид конечного продукта",
            "Комментарии",
            "",
            "",
            "Упаковка в 1,8",
            "добавить",
        ]
    )
    ws.append(
        [
            "ЮП-2616",
            "ТЗ",
            "Кант универсальный 47мм 2,7 анод черный мат",
            7300,
            "черный",
            300,
            2.7,
            "",
            "смотка спанбондом поштучно в пачке 10 штук",
            "",
            2.7,
            300,
            "",
            300,
            "П/ф",
        ]
    )
    ws.append(["ЮП-2604", "ТЗ", "", 3700, "черный", 300, 2.7, "", "", "", 2.7, 300, "", 300, "П/ф"])
    ws.append(
        [
            "ЮП-2083",
            "ТЗ",
            "Стык 38 мм. 2,7 анод.серебро, матовый",
            2958,
            "серебро",
            1100,
            2.7,
            "сверло",
            "поф",
            "",
            0.9,
            1500,
            1500,
            0,
            "ГП",
        ]
    )
    ws.append(["ЮП-2083", "", "", "", "серебро", "", "", "сверло", "поф", "", 1.8, 900, 900, 0, "ГП"])
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


async def _create_template(session, *, name: str, code: str) -> ImportTemplate:
    template = ImportTemplate(
        name=name,
        code=code,
        is_active=True,
        column_mapping={"sku": {"header": "Артикул", "column": "A"}},
    )
    session.add(template)
    await session.flush()
    return template


def test_factory_plan_parser_keeps_pair_rows_apart_and_groups_continuations() -> None:
    parsed = parse_factory_plan_workbook(_workbook_bytes(), "plan.xlsx")

    assert parsed.sheet_name == "План май 26 05"
    assert parsed.header_row_number == 5
    # Период больше не парсится: ParsedWorkbook и строки не несут period_start/end.
    assert not hasattr(parsed, "period_start")
    assert not hasattr(parsed, "period_end")
    # Склейки пары больше нет (#312): строки 6 и 7 — две позиции, а строка
    # 8-9 (тот же SKU без собственного входа) — по-прежнему одна операция.
    assert len(parsed.parsed_rows) == 3
    for row in parsed.parsed_rows:
        assert "period_start" not in row.payload
        assert "period_end" not in row.payload

    first, second = parsed.parsed_rows[0], parsed.parsed_rows[1]
    assert first.source_row_numbers == [6]
    assert first.source_sku == "ЮП-2616"
    assert second.source_row_numbers == [7]
    assert second.source_sku == "ЮП-2604"
    for row in (first, second):
        assert row.quantity == 300
        assert row.payload["paired_profile"] is False
        assert [component["sku"] for component in row.payload["components"]] == [row.source_sku]
        assert row.payload["raw_columns_meta"][0]["index"] == 1
        assert row.payload["raw_columns_meta"][0]["letter"] == "A"
        assert row.payload["raw_columns_meta"][0]["header"] == "Артикул"
        assert row.payload["raw_columns_meta"][7]["index"] == 8
        assert row.payload["raw_columns_meta"][7]["letter"] == "H"
        assert row.payload["raw_columns_meta"][7]["header"] == "Пробивка/сверловка"

    # Строка того же SKU без собственного входа — ещё один выход той же
    # операции (ADR-0003): группа строк 8-9 = одна позиция.
    group = parsed.parsed_rows[2]
    assert group.source_row_numbers == [8, 9]
    assert group.source_ref == "rows:8-9"
    assert group.source_name == "Стык 38 мм. 2,7 анод.серебро, матовый"
    assert group.quantity == 2400
    assert group.input_quantity == 1100
    assert group.input_dimensions == {"length_mm": 2700}
    assert [(o["quantity"], o["dimensions"]) for o in group.outputs] == [
        ("1500", {"length_mm": 900}),
        ("900", {"length_mm": 1800}),
    ]
    # Баланс группы сходится: 1100×2700 = 1500×900 + 900×1800.
    assert not any(w.startswith("plan_group_balance_mismatch") for w in group.warnings)


_CUT_GROUP_HEADERS = [
    "Артикул",
    "пополнение",
    "Наименование",
    "остатки сырья на КТМ",
    "Цвет",
    "кол-во шт. в 2,7",
    "Длина, м",
    "Пробивка/сверловка",
    "Упаковка",
    "Примечание ",
    "Длина после упак, м",
    "кол-во штук готовой продукции",
    "Запад",
    "Восток",
    "Вид конечного продукта",
    "Комментарии",
]


def _cut_group_workbook(data_rows: list[list]) -> bytes:
    """Лист упаковочной карты с раскладкой строк 56–57 реального файла (#279)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "План февраль 26 02"
    ws.append(["", "", "Комментарий"])
    ws.append(["Заявка № 02", "февраль"])
    ws.append([])
    ws.append(["", "", "", "", "", "", "", "", "", "", "", "", "Формирование ящиков"])
    ws.append(_CUT_GROUP_HEADERS)
    for row in data_rows:
        ws.append(row)
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def test_continuation_with_filled_input_length_joins_group() -> None:
    """#279: «Длина, м» заполнена у продолжения, но количества нет — та же группа.

    Реальная раскладка строк 56–57 листа «План февраль 26 02»: ЮП-2630 титан,
    100 шт в 2,7 → выходы 0,9 и 1,8. Раньше строка 57 с заполненной длиной
    входа становилась второй позицией без наименования.
    """
    parsed = parse_factory_plan_workbook(
        _cut_group_workbook(
            [
                ["ЮП-2630", "ТЗ", "Кант 47мм 2,7 титан", 5000, "титан", 100, 2.7, "", "", "", 0.9, 100, "", "", "П/ф"],
                ["ЮП-2630", None, None, None, None, None, 2.7, "", "", "", 1.8, 100, "", "", "ГП"],
            ]
        ),
        "plan.xlsx",
    )

    assert [row.source_sku for row in parsed.parsed_rows] == ["ЮП-2630"]
    group = parsed.parsed_rows[0]
    assert group.source_row_numbers == [6, 7]
    assert group.source_ref == "rows:6-7"
    assert group.input_quantity == 100
    assert group.input_dimensions == {"length_mm": 2700}
    assert [(o["quantity"], o["dimensions"]) for o in group.outputs] == [
        ("100", {"length_mm": 900}),
        ("100", {"length_mm": 1800}),
    ]
    assert "product_name_missing" not in group.warnings
    # Баланс сходится: 100×2700 = 100×900 + 100×1800.
    assert not any(w.startswith("plan_group_balance_mismatch") for w in group.warnings)


def test_continuation_with_empty_input_length_joins_group() -> None:
    """#279: вторая форма продолжения (ЮП-081) — обе входные ячейки пусты."""
    parsed = parse_factory_plan_workbook(
        _cut_group_workbook(
            [
                ["ЮП-081", "ТЗ", "Стык 38мм 2,7 серебро", 4000, "серебро", 160, 2.7, "", "", "", 0.9, 160, "", "", "П/ф"],
                ["ЮП-081", None, None, None, None, None, None, "", "", "", 1.8, 160, "", "", "ГП"],
            ]
        ),
        "plan.xlsx",
    )

    assert [row.source_sku for row in parsed.parsed_rows] == ["ЮП-081"]
    group = parsed.parsed_rows[0]
    assert group.source_row_numbers == [6, 7]
    assert group.input_quantity == 160
    assert group.input_dimensions == {"length_mm": 2700}
    assert [(o["quantity"], o["dimensions"]) for o in group.outputs] == [
        ("160", {"length_mm": 900}),
        ("160", {"length_mm": 1800}),
    ]
    assert "product_name_missing" not in group.warnings


def test_adjacent_same_sku_with_own_input_quantity_stays_separate_row() -> None:
    """#279, граница: своё входное количество у соседней строки — отдельная позиция."""
    parsed = parse_factory_plan_workbook(
        _cut_group_workbook(
            [
                ["ЮП-2630", "ТЗ", "Кант 47мм 2,7 титан", 5000, "титан", 100, 2.7, "", "", "", 0.9, 100, "", "", "П/ф"],
                ["ЮП-2630", "ТЗ", "Кант 47мм 2,7 титан", 5000, "титан", 120, 2.7, "", "", "", 1.8, 120, "", "", "ГП"],
            ]
        ),
        "plan.xlsx",
    )

    assert [row.source_row_numbers for row in parsed.parsed_rows] == [[6], [7]]
    assert [row.input_quantity for row in parsed.parsed_rows] == [100, 120]


def test_continuation_with_mismatched_input_length_stays_separate_row() -> None:
    """#279, граница: длина входа продолжения не равна входу группы — своя позиция."""
    parsed = parse_factory_plan_workbook(
        _cut_group_workbook(
            [
                ["ЮП-2630", "ТЗ", "Кант 47мм 2,7 титан", 5000, "титан", 100, 2.7, "", "", "", 0.9, 100, "", "", "П/ф"],
                ["ЮП-2630", None, None, None, None, None, 2.0, "", "", "", 1.8, 100, "", "", "ГП"],
            ]
        ),
        "plan.xlsx",
    )

    assert [row.source_row_numbers for row in parsed.parsed_rows] == [[6], [7]]


def test_parse_row_selection_csv_and_ranges() -> None:
    assert parse_row_selection("5") == {5}
    assert parse_row_selection("5,7,9") == {5, 7, 9}
    assert parse_row_selection("5-8") == {5, 6, 7, 8}
    assert parse_row_selection("5,7-9") == {5, 7, 8, 9}
    assert parse_row_selection("5, 7, 7, 9-10") == {5, 7, 9, 10}


@pytest.mark.parametrize("value", ["", "7-", "a", "15-12", "5,,7", "-1", "0"])
def test_parse_row_selection_invalid(value: str) -> None:
    with pytest.raises(ValueError):
        parse_row_selection(value)


def test_factory_plan_parser_row_selection_keeps_only_selected_pair_row() -> None:
    """Строки 6 и 7 — разные позиции, выбор строки тянет только её (#312)."""
    parsed = parse_factory_plan_workbook(_workbook_bytes(), "plan.xlsx", row_selection="6")
    assert len(parsed.parsed_rows) == 1
    row = parsed.parsed_rows[0]
    assert row.source_row_numbers == [6]
    assert row.source_sku == "ЮП-2616"
    assert not any(w.startswith("paired_row_auto_included:") for w in row.warnings)
    assert parsed.selected_row_numbers == [6]
    assert parsed.auto_included_row_numbers is None


@pytest.mark.asyncio
async def test_import_excel_creates_batch_and_change_set(client, session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))
    template = await _create_template(session, name="Base Template", code="base-template")
    await session.commit()

    response = await client.post(
        f"/api/imports/excel?template_id={template.id}",
        files={
            "file": (
                "plan.xlsx",
                _workbook_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 201
    body = response.json()
    # Пара больше не склеивается (#312): строки 6 и 7 дают две позиции,
    # плюс группа 8-9 — третья.
    assert body["summary"]["total_positions"] == 3
    assert body["summary"]["paired_profile_positions"] == 0
    assert len(body["items"]) == 3
    assert [item["source_sku"] for item in body["items"]] == ["ЮП-2616", "ЮП-2604", "ЮП-2083"]
    # ЮП-2616/ЮП-2604 не заведены в справочнике сырья тестовой БД.
    assert "product_not_found" in body["items"][0]["codes"]
    assert "product_not_found" in body["items"][1]["codes"]
    # ЮП-2083 not seeded in tests, so product_not_found is expected
    assert "product_not_found" in body["items"][2]["codes"]
    # Полный after_data — лениво, одной строкой (§4.3)
    full = (await client.get(f"/api/imports/items/{body['items'][0]['item_id']}?full=1")).json()
    assert full["after_data"]["source_sku"] == "ЮП-2616"
    assert full["after_data"]["has_pack_ops"] is False
    assert full["after_data"]["source_payload"]["paired_profile"] is False

    assert await session.get(ImportFile, body["import_file_id"]) is not None
    assert await session.get(ImportBatch, body["import_batch_id"]) is not None
    assert await session.get(ProductionPlan, body["production_plan_id"]) is not None
    assert await session.get(PlanChangeSet, body["change_set_id"]) is not None

    change_items = body["items"]
    assert await session.get(PlanChangeItem, change_items[0]["item_id"]) is not None

@pytest.mark.asyncio
async def test_import_excel_returns_light_items_and_summary(client, session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))
    template = await _create_template(session, name="Light Template", code="light-template")
    await session.commit()

    response = await client.post(
        f"/api/imports/excel?template_id={template.id}",
        files={
            "file": (
                "plan.xlsx",
                _workbook_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 201
    body = response.json()

    summary = body["summary"]
    assert summary["total"] == len(body["items"]) == 3
    assert summary["valid"] + summary["warning"] + summary["invalid"] == summary["total"]
    assert summary["invalid"] == 3
    assert summary["duplicates"] == 0
    assert summary["errors"]["product_not_found"] == 3

    for item in body["items"]:
        assert "after_data" not in item
        assert set(item) >= {
            "item_id",
            "source_row_numbers",
            "source_sku",
            "quantity",
            "status",
            "change_action",
            "codes",
        }
    by_sku = {item["source_sku"]: item for item in body["items"]}
    assert by_sku["ЮП-2616"]["codes"] == [
        "product_not_found",
        "no_route_candidate",
        "hanger_quantity_not_set:продукт не найден",
    ]
    # У ЮП-2604 в листе нет наименования: это своя позиция, и собственное
    # предупреждение строки больше не снимается склейкой пары.
    assert by_sku["ЮП-2604"]["codes"] == [
        "product_not_found",
        "no_route_candidate",
        "product_name_missing",
        "hanger_quantity_not_set:продукт не найден",
    ]


@pytest.mark.asyncio
async def test_import_summary_counts_intra_import_duplicates(client, session, tmp_path, monkeypatch) -> None:
    """Две одинаковые строки — внутриимпортный дубль: summary.duplicates считает их
    (спека §4.3), иначе серверный чип «Дубли» в диалоге расходится с таблицей."""
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))
    template = await _create_template(session, name="Dup Template", code="dup-template")
    await session.commit()

    wb = Workbook()
    ws = wb.active
    ws.title = "План"
    ws.append(
        [
            "Артикул",
            "пополнение",
            "Наименование",
            "остатки сырья на КТМ",
            "Цвет",
            "кол-во шт. в 2,7",
            "Длина, м",
            "Пробивка/сверловка",
            "Упаковка",
            "Примечание ",
            "Длина после упак, м",
            "кол-во штук готовой продукции",
            "Запад",
            "Восток",
            "Вид конечного продукта",
            "Комментарии",
            "",
            "",
            "Упаковка в 1,8",
            "добавить",
        ]
    )
    for _ in range(2):
        ws.append(["FG-DUP", "ТЗ", "Дубль", 0, "", 100, 2.7, "", "", "", 2.7, 100, "", 100, "ГП"])
    out = BytesIO()
    wb.save(out)

    response = await client.post(
        f"/api/imports/excel?template_id={template.id}",
        files={
            "file": (
                "dup.xlsx",
                out.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 201
    body = response.json()

    assert body["summary"]["duplicates"] == 2
    assert body["summary"]["errors"]["duplicate_sku_due_date"] == 2
    for item in body["items"]:
        assert "duplicate_sku_due_date" in item["codes"]
        assert item["status"] == "invalid"


@pytest.mark.asyncio
async def test_preview_excel_resolves_paired_profile_when_pair_exists(
    client, session, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    template = await _create_template(session, name="Preview Pair Template", code="preview-pair-template")
    await _make_product_pair(
        session,
        "ЮП-2616",
        "ЮП-2604",
        manual_n=8,
        length={"length_mm": 2700, "is_primary": True},
    )
    await session.commit()

    response = await client.post(
        f"/api/imports/excel/preview?template_id={template.id}",
        files={
            "file": (
                "plan.xlsx",
                _workbook_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    # Пара не склеена: две позиции, у каждой своя N — парная (#312).
    assert [item["source_sku"] for item in body["items"]] == ["ЮП-2616", "ЮП-2604", "ЮП-2083"]
    for item in body["items"][:2]:
        assert "paired_profile_product_unmapped" not in item["warnings"]
        assert item["after_data"]["quantity_per_hanger"] == 8, item["source_sku"]
        assert item["after_data"]["hanger_source"] == "manual"
        assert item["after_data"]["source_payload"]["paired_profile"] is False


@pytest.mark.asyncio
async def test_apply_paired_import_does_not_cache_hanger_override(
    client, session, tmp_path, monkeypatch
) -> None:
    """Импортная N пары не кэшируется как override: позиция читает снапшот."""
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    await _make_product_pair(
        session,
        "ЮП-PAIR-A",
        "ЮП-PAIR-B",
        manual_n=8,
        length={"length_mm": 2700, "is_primary": True},
    )
    template = await _create_template(session, name="Paired Apply Template", code="paired-apply-template")
    await session.commit()

    response = await client.post(
        f"/api/imports/excel?template_id={template.id}",
        data={"normalize_hanger_quantity": "true"},
        files={"file": ("paired.xlsx", _workbook_paired(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    applied = await client.post(
        f"/api/production-plans/{body['production_plan_id']}/change-sets/{body['change_set_id']}/apply"
    )
    assert applied.status_code == 200, applied.text

    positions = (
        await client.get(f"/api/production-plans/{body['production_plan_id']}/all-positions")
    ).json()
    paired_position = positions[0]
    # В payload нет импортной N — она не override; норма приходит из снапшота пары.
    assert "quantity_per_hanger" not in (paired_position["payload"] or {})
    assert paired_position["quantity_per_hanger"] == 8
    assert paired_position["quantity_per_hanger_source"] == "manual"


@pytest.mark.asyncio
async def test_import_excel_with_row_selection_takes_only_selected_pair_row(
    client, session, tmp_path, monkeypatch
) -> None:
    """Выбор строки пары не тянет вторую: это отдельная позиция (#312)."""
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))
    template = await _create_template(session, name="Rows Template", code="rows-template")
    await session.commit()

    response = await client.post(
        f"/api/imports/excel?template_id={template.id}",
        data={"row_selection": "6"},
        files={
            "file": (
                "plan.xlsx",
                _workbook_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["summary"]["total_positions"] == 1
    assert body["summary"]["row_selection"] == "6"
    assert body["summary"]["selected_row_numbers"] == [6]
    assert not body["summary"]["auto_included_row_numbers"]
    assert body["items"][0]["source_sku"] == "ЮП-2616"
    assert not any(w.startswith("paired_row_auto_included:") for w in body["items"][0]["codes"])


@pytest.mark.asyncio
async def test_import_excel_with_invalid_row_selection_returns_400(client, session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))
    template = await _create_template(session, name="Invalid Rows Template", code="invalid-rows-template")
    await session.commit()

    response = await client.post(
        f"/api/imports/excel?template_id={template.id}",
        data={"row_selection": "15-12"},
        files={
            "file": (
                "plan.xlsx",
                _workbook_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 400
    assert "row range" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_import_excel_requires_template_id(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    response = await client.post(
        "/api/imports/excel",
        files={
            "file": (
                "plan.xlsx",
                _workbook_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Поле template_id обязательно"


def test_factory_plan_parser_with_custom_mapping() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Custom Plan"
    ws.append(["SKU", "Name", "Qty", "Deadline", "Client", "Priority", "Order"])
    ws.append(["ABC-123", "Test Product", 50, "2026-06-15", "ClientA", 1, "ORD-001"])
    out = BytesIO()
    wb.save(out)
    content = out.getvalue()

    custom_mapping = {
        "sku": "SKU",
        "product_name": "Name",
        "quantity": "Qty",
        "due_date": "Deadline",
        "customer": "Client",
        "priority": "Priority",
        "order_ref": "Order",
    }
    parsed = parse_factory_plan_workbook(content, "custom.xlsx", column_mapping=custom_mapping)

    assert len(parsed.parsed_rows) == 1
    row = parsed.parsed_rows[0]
    assert row.source_sku == "ABC-123"
    assert row.source_name == "Test Product"
    assert row.quantity == 50
    assert row.payload["due_date"] == "2026-06-15"
    assert row.payload["customer"] == "ClientA"
    assert row.payload["priority"] == 1
    assert row.payload["order_ref"] == "ORD-001"


def test_factory_plan_parser_extracts_color_from_product_name_when_color_empty() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "План май 26 05"
    ws.append(["", "", "Комментарий"])
    ws.append(["Заявка № 05", "май"])
    ws.append([])
    ws.append(["", "", "", "", "", "", "", "", "", "", "", "", "Формирование ящиков"])
    ws.append(
        [
            "Артикул",
            "пополнение",
            "Наименование",
            "остатки сырья на КТМ",
            "Цвет",
            "кол-во шт. в 2,7",
            "Длина, м",
            "Пробивка/сверловка",
            "Упаковка",
            "Примечание",
            "Длина после упак, м",
            "кол-во штук готовой продукции",
            "Вид конечного продукта",
        ]
    )
    ws.append(
        [
            "ХТ-466-3776",
            "",
            "РП-АКТ-03 2,7 м анодчерный матов",
            "",
            "",
            100,
            2.7,
            "",
            "",
            "",
            "",
            100,
            "ГП",
        ]
    )
    out = BytesIO()
    wb.save(out)
    parsed = parse_factory_plan_workbook(out.getvalue(), "anod-color.xlsx")

    assert len(parsed.parsed_rows) == 1
    row = parsed.parsed_rows[0]
    assert row.payload["color"] == "черный"
    assert row.payload["source_name"] == "РП-АКТ-03 2,7 м анодчерный матов"


def test_factory_plan_parser_preserves_raw_operation_and_output_kind() -> None:
    """Normalization is handled by route selection rules now; parser only preserves raw values."""
    wb = Workbook()
    ws = wb.active
    ws.title = "План май 26 05"
    ws.append(["", "", "Комментарий"])
    ws.append(["Заявка № 05", "май"])
    ws.append([])
    ws.append(["", "", "", "", "", "", "", "", "", "", "", "", "Формирование ящиков"])
    ws.append(
        [
            "Артикул",
            "пополнение",
            "Наименование",
            "остатки сырья на КТМ",
            "Цвет",
            "кол-во шт. в 2,7",
            "Длина, м",
            "Пробивка/сверловка",
            "Упаковка",
            "Примечание ",
            "Длина после упак, м",
            "кол-во штук готовой продукции",
            "Запад",
            "Восток",
            "Вид конечного продукта",
            "Комментарии",
        ]
    )
    ws.append(["SKU-GLUE", "", "Glue Profile", 0, "", 100, 2.7, "клей", "поф", "", 2.7, 100, "", 100, "ГП", ""])
    ws.append(["SKU-DIFF", "", "Diffuser Profile", 0, "", 200, 2.7, "рассеиватель", "поф", "", 2.7, 200, "", 200, "ГП", ""])
    ws.append(["SKU-NODIFF", "", "No Diffuser Profile", 0, "", 50, 2.7, "Без рассеивателя", "поф", "", 2.7, 50, "", 50, "П/ф", ""])
    out = BytesIO()
    wb.save(out)

    parsed = parse_factory_plan_workbook(
        out.getvalue(),
        "pack_ops.xlsx",
    )
    assert len(parsed.parsed_rows) == 3

    # operation_code/operation_name/additional_pack_operations are now determined by selection rules
    glue = parsed.parsed_rows[0].payload
    assert glue["operation_code"] is None
    assert glue["operation_name"] is None
    assert glue["additional_pack_operations"] == []
    assert glue["operation"] == "клей"
    assert glue["output_kind"] == "ГП"
    assert glue["output_kind_raw"] == "ГП"

    diffuser = parsed.parsed_rows[1].payload
    assert diffuser["operation_code"] is None
    assert diffuser["operation"] == "рассеиватель"
    assert diffuser["output_kind"] == "ГП"

    no_diff = parsed.parsed_rows[2].payload
    assert no_diff["operation_code"] is None
    assert no_diff["operation"] == "Без рассеивателя"
    assert no_diff["output_kind"] == "П/ф"


from datetime import date, datetime

from app.services.excel_import import _excel_date_to_date, _parse_date


def test_date_normalization() -> None:
    assert _parse_date(date(2026, 5, 2)) == date(2026, 5, 2)
    assert _parse_date(datetime(2026, 5, 2, 14, 30)) == date(2026, 5, 2)  # noqa: DTZ001 — наивный datetime как значение ячейки Excel: парсер нормализует его в дату
    assert _parse_date("2026-05-02") == date(2026, 5, 2)
    assert _parse_date("02.05.2026") == date(2026, 5, 2)
    assert _excel_date_to_date(1) == date(1899, 12, 31)
    assert _parse_date(44561) == date(2021, 12, 31)
    assert _parse_date("invalid") is None
    assert _parse_date(None) is None


@pytest.mark.asyncio
async def test_replace_draft_mode_creates_cancel_for_missing_rows(client, session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    from app.models.product import Product, ProductLength, ProductType
    from app.models.route import ProductionRoute, RouteOperation, RouteStage
    from app.models.section import Section



    product = Product(sku="FG-TEST", name="Test Product", type=ProductType.finished_good, unit="pcs")
    component = Product(sku="FG-TEST-RAW", name="Test Raw", type=ProductType.component, unit="pcs")
    sections = [
        Section(code="CUT", name="Cut"),
        Section(code="PACKING", name="Pack"),
    ]
    session.add_all([product, component, *sections])
    await session.flush()
    session.add(ProductLength(product_id=product.id, length_mm=2700, is_primary=True))
    await session.flush()


    route = ProductionRoute(name="Main", is_active=True)
    session.add(route)
    await session.flush()
    for index, section in enumerate(sections, start=1):
        stage = RouteStage(
            route_id=route.id,
            sequence=index * 10,
            section_id=section.id,
            is_final=index == len(sections),
        )
        session.add(stage)
        await session.flush()
        session.add(
            RouteOperation(
                route_stage_id=stage.id,
                sequence=1,
                operation_name=f"Step {index}",
            )
        )
    await session.commit()

    def _make_workbook(rows: list[tuple[str, str, int]]) -> bytes:
        wb = Workbook()
        ws = wb.active
        ws.title = "План май 26 05"
        ws.append(["", "", "Комментарий"])
        ws.append(["Заявка № 05", "май"])
        ws.append([])
        ws.append(["", "", "", "", "", "", "", "", "", "", "", "", "Формирование ящиков"])
        ws.append(
            [
                "Артикул",
                "пополнение",
                "Наименование",
                "остатки сырья на КТМ",
                "Цвет",
                "кол-во шт. в 2,7",
                "Длина, м",
                "Пробивка/сверловка",
                "Упаковка",
                "Примечание ",
                "Длина после упак, м",
                "кол-во штук готовой продукции",
                "Запад",
                "Восток",
                "Вид конечного продукта",
                "Комментарии",
                "",
                "",
                "Упаковка в 1,8",
                "добавить",
            ]
        )
        for sku, name, qty in rows:
            ws.append([sku, "ТЗ", name, 0, "", qty, 2.7, "", "", "", 2.7, qty, "", qty, "ГП"])
        out = BytesIO()
        wb.save(out)
        return out.getvalue()

    # First import with 2 rows
    template = await _create_template(session, name="Replace Template", code="replace-template")
    await session.commit()
    wb1 = _make_workbook([("FG-TEST", "Test Product", 100), ("FG-TEST", "Test Product", 200)])
    response1 = await client.post(
        f"/api/imports/excel?template_id={template.id}",
        files={"file": ("plan1.xlsx", wb1, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response1.status_code == 201
    body1 = response1.json()
    plan_id = body1["production_plan_id"]
    change_set_id1 = body1["change_set_id"]

    apply1 = await client.post(f"/api/production-plans/{plan_id}/change-sets/{change_set_id1}/apply")
    assert apply1.status_code == 200
    assert apply1.json()["created_positions"] == 2

    # Second import with 1 row (replace mode)
    wb2 = _make_workbook([("FG-TEST", "Test Product", 100)])
    response2 = await client.post(
        f"/api/imports/excel?template_id={template.id}",
        data={"mode": "replace_draft_from_same_source", "production_plan_id": str(plan_id)},
        files={"file": ("plan2.xlsx", wb2, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response2.status_code == 201
    body2 = response2.json()
    actions = [item["change_action"] for item in body2["items"]]
    assert "cancel_draft_position" in actions

    await assert_no_invariants_violations(session, context="import replace-draft apply")


@pytest.mark.asyncio
async def test_import_excel_resolves_profile_by_template_priority(client, session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    template = ImportTemplate(
        name="Template with Profiles",
        code="template-profiles",
        is_active=True,
        column_mapping={"sku": {"header": "Артикул", "column": "A"}},
    )
    session.add(template)
    await session.flush()

    low_active = RouteRuleProfile(
        code="profile-low-active",
        name="Profile low active",
        is_active=True,
        priority=10,
        import_template_id=template.id,
    )
    high_inactive = RouteRuleProfile(
        code="profile-high-inactive",
        name="Profile high inactive",
        is_active=False,
        priority=999,
        import_template_id=template.id,
    )
    high_active = RouteRuleProfile(
        code="profile-high-active",
        name="Profile high active",
        is_active=True,
        priority=20,
        import_template_id=template.id,
    )
    session.add_all([low_active, high_inactive, high_active])
    await session.commit()

    response = await client.post(
        f"/api/imports/excel?template_id={template.id}",
        files={
            "file": (
                "plan.xlsx",
                _workbook_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["template_id"] == template.id
    assert body["rule_profile_id"] == high_active.id


@pytest.mark.asyncio
async def test_import_excel_template_without_profile_uses_fallback(client, session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    template = ImportTemplate(
        name="Template without profile",
        code="template-no-profile",
        is_active=True,
        column_mapping={"sku": {"header": "Артикул", "column": "A"}},
    )
    session.add(template)
    await session.commit()

    response = await client.post(
        f"/api/imports/excel?template_id={template.id}",
        files={
            "file": (
                "plan.xlsx",
                _workbook_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["template_id"] == template.id
    assert body["rule_profile_id"] is None


@pytest.mark.asyncio
async def test_preview_excel_uses_template_profile_for_rule_selection(client, session, monkeypatch) -> None:
    template = ImportTemplate(
        name="Template preview profile",
        code="template-preview-profile",
        is_active=True,
        column_mapping={"sku": {"header": "Артикул", "column": "A"}},
    )
    session.add(template)
    await session.flush()

    low_active = RouteRuleProfile(
        code="preview-profile-low",
        name="Preview profile low",
        is_active=True,
        priority=10,
        import_template_id=template.id,
    )
    high_inactive = RouteRuleProfile(
        code="preview-profile-high-inactive",
        name="Preview profile high inactive",
        is_active=False,
        priority=999,
        import_template_id=template.id,
    )
    high_active = RouteRuleProfile(
        code="preview-profile-high-active",
        name="Preview profile high active",
        is_active=True,
        priority=20,
        import_template_id=template.id,
    )
    session.add_all([low_active, high_inactive, high_active])
    await session.commit()

    captured: dict[str, int | None] = {"rule_profile_id": None}

    async def _fake_preview_excel_sheet(_db, **kwargs):
        captured["rule_profile_id"] = kwargs.get("rule_profile_id")
        return {
            "sheet_name": "test",
            "header_row_number": 1,
            "total_rows": 0,
            "summary": {},
            "items": [],
        }

    monkeypatch.setattr("app.services.plan_import_service.preview_excel_sheet", _fake_preview_excel_sheet)

    response = await client.post(
        f"/api/imports/excel/preview?template_id={template.id}",
        files={
            "file": (
                "plan.xlsx",
                _workbook_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    assert captured["rule_profile_id"] == high_active.id


# ─────────────────────────────────────────────────────────────
# Tests for hanger quantity rounding (normalize_hanger_quantity)
# ─────────────────────────────────────────────────────────────

def _workbook_with_quantity(
    sku: str, name: str, quantity: int, *, output_length_m: float = 2.7, length_m: float = 2.7
) -> bytes:
    """Создаёт минимальный Excel с одной строкой плана.

    ``output_length_m`` меньше 2,7 — кейс резки (вход 2,7 м → выход короче).
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "План май 26 05"
    ws.append(["", "", "Комментарий"])
    ws.append(["Заявка № 05", "май"])
    ws.append([])
    ws.append(["", "", "", "", "", "", "", "", "", "", "", "", "Формирование ящиков"])
    ws.append(
        [
            "Артикул",
            "пополнение",
            "Наименование",
            "остатки сырья на КТМ",
            "Цвет",
            "кол-во шт. в 2,7",
            "Длина, м",
            "Пробивка/сверловка",
            "Упаковка",
            "Примечание ",
            "Длина после упак, м",
            "кол-во штук готовой продукции",
            "Запад",
            "Восток",
            "Вид конечного продукта",
            "Комментарии",
        ]
    )
    ws.append([sku, "ТЗ", name, 0, "", quantity, length_m, "", "", "", output_length_m, quantity, "", quantity, "ГП"])
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


@pytest.mark.asyncio
async def test_import_with_normalize_hanger_quantity_rounds_up(
    client, session, tmp_path, monkeypatch
) -> None:
    """Импорт с normalize_hanger_quantity=True округляет количество вверх."""
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    from app.models.product import Product, ProductType
    from app.models.route import ProductionRoute, RouteOperation, RouteStage
    from app.models.section import Section

    product = Product(sku="FG-TEST", name="Test Product", type=ProductType.finished_good, unit="pcs", quantity_per_hanger=5, hanger_mode="manual")
    component = Product(sku="FG-TEST-RAW", name="Test Raw", type=ProductType.component, unit="pcs")
    sections = [Section(code="CUT", name="Cut"), Section(code="PACKING", name="Pack")]
    session.add_all([product, component, *sections])
    await session.flush()


    route = ProductionRoute(name="Main", is_active=True)
    session.add(route)
    await session.flush()
    for index, section in enumerate(sections, start=1):
        stage = RouteStage(
            route_id=route.id,
            sequence=index * 10,
            section_id=section.id,
            is_final=index == len(sections),
        )
        session.add(stage)
        await session.flush()
        session.add(
            RouteOperation(
                route_stage_id=stage.id,
                sequence=1,
                operation_name=f"Step {index}",
            )
        )
    await session.commit()

    template = await _create_template(session, name="Hanger Template", code="hanger-template")
    await session.commit()

    # Количество 12, на подвес 5 → должно округлиться до 15
    wb = _workbook_with_quantity("FG-TEST", "Test Product", 12)
    response = await client.post(
        f"/api/imports/excel?template_id={template.id}",
        data={"normalize_hanger_quantity": "true"},
        files={"file": ("plan.xlsx", wb, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 201
    body = response.json()
    item = (await client.get(f"/api/imports/items/{body['items'][0]['item_id']}?full=1")).json()

    # Проверяем что количество округлено (Decimal строки)
    assert item["after_data"]["quantity"] == "15"
    assert item["after_data"]["original_quantity"] in ("12", "12.0")

    # Проверяем что есть hanger_count и quantity_per_hanger
    assert item["after_data"]["quantity_per_hanger"] == 5
    assert item["after_data"]["hanger_count"] == 3

    # Нет warning о округлении (это нормальное поведение, не warning)
    assert not any("hanger_quantity_adjusted" in w for w in item["warnings"])

    # Проверяем summary (Decimal строки)
    assert body["summary"]["quantity_total"] in ("12", "12.0")
    # quantity_adjusted_total добавляется на верхний уровень ответа
    assert body["quantity_adjusted_total"] == "15"


@pytest.mark.asyncio
async def test_import_without_normalize_hanger_quantity_keeps_original(
    client, session, tmp_path, monkeypatch
) -> None:
    """Импорт с normalize_hanger_quantity=False сохраняет оригинальное количество."""
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    from app.models.product import Product, ProductType
    from app.models.route import ProductionRoute, RouteOperation, RouteStage
    from app.models.section import Section

    product = Product(sku="FG-TEST", name="Test Product", type=ProductType.finished_good, unit="pcs", quantity_per_hanger=5, hanger_mode="manual")
    component = Product(sku="FG-TEST-RAW", name="Test Raw", type=ProductType.component, unit="pcs")
    sections = [Section(code="CUT", name="Cut"), Section(code="PACKING", name="Pack")]
    session.add_all([product, component, *sections])
    await session.flush()


    route = ProductionRoute(name="Main", is_active=True)
    session.add(route)
    await session.flush()
    for index, section in enumerate(sections, start=1):
        stage = RouteStage(
            route_id=route.id,
            sequence=index * 10,
            section_id=section.id,
            is_final=index == len(sections),
        )
        session.add(stage)
        await session.flush()
        session.add(
            RouteOperation(
                route_stage_id=stage.id,
                sequence=1,
                operation_name=f"Step {index}",
            )
        )
    await session.commit()

    template = await _create_template(session, name="No Hanger Template", code="no-hanger-template")
    await session.commit()

    wb = _workbook_with_quantity("FG-TEST", "Test Product", 12)
    response = await client.post(
        f"/api/imports/excel?template_id={template.id}",
        data={"normalize_hanger_quantity": "false"},
        files={"file": ("plan.xlsx", wb, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 201
    body = response.json()
    item = (await client.get(f"/api/imports/items/{body['items'][0]['item_id']}?full=1")).json()

    # Количество не округлено (Decimal строки)
    assert item["after_data"]["quantity"] in ("12", "12.0")
    assert item["after_data"]["original_quantity"] in ("12", "12.0")

    # Нет warning о округлении
    assert not any("hanger_quantity_adjusted" in w for w in item["warnings"])


@pytest.mark.asyncio
async def test_import_product_without_quantity_per_hanger_shows_warning(
    client, session, tmp_path, monkeypatch
) -> None:
    """Продукт без quantity_per_hanger получает warning но количество не меняется."""
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    from app.models.product import Product, ProductType
    from app.models.route import ProductionRoute, RouteOperation, RouteStage
    from app.models.section import Section

    # Продукт БЕЗ quantity_per_hanger
    product = Product(sku="FG-TEST", name="Test Product", type=ProductType.finished_good, unit="pcs")
    component = Product(sku="FG-TEST-RAW", name="Test Raw", type=ProductType.component, unit="pcs")
    sections = [Section(code="CUT", name="Cut"), Section(code="PACKING", name="Pack")]
    session.add_all([product, component, *sections])
    await session.flush()


    route = ProductionRoute(name="Main", is_active=True)
    session.add(route)
    await session.flush()
    for index, section in enumerate(sections, start=1):
        stage = RouteStage(
            route_id=route.id,
            sequence=index * 10,
            section_id=section.id,
            is_final=index == len(sections),
        )
        session.add(stage)
        await session.flush()
        session.add(
            RouteOperation(
                route_stage_id=stage.id,
                sequence=1,
                operation_name=f"Step {index}",
            )
        )
    await session.commit()

    template = await _create_template(session, name="No Hanger Value Template", code="no-hanger-value-template")
    await session.commit()

    wb = _workbook_with_quantity("FG-TEST", "Test Product", 12)
    response = await client.post(
        f"/api/imports/excel?template_id={template.id}",
        data={"normalize_hanger_quantity": "true"},
        files={"file": ("plan.xlsx", wb, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 201
    body = response.json()
    item = (await client.get(f"/api/imports/items/{body['items'][0]['item_id']}?full=1")).json()

    # Количество не изменилось (Decimal строки)
    assert item["after_data"]["quantity"] in ("12", "12.0")
    assert item["after_data"]["original_quantity"] in ("12", "12.0")

    # Есть warning что quantity_per_hanger не задан
    assert any("hanger_quantity_not_set" in w for w in item["warnings"])


@pytest.mark.asyncio
async def test_import_already_multiple_no_warning(
    client, session, tmp_path, monkeypatch
) -> None:
    """Количество уже кратно подвесу — нет warning."""
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    from app.models.product import Product, ProductType
    from app.models.route import ProductionRoute, RouteOperation, RouteStage
    from app.models.section import Section

    product = Product(sku="FG-TEST", name="Test Product", type=ProductType.finished_good, unit="pcs", quantity_per_hanger=5, hanger_mode="manual")
    component = Product(sku="FG-TEST-RAW", name="Test Raw", type=ProductType.component, unit="pcs")
    sections = [Section(code="CUT", name="Cut"), Section(code="PACKING", name="Pack")]
    session.add_all([product, component, *sections])
    await session.flush()


    route = ProductionRoute(name="Main", is_active=True)
    session.add(route)
    await session.flush()
    for index, section in enumerate(sections, start=1):
        stage = RouteStage(
            route_id=route.id,
            sequence=index * 10,
            section_id=section.id,
            is_final=index == len(sections),
        )
        session.add(stage)
        await session.flush()
        session.add(
            RouteOperation(
                route_stage_id=stage.id,
                sequence=1,
                operation_name=f"Step {index}",
            )
        )
    await session.commit()

    template = await _create_template(session, name="Multiple Template", code="multiple-template")
    await session.commit()

    # 15 кратно 5
    wb = _workbook_with_quantity("FG-TEST", "Test Product", 15)
    response = await client.post(
        f"/api/imports/excel?template_id={template.id}",
        data={"normalize_hanger_quantity": "true"},
        files={"file": ("plan.xlsx", wb, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 201
    body = response.json()
    item = (await client.get(f"/api/imports/items/{body['items'][0]['item_id']}?full=1")).json()

    assert item["after_data"]["quantity"] in ("15", "15.0")
    # Нет warning о округлении так как уже кратно
    assert not any("hanger_quantity_adjusted" in w for w in item["warnings"])
    assert not any("hanger_quantity_not_set" in w for w in item["warnings"])


async def _add_single_hanger_product(
    session,
    sku: str,
    *,
    lengths: list[dict] | None = None,
    quantity_per_hanger: dict | None = None,
    hanger_mode: str = "manual",
    perimeter_mm: float | None = None,
    mount_width_mm: float | None = None,
) -> None:
    """Одиночный артикул с каноническим реестром normal/raw длин."""
    from app.models.product import Product, ProductLength, ProductType

    product = Product(sku=sku, name=f"Single {sku}", type=ProductType.component, unit="pcs")
    product.hanger_mode = hanger_mode
    if quantity_per_hanger is not None:
        product.quantity_per_hanger = quantity_per_hanger
    if perimeter_mm is not None:
        product.perimeter_mm = perimeter_mm
    if mount_width_mm is not None:
        product.mount_width_mm = mount_width_mm
    session.add(product)
    await session.flush()
    session.add_all(
        ProductLength(product_id=product.id, **length)
        for length in (lengths or [])
    )
    await session.commit()


@pytest.mark.asyncio
async def test_import_single_manual_norm_keeps_excel_normal_length(
    client, session, tmp_path, monkeypatch
) -> None:
    """Excel 2700 остаётся геометрией плана; N выбирается по 2700, не по primary."""
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    await _add_single_hanger_product(
        session,
        "ЮП-NORM-LEN",
        lengths=[
            {"length_mm": 2700, "raw_length_mm": 2750, "is_primary": False},
            {"length_mm": 3000, "is_primary": True},
        ],
        hanger_mode="manual",
        quantity_per_hanger={
            "2700": {"auto": None, "manual": 5},
            "3000": {"auto": None, "manual": 7},
        },
    )
    template = await _create_template(session, name="Norm Length Template", code="norm-length-template")
    await session.commit()

    wb = _workbook_with_quantity("ЮП-NORM-LEN", "Norm Length", 11)
    response = await client.post(
        f"/api/imports/excel/preview?template_id={template.id}",
        data={"normalize_hanger_quantity": "true"},
        files={"file": ("single.xlsx", wb, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["after_data"]["input_dimensions"] == {"length_mm": 2700}
    assert item["after_data"]["quantity_per_hanger"] == 5
    assert item["after_data"]["quantity"] == "15"
    assert item["after_data"]["hanger_count"] == 3
    assert "normal_length_not_found" not in item["errors"]


@pytest.mark.asyncio
async def test_import_single_missing_normal_norm_keeps_length_and_warns(
    client, session, tmp_path, monkeypatch
) -> None:
    """Отсутствие N для зарегистрированной 2700 не меняет геометрию позиции."""
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    await _add_single_hanger_product(
        session,
        "ЮП-NORM-GAP",
        lengths=[
            {"length_mm": 2700, "raw_length_mm": 2750, "is_primary": True},
            {"length_mm": 3000, "is_primary": False},
        ],
        hanger_mode="manual",
        quantity_per_hanger={"3000": {"auto": None, "manual": 7}},
    )
    template = await _create_template(session, name="Norm Gap Template", code="norm-gap-template")
    await session.commit()

    wb = _workbook_with_quantity("ЮП-NORM-GAP", "Norm Gap", 11)
    response = await client.post(
        f"/api/imports/excel/preview?template_id={template.id}",
        data={"normalize_hanger_quantity": "true"},
        files={"file": ("single.xlsx", wb, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["after_data"]["input_dimensions"] == {"length_mm": 2700}
    assert item["after_data"]["quantity_per_hanger"] is None
    assert item["after_data"]["quantity"] == item["after_data"]["original_quantity"]
    assert item["after_data"]["quantity"] in ("11", "11.0")
    assert "hanger_quantity_not_set:2,7" in item["warnings"]




@pytest.mark.asyncio
async def test_import_single_auto_norm_computed_by_raw_length(
    client, session, tmp_path, monkeypatch
) -> None:
    """Auto использует effective raw для формулы, но сохраняет normal в позиции."""
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    await _add_single_hanger_product(
        session,
        "ЮП-NORM-AUTO",
        lengths=[{"length_mm": 3000, "raw_length_mm": 3050, "is_primary": True}],
        hanger_mode="auto",
        quantity_per_hanger={"3000": {"auto": 72, "manual": 71}},
        perimeter_mm=60,
        mount_width_mm=15,
    )
    template = await _create_template(session, name="Norm Auto Template", code="norm-auto-template")
    await session.commit()

    wb = _workbook_with_quantity("ЮП-NORM-AUTO", "Norm Auto", 500, output_length_m=3.0, length_m=3.0)
    response = await client.post(
        f"/api/imports/excel/preview?template_id={template.id}",
        data={"normalize_hanger_quantity": "true"},
        files={"file": ("single.xlsx", wb, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["after_data"]["input_dimensions"] == {"length_mm": 3000}
    assert item["after_data"]["outputs"][0]["dimensions"] == {"length_mm": 3000}
    assert item["after_data"]["quantity_per_hanger"] == 71
    assert item["after_data"]["quantity"] == "568"  # ceil(500/71)*71 = 8*71
    assert item["after_data"]["hanger_count"] == 8


@pytest.mark.asyncio
async def test_import_single_auto_norm_per_length_uses_mode(
    client, session, tmp_path, monkeypatch
) -> None:
    """В auto-режиме сохранённое значение не подменяет формулу по raw."""
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    await _add_single_hanger_product(
        session,
        "ЮП-NORM-AUTO-PL",
        lengths=[{"length_mm": 3000, "is_primary": True}],
        hanger_mode="auto",
        quantity_per_hanger={"3000": {"auto": 72, "manual": 71}},
        perimeter_mm=60,
        mount_width_mm=15,
    )
    template = await _create_template(session, name="Norm Auto Pl Template", code="norm-auto-pl-template")
    await session.commit()

    wb = _workbook_with_quantity("ЮП-NORM-AUTO-PL", "Norm Auto Pl", 500, output_length_m=3.0, length_m=3.0)
    response = await client.post(
        f"/api/imports/excel/preview?template_id={template.id}",
        data={"normalize_hanger_quantity": "true"},
        files={"file": ("single.xlsx", wb, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["after_data"]["input_dimensions"] == {"length_mm": 3000}
    assert item["after_data"]["outputs"][0]["dimensions"] == {"length_mm": 3000}
    assert item["after_data"]["quantity_per_hanger"] == 72
    assert item["after_data"]["quantity"] == "504"
    assert item["after_data"]["hanger_count"] == 7


@pytest.mark.asyncio
async def test_import_single_auto_norm_without_geometry_warns(
    client, session, tmp_path, monkeypatch
) -> None:
    """Auto без геометрии оставляет количество и normal-геометрию без подмены."""
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    await _add_single_hanger_product(
        session,
        "ЮП-NORM-NOGEO",
        lengths=[{"length_mm": 3000, "is_primary": True}],
        hanger_mode="auto",
        quantity_per_hanger={"3000": {"auto": None, "manual": 71}},
    )
    template = await _create_template(session, name="Norm No Geo Template", code="norm-no-geo-template")
    await session.commit()

    wb = _workbook_with_quantity("ЮП-NORM-NOGEO", "Norm No Geo", 500, output_length_m=3.0, length_m=3.0)
    response = await client.post(
        f"/api/imports/excel/preview?template_id={template.id}",
        data={"normalize_hanger_quantity": "true"},
        files={"file": ("single.xlsx", wb, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["after_data"]["input_dimensions"] == {"length_mm": 3000}
    assert item["after_data"]["outputs"][0]["dimensions"] == {"length_mm": 3000}
    assert item["after_data"]["quantity_per_hanger"] is None
    assert item["after_data"]["quantity"] == item["after_data"]["original_quantity"]
    assert item["after_data"]["quantity"] in ("500", "500.0")
    assert "hanger_quantity_not_set:3" in item["warnings"]




def _workbook_paired(length_m: float = 2.7, output_length_m: float | None = None) -> bytes:
    """Создаёт Excel с парой профилей.

    ``output_length_m`` отличается от ``length_m`` в кейсе резки
    («Длина, м» 2,7 → «Длина после упак, м» 0,9).
    """
    out_length = length_m if output_length_m is None else output_length_m
    wb = Workbook()
    ws = wb.active
    ws.title = "План май 26 05"
    ws.append(["", "", "Комментарий"])
    ws.append(["Заявка № 05", "май"])
    ws.append([])
    ws.append(["", "", "", "", "", "", "", "", "", "", "", "", "Формирование ящиков"])
    ws.append(
        [
            "Артикул",
            "пополнение",
            "Наименование",
            "остатки сырья на КТМ",
            "Цвет",
            "кол-во шт. в 2,7",
            "Длина, м",
            "Пробивка/сверловка",
            "Упаковка",
            "Примечание ",
            "Длина после упак, м",
            "кол-во штук готовой продукции",
            "Запад",
            "Восток",
            "Вид конечного продукта",
            "Комментарии",
            "",
            "",
            "Упаковка в 1,8",
            "добавить",
        ]
    )
    # Парная строка 1 и 2 — вторая с пустым name как в оригинале
    ws.append(["ЮП-PAIR-A", "ТЗ", "Paired Profile", 100, "black", 10, length_m, "", "", "", out_length, 10, "", 10, "П/ф"])
    ws.append(["ЮП-PAIR-B", "ТЗ", "", 100, "black", 10, length_m, "", "", "", out_length, 10, "", 10, "П/ф"])
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


async def _make_product_pair(
    session,
    sku_a: str,
    sku_b: str,
    *,
    manual_n: int | None = None,
    length: dict,
    length_b: dict | None = None,
) -> None:
    """Пара артикулов с каноническими реестрами normal/raw длин."""
    from app.models.product import Product, ProductLength, ProductPair, ProductType

    comp_a = Product(sku=sku_a, name=f"Pair {sku_a}", type=ProductType.component, unit="pcs")
    comp_b = Product(sku=sku_b, name=f"Pair {sku_b}", type=ProductType.component, unit="pcs")
    session.add_all([comp_a, comp_b])
    await session.flush()
    session.add_all([
        ProductLength(product_id=comp_a.id, **length),
        ProductLength(product_id=comp_b.id, **(length_b or length)),
    ])
    length_mm = length["length_mm"]
    quantity = {str(int(length_mm)): {"auto": None, "manual": manual_n}} if manual_n is not None else {}
    session.add(ProductPair(
        product_a_id=min(comp_a.id, comp_b.id),
        product_b_id=max(comp_a.id, comp_b.id),
        quantity_per_hanger=quantity,
    ))
    await session.flush()


@pytest.mark.asyncio
async def test_import_pair_components_round_by_pair_manual_n(
    client, session, tmp_path, monkeypatch
) -> None:
    """Обе позиции пары округляются по N пары (#312, #67: инвариант равенства).

    Склейки больше нет: ``ЮП-PAIR-A`` и ``ЮП-PAIR-B`` — две позиции, но
    норма у обеих парная, потому что на подвесе едут оба компонента.
    """
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    await _make_product_pair(
        session,
        "ЮП-PAIR-A",
        "ЮП-PAIR-B",
        manual_n=8,
        length={"length_mm": 2700, "is_primary": True},
    )
    await session.commit()

    template = await _create_template(session, name="Paired Hanger Template", code="paired-hanger-template")
    await session.commit()

    wb = _workbook_paired()
    response = await client.post(
        f"/api/imports/excel/preview?template_id={template.id}",
        data={"normalize_hanger_quantity": "true"},
        files={"file": ("paired.xlsx", wb, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["source_sku"] for item in body["items"]] == ["ЮП-PAIR-A", "ЮП-PAIR-B"]
    for item in body["items"]:
        after_data = item["after_data"]
        # 10 → кратно N=8 у каждой позиции пары
        assert after_data["quantity"] == "16", item["source_sku"]
        assert after_data["original_quantity"] in ("10", "10.0")
        assert after_data["quantity_per_hanger"] == 8
        assert after_data["hanger_count"] == 2
        # Округление молчаливое — текстового предупреждения нет
        assert not any("paired_hanger_adjusted" in w for w in item["warnings"])


@pytest.mark.asyncio
async def test_import_pair_component_without_pair_n_falls_back_to_single_norm(
    client, session, tmp_path, monkeypatch
) -> None:
    """Пара есть, но N невозможна → одиночная норма артикула, позиция не блокируется.

    Позиция-компонент больше не склеена, поэтому неразрешимая норма пары не
    должна запрещать утверждение отдельной позиции (#312).
    """
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    await _make_product_pair(
        session,
        "ЮП-PAIR-A",
        "ЮП-PAIR-B",
        length={"length_mm": 2700, "is_primary": True},
    )
    await session.commit()

    template = await _create_template(session, name="Paired No Hanger Template", code="paired-no-hanger-template")
    await session.commit()

    wb = _workbook_paired()
    response = await client.post(
        f"/api/imports/excel/preview?template_id={template.id}",
        data={"normalize_hanger_quantity": "true"},
        files={"file": ("paired.xlsx", wb, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    body = response.json()
    for item in body["items"]:
        after_data = item["after_data"]
        # Количество не округлено (Decimal строка): нормы нет ни у пары, ни у артикула
        assert after_data["quantity"] in ("10", "10.0"), item["source_sku"]
        assert after_data["original_quantity"] in ("10", "10.0")
        assert after_data["quantity_per_hanger"] is None
        assert "hanger_calc_zero" not in item["errors"]
        assert any(w.startswith("hanger_quantity_not_set") for w in item["warnings"])


@pytest.mark.asyncio
async def test_import_pair_component_keeps_normal_length_with_mismatched_raw(
    client, session, tmp_path, monkeypatch
) -> None:
    """Общая normal 2700 остаётся входом; ручная N пары работает при разных raw A/B."""
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    await _make_product_pair(
        session,
        "ЮП-PAIR-A",
        "ЮП-PAIR-B",
        manual_n=8,
        length={"length_mm": 2700, "raw_length_mm": 2750, "is_primary": True},
        length_b={"length_mm": 2700, "raw_length_mm": 2800, "is_primary": True},
    )
    await session.commit()
    template = await _create_template(
        session, name="Paired Normal Template", code="paired-normal-template"
    )
    await session.commit()

    response = await client.post(
        f"/api/imports/excel/preview?template_id={template.id}",
        data={"normalize_hanger_quantity": "true"},
        files={
            "file": (
                "paired.xlsx",
                _workbook_paired(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200, response.text
    for item in response.json()["items"]:
        assert "normal_length_not_found" not in item["errors"]
        assert "hanger_calc_zero" not in item["errors"]
        after_data = item["after_data"]
        assert after_data["input_dimensions"] == {"length_mm": 2700}
        assert after_data["outputs"][0]["dimensions"] == {"length_mm": 2700}
        assert after_data["quantity_per_hanger"] == 8
        assert after_data["quantity"] == "16"
        assert after_data["hanger_count"] == 2


@pytest.mark.asyncio
async def test_import_pair_component_unknown_normal_length_is_position_error(
    client, session, tmp_path, monkeypatch
) -> None:
    """Нормальная длина вне пересечения пары — обычная ошибка позиции (#312).

    Раньше это была спецпроверка склеенной пары; у позиции-компонента
    работает общий путь: длина входа сверяется с реестром артикула.
    """
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    await _make_product_pair(
        session,
        "ЮП-PAIR-A",
        "ЮП-PAIR-B",
        manual_n=8,
        length={"length_mm": 2750, "raw_length_mm": 2800, "is_primary": True},
        length_b={"length_mm": 2600, "is_primary": True},
    )
    await session.commit()
    template = await _create_template(
        session, name="Paired Unknown Normal Template", code="paired-unknown-normal-template"
    )
    await session.commit()

    response = await client.post(
        f"/api/imports/excel/preview?template_id={template.id}",
        data={"normalize_hanger_quantity": "true"},
        files={
            "file": (
                "paired.xlsx",
                _workbook_paired(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert "normal_length_not_found" in items[0]["errors"]
    assert items[0]["after_data"]["input_dimensions"] == {"length_mm": 2700}
    # У ЮП-PAIR-B реестровая длина 2600, а вход 2700 — своя ошибка позиции.
    assert "normal_length_not_found" in items[1]["errors"]


@pytest.mark.asyncio
async def test_batch_items_cursor_paging_returns_light_rows(client, session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))
    template = await _create_template(session, name="Paging Template", code="paging-template")
    await session.commit()

    created = await client.post(
        f"/api/imports/excel?template_id={template.id}",
        files={
            "file": (
                "plan.xlsx",
                _workbook_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert created.status_code == 201
    batch_id = created.json()["import_batch_id"]

    first = (await client.get(f"/api/imports/batches/{batch_id}/items?limit=1")).json()
    assert first["total"] == 3
    assert len(first["items"]) == 1
    assert "after_data" not in first["items"][0]
    assert first["next_cursor"] is not None

    second = (
        await client.get(
            f"/api/imports/batches/{batch_id}/items?cursor={first['next_cursor']}&limit=1"
        )
    ).json()
    assert len(second["items"]) == 1
    assert second["total"] == 3  # total — размер change set, курсор на него не влияет
    assert second["next_cursor"] is not None
    assert second["items"][0]["item_id"] != first["items"][0]["item_id"]

    third = (
        await client.get(
            f"/api/imports/batches/{batch_id}/items?cursor={second['next_cursor']}&limit=1"
        )
    ).json()
    assert len(third["items"]) == 1
    assert third["next_cursor"] is None

    missing = await client.get("/api/imports/batches/999999999/items")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_import_item_full_returns_after_data(client, session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))
    template = await _create_template(session, name="Item Template", code="item-template")
    await session.commit()

    created = await client.post(
        f"/api/imports/excel?template_id={template.id}",
        files={
            "file": (
                "plan.xlsx",
                _workbook_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert created.status_code == 201
    item_id = created.json()["items"][0]["item_id"]

    light = (await client.get(f"/api/imports/items/{item_id}")).json()
    assert "after_data" not in light
    assert light["item_id"] == item_id

    full = (await client.get(f"/api/imports/items/{item_id}?full=1")).json()
    assert full["after_data"]["source_sku"] == "ЮП-2616"

    missing = await client.get("/api/imports/items/999999999?full=1")
    assert missing.status_code == 404


# ─────────────────────────────────────────────────────────────
# Источник количества на подвес в предпросмотре (after_data.hanger_source)
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("attributes", "expected_source", "expected_quantity_per_hanger"),
    [
        (
            {
                "hanger_mode": "auto",
                "perimeter_mm": 60,
                "mount_width_mm": 15,
                "quantity_per_hanger": {"2700": {"auto": 6, "manual": None}},
            },
            "auto",
            80,
        ),
        (
            {"hanger_mode": "manual", "quantity_per_hanger": {"2700": {"auto": None, "manual": 9}}},
            "manual",
            9,
        ),
        ({"hanger_mode": "auto"}, "none", None),
    ],
    ids=["auto", "manual", "none"],
)
async def test_preview_single_hanger_source_matches_product_mode(
    client, session, tmp_path, monkeypatch, attributes, expected_source, expected_quantity_per_hanger
) -> None:
    """Одиночная строка: источник и значение количества на подвес — по режиму артикула.

    ``auto`` — авторасчёт по сырьевой длине строки из геометрии артикула
    (хранимое в карточке авто-значение не участвует, #170), ``manual`` —
    ручное значение длины, нет значения — ``none`` (а не режим артикула).
    """
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    from app.models.product import Product, ProductType

    product = Product(
        sku="HS-SINGLE",
        name="Hanger Source Single",
        type=ProductType.finished_good,
        unit="pcs",
        attributes=attributes,
    )
    session.add(product)
    await session.commit()

    template = await _create_template(
        session, name="Hanger Source Single Template", code="hanger-source-single-template"
    )
    await session.commit()

    wb = _workbook_with_quantity("HS-SINGLE", "Hanger Source Single", 10)
    response = await client.post(
        f"/api/imports/excel/preview?template_id={template.id}",
        data={"normalize_hanger_quantity": "true"},
        files={"file": ("single.xlsx", wb, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    after_data = response.json()["items"][0]["after_data"]
    assert after_data["hanger_source"] == expected_source
    # Источник не врёт о значении: auto/manual отдают своё число, none — пусто.
    assert after_data["quantity_per_hanger"] == expected_quantity_per_hanger


@pytest.mark.asyncio
async def test_preview_single_hanger_source_missing_product(
    client, session, tmp_path, monkeypatch
) -> None:
    """Одиночная строка: артикула нет в справочнике → missing_product + product_not_found."""
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    template = await _create_template(
        session, name="Hanger Source Missing Template", code="hanger-source-missing-template"
    )
    await session.commit()

    wb = _workbook_with_quantity("HS-ABSENT", "Absent Product", 10)
    response = await client.post(
        f"/api/imports/excel/preview?template_id={template.id}",
        data={"normalize_hanger_quantity": "true"},
        files={"file": ("single.xlsx", wb, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["after_data"]["hanger_source"] == "missing_product"
    assert "product_not_found" in item["errors"]
    assert item["after_data"]["quantity_per_hanger"] is None


@pytest.mark.asyncio
async def test_preview_pair_component_hanger_source_missing_product(
    client, session, tmp_path, monkeypatch
) -> None:
    """Парная строка без записи product_pairs → missing_product + product_pair_not_found."""
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    template = await _create_template(
        session, name="Hanger Source Missing Pair Template", code="hanger-source-missing-pair-template"
    )
    await session.commit()

    wb = _workbook_paired()
    response = await client.post(
        f"/api/imports/excel/preview?template_id={template.id}",
        data={"normalize_hanger_quantity": "true"},
        files={"file": ("paired.xlsx", wb, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    items = response.json()["items"]
    # Строки пары больше не склеены, поэтому отсутствие записи product_pairs
    # выглядит как обычные одиночные позиции с незаведённым артикулом.
    assert [item["source_sku"] for item in items] == ["ЮП-PAIR-A", "ЮП-PAIR-B"]
    for item in items:
        assert item["after_data"]["hanger_source"] == "missing_product"
        assert "product_not_found" in item["errors"]
        assert item["after_data"]["quantity_per_hanger"] is None


@pytest.mark.asyncio
async def test_preview_pair_component_hanger_source_manual_n(
    client, session, tmp_path, monkeypatch
) -> None:
    """Обе позиции-компонента с ручной N пары → источник manual (#312)."""
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    await _make_product_pair(
        session,
        "ЮП-PAIR-A",
        "ЮП-PAIR-B",
        manual_n=8,
        length={"length_mm": 2700, "is_primary": True},
    )
    await session.commit()

    template = await _create_template(
        session, name="Hanger Source Paired Manual Template", code="hanger-source-paired-manual-template"
    )
    await session.commit()

    wb = _workbook_paired()
    response = await client.post(
        f"/api/imports/excel/preview?template_id={template.id}",
        data={"normalize_hanger_quantity": "true"},
        files={"file": ("paired.xlsx", wb, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["source_sku"] for item in items] == ["ЮП-PAIR-A", "ЮП-PAIR-B"]
    for item in items:
        assert item["after_data"]["hanger_source"] == "manual"
        assert item["after_data"]["quantity_per_hanger"] == 8
        assert item["after_data"]["hanger_count"] == 2
