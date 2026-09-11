from io import BytesIO

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.models.import_template import ImportTemplate
from app.models.product import Product, ProductType
from app.models.route import ProductionRoute, RouteStage, RouteOperation
from app.models.section import Section


def _single_row_workbook() -> bytes:
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
    ws.append(
        [
            "ЮП-2630",
            "ТЗ",
            "Стык с дюбелем 40мм 2,7 анод.серебро матовый",
            3400,
            "серебро",
            100,
            2.7,
            "",
            "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*30 на пачку из 10 шт",
            "",
            2.7,
            100,
            100,
            100,
            "ГП",
            "",
        ]
    )
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


@pytest.mark.asyncio
async def test_single_row_import_yup_2630_passes_when_product_and_route_exist(client, session) -> None:
    product = await session.scalar(select(Product).where(Product.sku == "ЮП-2630"))
    if product is None:
        product = Product(
            sku="ЮП-2630",
            name="Стык с дюбелем 40мм 2,7 анод.серебро матовый",
            type=ProductType.finished_good,
            unit="pcs",
            is_active=True,
        )
        session.add(product)
        await session.flush()

    section_specs = [
        ("WH-RAW-2630", "Склад сырья", "raw_stock"),
        ("PACK-2630", "Упаковка", "production"),
        ("WH-FG-2630", "Склад ГП", "finished_stock"),
    ]
    sections: list[Section] = []
    for code, name, type_ in section_specs:
        section = await session.scalar(select(Section).where(Section.code == code))
        if section is None:
            section = Section(code=code, name=name, type=type_, is_active=True)
            session.add(section)
            await session.flush()
        sections.append(section)

    route = await session.scalar(select(ProductionRoute).where(ProductionRoute.name == "Route ЮП-2630"))
    if route is None:
        route = ProductionRoute(name="Route ЮП-2630", is_active=True)
        session.add(route)
        await session.flush()
    stage_count = await session.scalar(select(RouteStage.id).where(RouteStage.route_id == route.id).limit(1))
    if stage_count is None:
        for seq, section in enumerate(sections, start=1):
            stage = RouteStage(
                route_id=route.id,
                sequence=seq * 10,
                section_id=section.id,
                is_final=seq == len(sections),
            )
            session.add(stage)
            await session.flush()
            session.add(
                RouteOperation(
                    route_stage_id=stage.id,
                    sequence=1,
                    operation_name=f"Step {seq}",
                )
            )
    await session.commit()

    template = ImportTemplate(
        name="Single Row Template",
        code="single-row-template",
        is_active=True,
        column_mapping={"sku": {"header": "Артикул", "column": "A"}},
    )
    session.add(template)
    await session.commit()

    response = await client.post(
        f"/api/imports/excel?template_id={template.id}",
        files={
            "file": (
                "single-row-yup2630.xlsx",
                _single_row_workbook(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["summary"]["total_positions"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["source_sku"] == "ЮП-2630"
    assert any(c.startswith("hanger_quantity_not_set") for c in item["codes"])
    full = (await client.get(f"/api/imports/items/{item['item_id']}?full=1")).json()
    assert full["after_data"]["source_sku"] == "ЮП-2630"
    assert full["errors"] == []
