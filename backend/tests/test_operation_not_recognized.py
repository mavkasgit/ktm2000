"""#227: нераспознанное значение операции строки импорта — ошибка строки.

Колонка «Пробивка/сверловка» попадает в payload как ``operation``, и её читают
правила профиля (``app/seeds/selection_rules.py``). Правило ``press_types``
срабатывает по ``not_empty`` на ЛЮБОЕ непустое значение, но его mapping знает
только «окн»/«греб»: при значении «фрезеровка» оно молча ничего не пишет, а
группа операций пресса без резолва берёт первую операцию группы — позиция
получала чужую операцию без единой ошибки.

Контракт, который здесь закреплён:
- непустое значение, которое не узнало ни одно правило профиля → errors +
  статус ``invalid``;
- пустая операция легитимна (правило ``empty_primary``) и ошибки не даёт;
- значения, которые правила узнают («сверл»/«окн»/«греб»), ошибки не дают.

Ключевые слова намеренно не зашиты в сервис: узнаёт ли значение операция —
решают данные правил профиля, поэтому тест строит профиль с теми же условиями
по ``operation``, что и живой сид.
"""
from __future__ import annotations

from io import BytesIO

import pytest
from app.models.import_template import ImportTemplate
from app.models.product import Product, ProductLength, ProductType
from app.models.production_plan import (
    PlanChangeItem,
    PlanChangeItemStatus,
    ProductionPlan,
)
from app.models.route import RouteRuleProfile, RouteSelectionRule, SectionOperation
from app.models.section import Section
from app.services.plan_import_service import create_excel_import_change_set
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.plan_sample import HEADERS

OPERATION_CODE = "route_operation_not_recognized"

SECTIONS = [
    {"code": "RAW_STOCK", "name": "Склад сырья", "sort_order": 10, "type": "raw_stock"},
    {"code": "DRILLING", "name": "Сверловка", "sort_order": 20, "type": "production"},
    {"code": "PRESSING", "name": "Пресс", "sort_order": 30, "type": "production"},
    {"code": "ANODIZING", "name": "Анодирование", "sort_order": 50, "type": "production"},
    {"code": "PACKING", "name": "Упаковка", "sort_order": 80, "type": "production"},
    {"code": "FINISHED_STOCK", "name": "Склад готовой продукции", "sort_order": 90, "type": "finished_stock"},
]
ROUTE_SECTIONS = [item["code"] for item in SECTIONS]

SECTION_OPERATIONS = [
    ("DRILLING", "DRILLING", "Сверловка", "DRILL"),
    ("PRESSING", "PRESSING", "Окно", "PRESS_WINDOW"),
    ("PRESSING", "PRESSING", "Гребенка", "PRESS_COMB"),
    ("ANODIZING", "ANODIZING", "Серебро", "ANOD_01"),
    ("PACKING", "PACKING", "Стретч", "PACK_STRETCH"),
]

#: Условия по полю `operation` — как в `app/seeds/selection_rules.py`.
#: `press_types` срабатывает по `not_empty` на любое непустое значение и обязан
#: поэтому НЕ считаться признаком распознавания: распознаёт значение только
#:`set_operation`/require/exclude и mapping, реально нашедший ключевое слово.
OPERATION_RULES = [
    {
        "code": "drill",
        "name": "Операция сверловки",
        "priority": 900,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "contains", "value": "сверл"},
        ],
        "actions": [
            {"action": "require_section", "section_code": "DRILLING"},
            {"action": "exclude_section", "section_code": "PRESSING"},
        ],
    },
    {
        "code": "press_section",
        "name": "Пресс: участок маршрута",
        "priority": 850,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "contains", "value": "окн"},
            {"source": "payload", "field_path": "operation", "operator": "not_contains", "value": "сверл"},
        ],
        "condition_logic": "and",
        "actions": [
            {"action": "require_section", "section_code": "PRESSING"},
            {"action": "exclude_section", "section_code": "DRILLING"},
        ],
    },
    {
        "code": "press_section_comb",
        "name": "Пресс гребёнка: участок маршрута",
        "priority": 850,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "contains", "value": "греб"},
            {"source": "payload", "field_path": "operation", "operator": "not_contains", "value": "сверл"},
        ],
        "condition_logic": "and",
        "actions": [
            {"action": "require_section", "section_code": "PRESSING"},
            {"action": "exclude_section", "section_code": "DRILLING"},
        ],
    },
    {
        "code": "empty_primary",
        "name": "Без первичной операции",
        "priority": 800,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "empty", "value": None},
        ],
        "actions": [
            {"action": "exclude_section", "section_code": "DRILLING"},
            {"action": "exclude_section", "section_code": "PRESSING"},
        ],
    },
    {
        "code": "press_types",
        "name": "Пресс: определение типа",
        "priority": 100,
        "phase": "resolve_operations",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "not_empty", "value": None},
        ],
        "actions": [
            {
                "action": "set_operation_by_mapping",
                "section_code": "PRESSING",
                "group_code": "PRESSING",
                "lookup_field": "operation",
                "mapping": [
                    {"keyword": "окн", "operation_code": "PRESS_WINDOW"},
                    {"keyword": "греб", "operation_code": "PRESS_COMB"},
                ],
            },
        ],
    },
    {
        "code": "drill_types",
        "name": "Сверловка: определение типа",
        "priority": 100,
        "phase": "resolve_operations",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "contains", "value": "сверл"},
        ],
        "actions": [
            {
                "action": "set_operation",
                "section_code": "DRILLING",
                "group_code": "DRILLING",
                "operation_code": "DRILL",
            },
        ],
    },
]

#: (SKU, значение операции) — пять контрастных строк одного импорта.
PLAN_ROWS = [
    ("ОП-1001", "сверло"),
    ("ОП-1002", "окно"),
    ("ОП-1003", "гребенка"),
    ("ОП-1004", None),
    ("ОП-1005", "фрезеровка"),
]


def _workbook(rows: list[tuple[str, str | None]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "totalplan"
    for _ in range(3):
        ws.append([])
    ws.append(list(HEADERS))
    for sku, operation in rows:
        ws.append([
            sku,
            "ТЗ",
            f"Профиль {sku} 2,7 м анодсеребро матов",
            5000,
            "серебро",
            100,
            2.7,
            operation,
            "смотка спанбондом поштучно в пачке 10 штук",
            None,
            2.7,
            100,
            None,
            100,
            "ГП",
        ])
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


async def _seed_factory(session: AsyncSession) -> tuple[int, int]:
    """Участки, артикулы, шаблон и профиль с правилами по операции."""
    sections_by_code: dict[str, Section] = {}
    for spec in SECTIONS:
        section = Section(**spec, is_active=True)
        session.add(section)
        await session.flush()
        sections_by_code[section.code] = section
    for section_code, group_code, op_name, op_code in SECTION_OPERATIONS:
        session.add(SectionOperation(
            section_id=sections_by_code[section_code].id,
            operation_code=op_code,
            operation_name=op_name,
            group_code=group_code,
            group_name=op_name,
            sort_order=10,
            is_significant=True,
            operation_type="production",
        ))

    for sku, _operation in PLAN_ROWS:
        product = Product(sku=sku, name=f"Профиль {sku}", type=ProductType.finished_good, unit="pcs")
        session.add(product)
        await session.flush()
        session.add(ProductLength(product_id=product.id, length_mm=2700.0, is_primary=True))

    template = ImportTemplate(code="tpl227", name="Шаблон 227", is_active=True)
    session.add(template)
    await session.flush()

    profile = RouteRuleProfile(
        code="profile227",
        name="Профиль 227",
        is_active=True,
        priority=100,
        import_template_id=template.id,
        route_sections=list(ROUTE_SECTIONS),
    )
    session.add(profile)
    await session.flush()

    session.add(RouteSelectionRule(
        code="core_sections",
        name="Базовые участки маршрута",
        profile_id=profile.id,
        priority=1000,
        is_active=True,
        phase="route_select",
        conditions=[],
        actions=[
            {"action": "require_section", "section_code": "RAW_STOCK"},
            {"action": "require_section", "section_code": "ANODIZING"},
            {"action": "require_section", "section_code": "PACKING"},
            {"action": "require_section", "section_code": "FINISHED_STOCK"},
        ],
    ))
    for rule in OPERATION_RULES:
        session.add(RouteSelectionRule(
            code=rule["code"],
            name=rule["name"],
            profile_id=profile.id,
            priority=rule["priority"],
            is_active=True,
            phase=rule["phase"],
            conditions=rule["conditions"],
            actions=rule["actions"],
        ))
    await session.commit()
    return template.id, profile.id


async def _import_items(session: AsyncSession) -> dict[str, PlanChangeItem]:
    template_id, profile_id = await _seed_factory(session)
    plan = ProductionPlan(plan_no="PLAN-227", name="План 227")
    session.add(plan)
    await session.flush()

    result = await create_excel_import_change_set(
        session,
        filename="plan-227.xlsx",
        content=_workbook(PLAN_ROWS),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        production_plan_id=plan.id,
        template_id=template_id,
        rule_profile_id=profile_id,
    )
    items = (
        await session.execute(
            select(PlanChangeItem)
            .where(PlanChangeItem.change_set_id == result["change_set_id"])
            .order_by(PlanChangeItem.id)
        )
    ).scalars().all()
    return {(item.after_data or {})["source_sku"]: item for item in items}


@pytest.mark.asyncio
async def test_unrecognized_operation_invalidates_only_its_row(session: AsyncSession) -> None:
    items = await _import_items(session)
    assert set(items) == {sku for sku, _ in PLAN_ROWS}, "часть строк импорта потеряна"

    unknown = items["ОП-1005"]
    assert OPERATION_CODE in (unknown.errors or []), unknown.errors
    assert unknown.status == PlanChangeItemStatus.invalid


@pytest.mark.asyncio
async def test_recognized_operations_have_no_error(session: AsyncSession) -> None:
    items = await _import_items(session)
    for sku, operation in PLAN_ROWS:
        if operation in ("сверло", "окно", "гребенка"):
            item = items[sku]
            assert OPERATION_CODE not in (item.errors or []), f"{operation}: {item.errors}"


@pytest.mark.asyncio
async def test_empty_operation_stays_legitimate(session: AsyncSession) -> None:
    """Пустая операция — законное состояние, а не опечатка (#227, `empty_primary`)."""
    items = await _import_items(session)
    item = items["ОП-1004"]
    assert OPERATION_CODE not in (item.errors or []), item.errors
    assert item.status != PlanChangeItemStatus.invalid, item.errors


async def _import_with_extra_action(session: AsyncSession, action: dict) -> dict[str, PlanChangeItem]:
    """Тот же импорт, но к правилу с ``not_empty`` добавлено ещё одно действие.

    Правило ``press_types`` срабатывает на ЛЮБОЕ непустое значение
    операции, поэтому его id попадает в ``matched_rule_ids`` всегда. Признаком
    распознавания он быть не может: узнаёт значение только действие, дающее
    результат по этому значению. Отсюда и проверка — сколько бы действий у
    такого правила ни было, нераспознанное значение обязано остаться
    ошибкой строки.
    """
    template_id, profile_id = await _seed_factory(session)
    rule = await session.scalar(
        select(RouteSelectionRule).where(
            RouteSelectionRule.profile_id == profile_id,
            RouteSelectionRule.code == "press_types",
        )
    )
    assert rule is not None, "предусловие: правило press_types создано"
    rule.actions = [*(rule.actions or []), action]
    await session.commit()

    plan = ProductionPlan(plan_no="PLAN-227-EXTRA", name="План 227 с новым действием")
    session.add(plan)
    await session.flush()
    result = await create_excel_import_change_set(
        session,
        filename="plan-227-extra.xlsx",
        content=_workbook(PLAN_ROWS),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        production_plan_id=plan.id,
        template_id=template_id,
        rule_profile_id=profile_id,
    )
    items = (
        await session.execute(
            select(PlanChangeItem)
            .where(PlanChangeItem.change_set_id == result["change_set_id"])
            .order_by(PlanChangeItem.id)
        )
    ).scalars().all()
    return {(item.after_data or {})["source_sku"]: item for item in items}


#: Действия, добавленные к правилу с ``not_empty``. Ни одно не узнаёт значение
#: операции: одно требует участок, другое пишет произвольное поле, третье —
#: действие, которого движок не знает вовсе. Признаком распознавания они быть
#: не могут, и нераспознанное значение обязано остаться ошибкой строки.
EXTRA_ACTIONS = [
    pytest.param({"action": "require_section", "section_code": "PRESSING"}, id="require_section"),
    pytest.param(
        {"action": "set_field", "path": "ctx.flagged", "value": True}, id="set_field"
    ),
    pytest.param({"action": "mark_possible_duplicate"}, id="unknown_action"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", EXTRA_ACTIONS)
async def test_not_empty_rule_with_extra_action_still_reports_unrecognized(
    session: AsyncSession, action: dict
) -> None:
    """Новое действие у правила с ``not_empty`` не отключает ошибку #227.

    ``not_empty`` срабатывает на любое непустое значение, поэтому такое
    правило всегда в ``matched_rule_ids``. Если бы «сработало» считалось
    признаком распознавания, ошибка ``route_operation_not_recognized``
    пропала бы молча — ровно тот дефект, который #227 и закрывал.
    """
    items = await _import_with_extra_action(session, action)

    unknown = items["ОП-1005"]
    assert OPERATION_CODE in (unknown.errors or []), (
        f"действие {action['action']!r} у правила с not_empty засчитало "
        f"непустое значение как распознанное: {unknown.errors}"
    )
    assert unknown.status == PlanChangeItemStatus.invalid

    # Узнанные значения ошибки не дают — новый action их не сломал.
    for sku in ("ОП-1001", "ОП-1002", "ОП-1003"):
        assert OPERATION_CODE not in (items[sku].errors or []), f"{sku}: {items[sku].errors}"
