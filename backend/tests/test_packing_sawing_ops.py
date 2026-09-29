"""#226: операции упаковки (склейка, рассеиватель) и пилы по длине раскроя.

Три контракта, которые видит потребитель:

- справочник даёт участкам упаковки и пилы операции, которые различают строки
  плана, и помечает резку по длине трансформирующей (ADR-0002);
- строка с «клей»/«рассеиватель» получает свою операцию упаковки и не тащит в
  маршрут сверловку с прессом — её маршрут тот же, что у строки без первичной
  операции;
- «Без рассеивателя» — признак отсутствия: операция не назначается и ошибкой
  строки импорта не становится, при этом значение узнанным считается (#227).
"""

from __future__ import annotations

from io import BytesIO

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.models.import_template import ImportTemplate
from app.models.product import Product, ProductLength, ProductType
from app.models.production_plan import PlanChangeItem, ProductionPlan
from app.models.route import RouteRuleProfile, SectionOperation
from app.models.section import Section
from app.seeds.run_seed import run_full_seed

from app.services.route_builder import build_route_from_profile
from app.services.plan_import_service import create_excel_import_change_set
from tests.plan_sample import HEADERS

PROFILE_CODE = "packaging_map_rp"
TEMPLATE_CODE = "upakovochnaya_karta_rp"

#: Коды ошибки #227: значение операции строки не узнал ни один профиль.
OPERATION_NOT_RECOGNIZED = "route_operation_not_recognized"

#: Операции упаковки, которые назначает правило по значению колонки H.
PACKING_CASES = [
    ("клей", "PACK_GLUE"),
    ("рассеиватель", "PACK_LENS"),
]

#: (вход, выход, число выходов, ожидаемая операция пилы). Базовую `SAW` получают
#: и строки без раскроя (вход = выход), и раскрой на несколько длин (ADR-0003):
#: одна операция такой раскрой не описывает.
SAWING_CASES = [
    ("2.7", "0.9", 1, "SAW_0900"),
    ("2.7", "1.35", 1, "SAW_1350"),
    ("2.7", "1.8", 1, "SAW_1800"),
    ("2.7", "2.7", 1, "SAW"),
    ("2.4", "2.4", 1, "SAW"),
    ("2.5", "2.5", 1, "SAW"),
    ("3.0", "3.0", 1, "SAW"),
    ("2.7", "0.9", 2, "SAW"),
]


def _payload(
    *,
    operation: str | None = None,
    input_length: str = "2.7",
    output_length: str = "2.7",
    outputs: int = 1,
) -> dict:
    return {
        "operation": operation,
        "color": "серебро",
        "input_length": input_length,
        "output_length": output_length,
        "outputs": [{"dimensions": {"length_mm": 2700.0}} for _ in range(outputs)],
    }


async def _ops_by_section(session, payload: dict) -> dict[str, str | None]:
    """Операция каждого участка в маршруте, собранном профилем плана."""
    profile = await session.scalar(
        select(RouteRuleProfile).where(RouteRuleProfile.code == PROFILE_CODE)
    )
    assert profile is not None, f"профиль {PROFILE_CODE} не просидирован"
    route = await build_route_from_profile(session, profile, payload)
    assert route.error is None, route.error
    return {step.section_code: step.operation_code for step in route.steps}


@pytest.mark.asyncio
async def test_seed_gives_packing_and_sawing_their_own_operations(session) -> None:
    """Справочник — источник операций: без них маршрут не может ничем их не заменить."""
    await run_full_seed(session, force=True)

    sections = {
        code: (await session.scalar(select(Section).where(Section.code == code)))
        for code in ("PACKING", "SAWING")
    }
    ops = {
        section_code: list(
            (
                await session.scalars(
                    select(SectionOperation)
                    .where(SectionOperation.section_id == section.id)
                    .order_by(SectionOperation.sort_order, SectionOperation.operation_code)
                )
            ).all()
        )
        for section_code, section in sections.items()
    }

    assert {op.operation_code for op in ops["PACKING"]} == {"PACK", "PACK_GLUE", "PACK_LENS"}
    assert {op.operation_code for op in ops["SAWING"]} == {
        "SAW",
        "SAW_0900",
        "SAW_1350",
        "SAW_1800",
        "SAW_2700",
    }

    # Резка на конкретную длину трансформирует габариты так же, как «просто резка»:
    # иначе доска участка перестала бы показывать раскрой (ADR-0002).
    transforms = {op.operation_code for op in ops["SAWING"] if op.transforms_dimensions}
    assert transforms == {"SAW", "SAW_0900", "SAW_1350", "SAW_1800", "SAW_2700"}

    # Дефолт группы — базовая операция: строка, которую ни одно правило не
    # различает, получает «Упаковку»/«Резку на пиле», а не первую по длине.
    assert ops["PACKING"][0].operation_code == "PACK"
    assert ops["SAWING"][0].operation_code == "SAW"


@pytest.mark.asyncio
@pytest.mark.parametrize(("operation", "expected"), PACKING_CASES)
async def test_packing_operation_row_gets_own_operation(
    session, operation: str, expected: str
) -> None:
    """Склейка и рассеиватель — операция упаковки этой строки, а не пресс по дефолту."""
    await run_full_seed(session, force=True)

    ops = await _ops_by_section(session, _payload(operation=operation))
    reference = await _ops_by_section(session, _payload())

    assert ops["PACKING"] == expected
    assert "DRILLING" not in ops, f"{operation}: {ops}"
    assert "PRESSING" not in ops, f"{operation}: {ops}"
    # Свой маршрут упаковки — единственное отличие от строки без операции.
    assert set(ops) == set(reference)


@pytest.mark.asyncio
async def test_no_lens_value_keeps_default_packing_and_drops_press_sections(session) -> None:
    """«Без рассеивателя» — признак отсутствия: операция дефолтная, пресс не нужен."""
    await run_full_seed(session, force=True)

    ops = await _ops_by_section(session, _payload(operation="Без рассеивателя"))

    assert ops["PACKING"] == "PACK"
    assert "DRILLING" not in ops
    assert "PRESSING" not in ops


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("input_length", "output_length", "outputs", "expected"), SAWING_CASES
)
async def test_sawing_operation_follows_cut_length(
    session, input_length: str, output_length: str, outputs: int, expected: str
) -> None:
    """Пила называет длину раскроя; без раскроя строка остаётся на базовой `SAW`."""
    await run_full_seed(session, force=True)

    ops = await _ops_by_section(
        session,
        _payload(input_length=input_length, output_length=output_length, outputs=outputs),
    )
    assert ops["SAWING"] == expected


def _workbook(rows: list[tuple[str, str | None, str, str, str]]) -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "totalplan"
    for _ in range(3):
        sheet.append([])
    sheet.append(list(HEADERS))
    for sku, operation, color, input_length, output_length in rows:
        quantity = 300
        sheet.append([
            sku,
            "ТЗ",
            f"Профиль {sku} 2,7 м анод{color} матов",
            5000,
            color,
            quantity,
            float(input_length),
            operation,
            "гп, этикетка с шк и наименованием на каждый профиль",
            None,
            float(output_length),
            quantity,
            quantity,
            0,
            "ГП",
        ])
    out = BytesIO()
    book.save(out)
    return out.getvalue()


#: Строки одного импорта: операция приходит колонкой H и различает маршруты.
IMPORT_ROWS = [
    ("УП-0001", "клей", "серебро", "2.7", "2.7"),
    ("УП-0002", "рассеиватель", "золото", "2.7", "2.7"),
    ("УП-0003", "Без рассеивателя", "черный", "2.7", "2.7"),
    ("УП-0004", "фрезеровка", "титан", "2.7", "2.7"),
]


@pytest.mark.asyncio
async def test_packing_operation_values_import_without_row_error(session) -> None:
    """Клей, рассеиватель и «без рассеивателя» — узнанные значения: ошибки строки нет."""
    await run_full_seed(session, force=True)
    template_id = await session.scalar(
        select(ImportTemplate.id).where(ImportTemplate.code == TEMPLATE_CODE)
    )
    profile_id = await session.scalar(
        select(RouteRuleProfile.id).where(RouteRuleProfile.code == PROFILE_CODE)
    )
    for sku, _operation, _color, input_length, _output_length in IMPORT_ROWS:
        product = Product(
            sku=sku,
            name=f"Профиль {sku}",
            type=ProductType.finished_good,
            unit="pcs",
            is_active=True,
        )
        session.add(product)
        await session.flush()
        session.add(
            ProductLength(
                product_id=product.id,
                length_mm=float(input_length) * 1000,
                is_primary=True,
            )
        )
    plan = ProductionPlan(plan_no="PLAN-226", name="План 226")
    session.add(plan)
    await session.flush()
    await session.commit()

    result = await create_excel_import_change_set(
        session,
        filename="plan-226.xlsx",
        content=_workbook(IMPORT_ROWS),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        production_plan_id=plan.id,
        template_id=template_id,
        rule_profile_id=profile_id,
    )
    items = {
        str((item.after_data or {}).get("source_sku")): item
        for item in (
            await session.scalars(
                select(PlanChangeItem)
                .where(PlanChangeItem.change_set_id == result["change_set_id"])
                .order_by(PlanChangeItem.id)
            )
        ).all()
    }
    assert set(items) == {sku for sku, *_rest in IMPORT_ROWS}, sorted(items)

    for sku, operation, _color, _in, _out in IMPORT_ROWS:
        errors = items[sku].errors or []
        if operation == "фрезеровка":
            # Правила узнают ровно свои значения: опечатка остаётся ошибкой (#227).
            assert OPERATION_NOT_RECOGNIZED in errors, (operation, errors)
        else:
            assert OPERATION_NOT_RECOGNIZED not in errors, (operation, errors)
