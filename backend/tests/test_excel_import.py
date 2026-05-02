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
