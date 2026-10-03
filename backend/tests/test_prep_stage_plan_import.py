"""План подготовительного участка (#313): три варианта маршрута, задания → PREP_STOCK.

Покрывает:
1. колонки шаблона `plan_prep_stage` (общий `parse_factory_plan_workbook`);
2. три ветки правил подбора маршрута — по значению колонки «Операция»;
3. операции строк из колонки файла (`resolve_operations`) и дефолт участка;
4. импорт файла новым шаблоном → позиции плана с маршрутами.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from app.models.import_template import ImportTemplate
from app.models.product import Product, ProductType
from app.models.production_plan import PlanChangeItem, ProductionPlan
from app.models.route import RouteRuleProfile, RouteStage, SectionOperation
from app.models.section import Section
from app.seeds.canon.models import SelectionRuleDef
from app.seeds.import_templates import IMPORT_TEMPLATES
from app.seeds.route_rule_profiles import ROUTE_RULE_PROFILES
from app.seeds.sections import SECTION_OPS, SECTIONS_DATA
from app.seeds.seeders.selection_rules_seeder import seed_selection_rules
from app.seeds.selection_rules import SELECTION_RULES
from app.services.excel_import import parse_factory_plan_workbook
from app.services.plan_import_service import create_excel_import_change_set
from app.services.route_builder import build_route_from_profile
from openpyxl import Workbook
from sqlalchemy import select

TEMPLATE_CODE = "plan_prep_stage"
PROFILE_CODE = "prep_stage_plan"

#: Заголовки файла «Плана подготовительного участка» — те же, что в сиде
#: шаблона (`IMPORT_TEMPLATES`), в порядке колонок A..F.
HEADERS = ["Артикул", "Наименование", "Цвет", "Операция", "Кол-во, шт", "Примечание"]

#: Три варианта подготовительного маршрута и ожидаемый состав участков.
#: Старт у всех — RAW_STOCK, финиш — PREP_STOCK (#313). «Окно» и «гребенка» —
#: один вариант (пресс+дробеструй) с разными видами операции пресса.
VARIANTS = [
    ("сверловка", ["RAW_STOCK", "DRILLING", "SHOT_BLAST", "PREP_STOCK"]),
    ("окно", ["RAW_STOCK", "PRESSING", "SHOT_BLAST", "PREP_STOCK"]),
    ("гребенка", ["RAW_STOCK", "PRESSING", "SHOT_BLAST", "PREP_STOCK"]),
    ("", ["RAW_STOCK", "SHOT_BLAST", "PREP_STOCK"]),
]

#: По одному представителю каждого СОСТАВА участков — для проверки имён.
VARIANT_REPRESENTATIVES = ["сверловка", "окно", ""]


def _template_mapping() -> dict:
    for template in IMPORT_TEMPLATES:
        if template["code"] == TEMPLATE_CODE:
            return template["column_mapping"]
    raise AssertionError(f"шаблон {TEMPLATE_CODE} не найден в сидах")


def _profile_seed() -> dict:
    for profile in ROUTE_RULE_PROFILES:
        if profile["code"] == PROFILE_CODE:
            return profile
    raise AssertionError(f"профиль {PROFILE_CODE} не найден в сидах")


def _prep_workbook(rows: list[tuple[str, str, str, str, int]]) -> bytes:
    """Книга в структуре нового шаблона: три пустые строки, затем шапка."""
    wb = Workbook()
    ws = wb.active
    ws.title = "prepplan"
    for _ in range(3):
        ws.append([])
    ws.append(HEADERS)
    for sku, name, color, operation, quantity in rows:
        ws.append([sku, name, color, operation, quantity, "E2E подготовка"])
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


async def _seed_sections(session) -> None:
    """Участки и операции — из сида, а не из ручного дубля справочника."""
    for item in SECTIONS_DATA:
        session.add(
            Section(
                code=item["code"],
                name=item["name"],
                sort_order=item["sort_order"],
                type=item["type"],
                is_output_default=item["is_output_default"],
                is_active=True,
            )
        )
    await session.flush()

    sections = (await session.execute(select(Section))).scalars().all()
    for section in sections:
        # (group_code, group_name, sort_order, op_code, op_name, is_significant, …)
        for op in SECTION_OPS.get(section.code, []):
            group_code, group_name, sort_order, op_code, op_name, is_sig = op[:6]
            if op_code is None:
                # Операция без кода — placeholder, резолвится динамически.
                continue
            session.add(
                SectionOperation(
                    section_id=section.id,
                    operation_code=op_code,
                    operation_name=op_name,
                    group_code=group_code,
                    group_name=group_name,
                    sort_order=sort_order,
                    is_significant=is_sig,
                )
            )
    await session.flush()


async def _seed_profile(session) -> RouteRuleProfile:
    """Профиль нового шаблона + его правила — из СИДОВ, а не из ручного дубля."""
    await _seed_sections(session)
    seed = _profile_seed()
    profile = RouteRuleProfile(
        code=PROFILE_CODE,
        name=seed["name"],
        is_active=True,
        priority=seed["priority"],
        route_name_pattern=seed["route_name_pattern"],
        route_sections=list(seed["route_sections"]),
    )
    session.add(profile)
    await session.flush()

    sections = (await session.execute(select(Section))).scalars().all()
    section_map = {s.code: s for s in sections}
    rules = [SelectionRuleDef.model_validate(d) for d in SELECTION_RULES if d["profile_code"] == PROFILE_CODE]
    assert rules, "правила подготовки в сидах не найдены"
    await seed_selection_rules(session, rules, profile, section_map)
    await session.commit()
    return profile


async def _make_product(session, sku: str) -> Product:
    product = Product(sku=sku, name=f"Уголок {sku}", type=ProductType.finished_good, unit="pcs")
    session.add(product)
    await session.commit()
    return product


# ─── 1. Колонки шаблона ──────────────────────────────────────────────────────


def test_prep_template_declares_required_and_operation_columns() -> None:
    """В маппинге есть обязательные колонки и колонка операций (#313, п.1)."""
    mapping = _template_mapping()
    assert {"sku", "product_name", "quantity"} <= set(mapping)
    assert "operation" in mapping, "колонка операций обязательна: по ней выбирается вариант"


def test_prep_template_drops_columns_outside_prep_route() -> None:
    """Лишние колонки убраны: подготовительный маршрут до них не доходит."""
    mapping = _template_mapping()
    for dropped in ("west_quantity", "east_quantity", "output_kind", "packaging_1_8_quantity"):
        assert dropped not in mapping, f"{dropped} не имеет отношения к подготовке"


def test_prep_profile_route_sections_start_raw_and_finish_prep() -> None:
    """`route_sections` начинается с RAW_STOCK и заканчивается PREP_STOCK."""
    sections = list(_profile_seed()["route_sections"])
    assert sections[0] == "RAW_STOCK"
    assert sections[-1] == "PREP_STOCK"
    assert "SHOT_BLAST" in sections, "дробеструй есть во всех трёх вариантах"


def test_prep_workbook_parsed_by_common_parser_with_template_mapping() -> None:
    """Общий парсер разбирает файл нового шаблона — свой парсер не нужен."""
    content = _prep_workbook([("ЮП-900", "Уголок 15*15", "черный", "сверловка", 120)])
    parsed = parse_factory_plan_workbook(
        content, "План подготовительного участка.xlsx", column_mapping=_template_mapping()
    )
    assert parsed.header_row_number == 4
    assert len(parsed.parsed_rows) == 1
    row = parsed.parsed_rows[0]
    assert row.source_sku == "ЮП-900"
    assert row.payload["operation"] == "сверловка"
    assert row.payload["source_name"] == "Уголок 15*15"
    assert float(row.quantity) == 120


# ─── 2. Три ветки правил подбора маршрута ────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,expected_sections", VARIANTS)
async def test_each_file_variant_builds_its_own_route(session, operation: str, expected_sections: list[str]) -> None:
    """Каждый вариант файла → свой маршрут, порядок этапов и финиш верные."""
    profile = await _seed_profile(session)
    built = await build_route_from_profile(session, profile, {"operation": operation})

    assert not built.error, f"маршрут не собрался: {built.error}"
    assert [s.section_code for s in built.steps] == expected_sections
    assert built.route_sections[-1] == "PREP_STOCK", "финиш подготовительного маршрута — PREP_STOCK"
    assert built.steps[-1].is_final, "финальным объявлен последний этап"


@pytest.mark.asyncio
async def test_three_variants_get_distinct_route_names(session) -> None:
    """Три варианта — три разных имени: иначе они делили бы один маршрут."""
    profile = await _seed_profile(session)
    names = set()
    for operation in VARIANT_REPRESENTATIVES:
        built = await build_route_from_profile(session, profile, {"operation": operation})
        names.add(built.name)
    assert len(names) == 3, f"имена маршрутов схлопнулись: {names}"


# ─── 3. Операции строк из колонок файла ──────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,expected_operation",
    [("сверловка", "DRILL"), ("окно", "PRESS_WINDOW"), ("гребенка", "PRESS_COMB")],
)
async def test_row_operation_comes_from_file_column(session, operation: str, expected_operation: str) -> None:
    """Операция участка берётся из колонки «Операция» (правило resolve_operations)."""
    profile = await _seed_profile(session)
    built = await build_route_from_profile(session, profile, {"operation": operation})
    codes = [s.operation_code for s in built.steps if s.operation_code]
    assert expected_operation in codes, f"{operation!r} → {codes}"


@pytest.mark.asyncio
async def test_shot_only_row_falls_back_to_section_default_operation(session) -> None:
    """Пустая колонка операций: участок даёт свою дефолтную операцию (SHOT)."""
    profile = await _seed_profile(session)
    built = await build_route_from_profile(session, profile, {"operation": ""})
    codes = [s.operation_code for s in built.steps if s.operation_code]
    assert codes == ["SHOT"], f"ожидался дефолт дробеструя, получено {codes}"


# ─── 4. Импорт файла новым шаблоном → позиции ────────────────────────────────


@pytest.mark.asyncio
async def test_prep_import_creates_positions_with_prep_routes(session) -> None:
    """Файл новым шаблоном → позиции, у каждой маршрут подготовки до PREP_STOCK."""
    profile = await _seed_profile(session)
    template = ImportTemplate(
        code=TEMPLATE_CODE,
        name="План подготовительного участка",
        is_active=True,
        column_mapping=_template_mapping(),
    )
    session.add(template)
    for sku in ("ЮП-901", "ЮП-902", "ЮП-903"):
        await _make_product(session, sku)
    plan = ProductionPlan(plan_no="PREP-001", name="План подготовки")
    session.add(plan)
    await session.flush()

    content = _prep_workbook(
        [
            ("ЮП-901", "Уголок 15*15", "черный", "сверловка", 120),
            ("ЮП-902", "Плинтус 16", "серебро", "окно", 80),
            ("ЮП-903", "Кант 47", "черный", "", 60),
        ]
    )
    result = await create_excel_import_change_set(
        session,
        filename="План подготовительного участка.xlsx",
        content=content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        production_plan_id=plan.id,
        template_id=template.id,
        column_mapping=_template_mapping(),
        rule_profile_id=profile.id,
    )

    # Create-ответ лёгкий: полные данные позиций читаем из persisted items.
    db_items = (
        await session.execute(
            select(PlanChangeItem)
            .where(PlanChangeItem.change_set_id == result["change_set_id"])
            .order_by(PlanChangeItem.id)
        )
    ).scalars().all()
    by_sku = {i.after_data["source_sku"]: i.after_data for i in db_items if i.after_data}
    assert set(by_sku) == {"ЮП-901", "ЮП-902", "ЮП-903"}, f"строки не импортированы: {list(by_sku)}"

    expected = {
        "ЮП-901": ["RAW_STOCK", "DRILLING", "SHOT_BLAST", "PREP_STOCK"],
        "ЮП-902": ["RAW_STOCK", "PRESSING", "SHOT_BLAST", "PREP_STOCK"],
        "ЮП-903": ["RAW_STOCK", "SHOT_BLAST", "PREP_STOCK"],
    }
    section_by_id = {s.id: s.code for s in (await session.execute(select(Section))).scalars().all()}
    for sku, codes in expected.items():
        route_id = by_sku[sku]["route_id"]
        stages = (
            await session.execute(
                select(RouteStage).where(RouteStage.route_id == route_id).order_by(RouteStage.sequence)
            )
        ).scalars().all()
        actual = [section_by_id.get(s.storage_section_id or s.section_id) for s in stages]
        assert actual == codes, f"{sku}: {actual} != {codes}"


@pytest.mark.asyncio
async def test_prep_import_position_quantity_comes_from_file(session) -> None:
    """Задание получает своё количество из файла, а не из остатка на складе."""
    profile = await _seed_profile(session)
    template = ImportTemplate(
        code=TEMPLATE_CODE, name="План подготовки", is_active=True, column_mapping=_template_mapping()
    )
    session.add(template)
    await _make_product(session, "ЮП-904")
    plan = ProductionPlan(plan_no="PREP-002", name="План подготовки 2")
    session.add(plan)
    await session.flush()

    result = await create_excel_import_change_set(
        session,
        filename="План подготовительного участка.xlsx",
        content=_prep_workbook([("ЮП-904", "Уголок 20", "серый", "сверловка", 137)]),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        production_plan_id=plan.id,
        template_id=template.id,
        column_mapping=_template_mapping(),
        rule_profile_id=profile.id,
    )
    db_items = (
        await session.execute(
            select(PlanChangeItem).where(PlanChangeItem.change_set_id == result["change_set_id"])
        )
    ).scalars().all()
    item = next(i.after_data for i in db_items if i.after_data and i.after_data["source_sku"] == "ЮП-904")
    assert float(item["quantity"]) == 137