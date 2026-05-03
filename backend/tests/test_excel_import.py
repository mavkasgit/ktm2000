from io import BytesIO

import pytest
from openpyxl import Workbook

from app.core.config import settings
from app.models.imports import ImportBatch, ImportFile
from app.models.production_plan import PlanChangeItem, PlanChangeSet, ProductionPlan
from app.services.excel_import import parse_factory_plan_workbook


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


def test_factory_plan_parser_groups_paired_profiles_and_continuations() -> None:
    parsed = parse_factory_plan_workbook(_workbook_bytes(), "plan.xlsx")

    assert parsed.sheet_name == "План май 26 05"
    assert parsed.header_row_number == 5
    assert parsed.period_start.isoformat() == "2026-05-01"
    assert parsed.period_end.isoformat() == "2026-05-31"
    assert len(parsed.parsed_rows) == 3

    paired = parsed.parsed_rows[0]
    assert paired.source_row_numbers == [6, 7]
    assert paired.source_sku == "ЮП-2616+ЮП-2604"
    assert paired.quantity == 300
    assert paired.payload["paired_profile"] is True
    assert [component["sku"] for component in paired.payload["components"]] == ["ЮП-2616", "ЮП-2604"]

    continuation = parsed.parsed_rows[2]
    assert continuation.source_row_numbers == [9]
    assert continuation.payload["context_inherited"] is True
    assert continuation.source_name == "Стык 38 мм. 2,7 анод.серебро, матовый"
    assert continuation.quantity == 900


@pytest.mark.asyncio
async def test_import_excel_creates_batch_and_change_set(client, session, tmp_path, monkeypatch) -> None:
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

    assert response.status_code == 201
    body = response.json()
    assert body["summary"]["total_positions"] == 3
    assert body["summary"]["paired_profile_positions"] == 1
    assert len(body["items"]) == 3
    assert body["items"][0]["after_data"]["source_sku"] == "ЮП-2616+ЮП-2604"
    assert body["items"][0]["warnings"] == ["paired_profile_product_unmapped"]
    assert body["items"][1]["errors"] == ["product_not_found"]

    assert await session.get(ImportFile, body["import_file_id"]) is not None
    assert await session.get(ImportBatch, body["import_batch_id"]) is not None
    assert await session.get(ProductionPlan, body["production_plan_id"]) is not None
    assert await session.get(PlanChangeSet, body["change_set_id"]) is not None

    change_items = body["items"]
    assert await session.get(PlanChangeItem, change_items[0]["id"]) is not None


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


def test_factory_plan_parser_maps_additional_pack_operations() -> None:
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
    out = BytesIO()
    wb.save(out)

    parsed = parse_factory_plan_workbook(out.getvalue(), "pack_ops.xlsx")
    assert len(parsed.parsed_rows) == 2

    glue = parsed.parsed_rows[0].payload
    assert glue["operation_code"] == "PACK"
    assert glue["operation_name"] == "Упаковка"
    assert glue["additional_pack_operations"][0]["operation_code"] == "PACK_GLUE"

    diffuser = parsed.parsed_rows[1].payload
    assert diffuser["operation_code"] == "PACK"
    assert diffuser["operation_name"] == "Упаковка"
    assert diffuser["additional_pack_operations"][0]["operation_code"] == "PACK_DIFFUSER"


from datetime import date, datetime

from app.services.excel_import import _excel_date_to_date, _parse_date


def test_date_normalization() -> None:
    assert _parse_date(date(2026, 5, 2)) == date(2026, 5, 2)
    assert _parse_date(datetime(2026, 5, 2, 14, 30)) == date(2026, 5, 2)
    assert _parse_date("2026-05-02") == date(2026, 5, 2)
    assert _parse_date("02.05.2026") == date(2026, 5, 2)
    assert _excel_date_to_date(1) == date(1899, 12, 31)
    assert _parse_date(44561) == date(2021, 12, 31)
    assert _parse_date("invalid") is None
    assert _parse_date(None) is None


@pytest.mark.asyncio
async def test_replace_draft_mode_creates_cancel_for_missing_rows(client, session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))

    from app.models.techcard import Techcard, TechcardLine
    from app.models.product import Product, ProductType
    from app.models.route import ProductionRoute, RouteStep
    from app.models.section import Section

    product = Product(sku="FG-TEST", name="Test Product", type=ProductType.finished_good, unit="pcs")
    component = Product(sku="FG-TEST-RAW", name="Test Raw", type=ProductType.component, unit="pcs")
    sections = [
        Section(code="CUT", name="Cut"),
        Section(code="PACK", name="Pack"),
    ]
    session.add_all([product, component, *sections])
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(TechcardLine(techcard_id=techcard.id, component_product_id=component.id, quantity=1, unit="pcs"))

    route = ProductionRoute(product_id=product.id, name="Main", version="v1", is_active=True)
    session.add(route)
    await session.flush()
    for index, section in enumerate(sections, start=1):
        session.add(
            RouteStep(
                route_id=route.id,
                sequence=index,
                section_id=section.id,
                operation_name=f"Step {index}",
                is_final=index == len(sections),
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
    wb1 = _make_workbook([("FG-TEST", "Test Product", 100), ("FG-TEST", "Test Product", 200)])
    response1 = await client.post(
        "/api/imports/excel",
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
        "/api/imports/excel",
        data={"mode": "replace_draft_from_same_source", "production_plan_id": str(plan_id)},
        files={"file": ("plan2.xlsx", wb2, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response2.status_code == 201
    body2 = response2.json()
    actions = [item["change_action"] for item in body2["items"]]
    assert "cancel_draft_position" in actions
