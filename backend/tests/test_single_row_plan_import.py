from io import BytesIO

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.models.import_template import ImportTemplate
from app.models.product import Product, ProductType
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
from app.models.techcard import Techcard, TechcardLine
from app.services.import_normalization import default_import_normalization_rules


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
async def test_single_row_import_yup_2630_passes_when_product_techcard_and_route_exist(client, session) -> None:
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

    component = await session.scalar(select(Product).where(Product.sku == "ЮП-2630-RAW"))
    if component is None:
        component = Product(
            sku="ЮП-2630-RAW",
            name="Сырье ЮП-2630",
            type=ProductType.component,
            unit="pcs",
            is_active=True,
        )
        session.add(component)
        await session.flush()

    section_specs = [
        ("WH-RAW-2630", "Склад сырья", "raw_stock"),
        ("PACK-2630", "Упаковка", "production"),
        ("WH-FG-2630", "Склад ГП", "finished_stock"),
    ]
    sections: list[Section] = []
    for code, name, kind in section_specs:
        section = await session.scalar(select(Section).where(Section.code == code))
        if section is None:
            section = Section(code=code, name=name, kind=kind, is_active=True)
            session.add(section)
            await session.flush()
        sections.append(section)

    techcard = await session.scalar(select(Techcard).where(Techcard.product_id == product.id, Techcard.is_active.is_(True)))
    if techcard is None:
        techcard = Techcard(product_id=product.id, version="v1", is_active=True, processing_type="standart_processing")
        session.add(techcard)
        await session.flush()

    # Critical rule: one line is enough for non-empty techcard.
    existing_line = await session.scalar(
        select(TechcardLine).where(
            TechcardLine.techcard_id == techcard.id,
            TechcardLine.component_product_id == component.id,
        )
    )
    if existing_line is None:
        session.add(TechcardLine(techcard_id=techcard.id, component_product_id=component.id, quantity=1, unit="pcs"))

    route = await session.scalar(select(ProductionRoute).where(ProductionRoute.name == "Route ЮП-2630"))
    if route is None:
        route = ProductionRoute(name="Route ЮП-2630", is_active=True)
        session.add(route)
        await session.flush()
    step_count = await session.scalar(select(RouteStep.id).where(RouteStep.route_id == route.id).limit(1))
    if step_count is None:
        for seq, section in enumerate(sections, start=1):
            session.add(
                RouteStep(
                    route_id=route.id,
                    sequence=seq * 10,
                    section_id=section.id,
                    operation_name=f"Step {seq}",
                    is_final=seq == len(sections),
                )
            )
    await session.commit()

    template = ImportTemplate(
        name="Single Row Template",
        code="single-row-template",
        is_active=True,
        column_mapping={"sku": {"header": "Артикул", "column": "A"}},
        normalization_rules=default_import_normalization_rules(),
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
    assert item["after_data"]["source_sku"] == "ЮП-2630"
    assert item["errors"] == []
