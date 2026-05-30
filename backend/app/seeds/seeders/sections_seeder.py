from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import SectionOperation
from app.models.section import Section

SECTIONS_DATA = [
    {"code": "WH", "name": "Склад сырья", "sort_order": 10, "kind": "raw_stock", "icon": "Warehouse", "icon_color": "#F59E0B"},
    {"code": "DRILL", "name": "Сверловка", "sort_order": 20, "kind": "production", "icon": "Drill", "icon_color": "#3B82F6"},
    {"code": "PRESS", "name": "Пресс", "sort_order": 30, "kind": "production", "icon": "Anvil", "icon_color": "#EF4444"},
    {"code": "SHOT", "name": "Дробеструй", "sort_order": 40, "kind": "production", "icon": "SprayCan", "icon_color": "#6B7280"},
    {"code": "ANOD", "name": "Анодирование", "sort_order": 50, "kind": "production", "icon": "FlaskConical", "icon_color": "#06B6D4"},
    {"code": "WIP_WH", "name": "Склад полуфабриката", "sort_order": 60, "kind": "wip_stock", "icon": "Boxes", "icon_color": "#84CC16"},
    {"code": "SAW", "name": "Пила", "sort_order": 70, "kind": "production", "icon": "Fan", "icon_color": "#F97316"},
    {"code": "PACK", "name": "Упаковка", "sort_order": 80, "kind": "production", "icon": "Package", "icon_color": "#10B981"},
    {"code": "FG_WH", "name": "Склад готовой продукции", "sort_order": 90, "kind": "finished_stock", "icon": "Container", "icon_color": "#065F46"},
    {"code": "SHIPMENT", "name": "К отгрузке", "sort_order": 100, "kind": "finished_stock", "icon": "Truck", "icon_color": "#7C3AED"},
    {"code": "SENT", "name": "Отправлено", "sort_order": 110, "kind": "finished_stock", "icon": "CheckCircle", "icon_color": "#059669"},
]

# Operations for each section: (group_code, group_name, sort_order, op_code, op_name, is_significant, icon, icon_color, resolver_type, resolver_config)
# group_code=None means the operation has no group (standalone).
# op_code=None means this is a placeholder operation (resolved dynamically).
# resolver_type=None means the operation code is explicit (no resolution needed).

SECTION_OPS: dict[str, list[tuple[str | None, str | None, int, str | None, str, bool, str | None, str | None, str | None, dict]]] = {
    "WH": [
        ("WH", "Выдача сырья", 10, "ISSUE_RAW", "Выдача сырья", False, "Package", "#F59E0B", None, {}),
    ],
    "DRILL": [
        ("DRILL", "Сверловка", 10, "DRILL", "Сверловка", True, "Drill", "#3B82F6", None, {}),
    ],
    "PRESS": [
        ("PRESS", "Пресс", 10, "PRESS_WINDOW", "Окно", True, "LetterO", "#EF4444", None, {}),
        ("PRESS", "Пресс", 10, "PRESS_COMB", "Гребенка", True, "LetterSh", "#F97316", None, {}),
    ],
    "SHOT": [
        ("SHOT", "Дробеструй", 10, "SHOT", "Дробеструй", True, "SprayCan", "#6B7280", None, {}),
    ],
    "ANOD": [
        ("ANOD", "Анодирование", 10, "ANOD_01", "Серебро", True, None, "#C0C0C0", None, {}),
        ("ANOD", "Анодирование", 10, "ANOD_02", "Золото", True, None, "#FFD700", None, {}),
        ("ANOD", "Анодирование", 10, "ANOD_03", "Бронза", True, None, "#8B5A2B", None, {}),
        ("ANOD", "Анодирование", 10, "ANOD_05", "Чёрный", True, None, "#1C1C1C", None, {}),
        ("ANOD", "Анодирование", 10, "ANOD_06", "Шампань", True, None, "#F7E7CE", None, {}),
        ("ANOD", "Анодирование", 10, "ANOD_07", "Медь", True, None, "#CD5C5C", None, {}),
        ("ANOD", "Анодирование", 10, "ANOD_08", "Титан", True, None, "#878681", None, {}),

        ("PACK", "Упаковка", 20, "PACK_STRETCH", "Стрейч", True, None, "#0891B2", None, {}),
        ("PACK", "Упаковка", 20, "PACK_SPUNBOND", "Спанбонд", True, None, "#06B6D4", None, {}),
    ],
    "WIP_WH": [
        ("WIP_WH", "Передача на склад", 10, "MOVE_TO_WIP", "Передача на склад полуфабриката", False, "Truck", "#84CC16", None, {}),
    ],
    "SAW": [
        ("SAW", "Резка", 10, "SAW", "Резка на пиле", True, "Fan", "#F97316", None, {}),
    ],
    "PACK": [
        ("PACK", "Упаковка", 10, "PACK", "Упаковка", True, "Package", "#10B981", None, {}),
    ],
    "FG_WH": [
        ("FG_WH", "Склад ГП", 10, "FG_WH", "Склад готовой продукции", False, "Container", "#065F46", None, {}),
    ],
    "SHIPMENT": [
        ("SHIPMENT", "К отгрузке", 10, "SHIPMENT", "К отгрузке", False, "PackageOpen", "#8B5CF6", None, {}),
    ],
    "SENT": [
        ("SENT", "Отправлено", 10, "SENT", "Отправлено", False, "PackageCheck", "#EC4899", None, {}),
    ],
}


async def seed_sections(db: AsyncSession, force: bool = False) -> dict[str, Section]:
    """Upsert all sections by code. Returns {code: section} map."""
    result: dict[str, Section] = {}

    for data in SECTIONS_DATA:
        section = await db.scalar(select(Section).where(Section.code == data["code"]))
        if section is None:
            section = Section(**data, is_active=True)
            db.add(section)
            await db.flush()
        else:
            for key, value in data.items():
                setattr(section, key, value)
            section.is_active = True

        result[data["code"]] = section

    return result


async def seed_section_operations(db: AsyncSession, sections_map: dict[str, Section]) -> int:
    """Upsert SectionOperation records for each section. Returns count of operations."""
    count = 0

    for section_code, ops in SECTION_OPS.items():
        section = sections_map.get(section_code)
        if not section:
            continue

        for group_code, group_name, sort_order, op_code, op_name, is_sig, icon, icon_color, resolver_type, resolver_config in ops:
            # Skip placeholder operations with None operation_code — they can't be
            # stored in SectionOperation (operation_code is NOT NULL).
            # Resolver info for placeholders is stored on the first non-None operation
            # of the same group.
            if op_code is None:
                continue

            existing = await db.scalar(
                select(SectionOperation).where(
                    SectionOperation.section_id == section.id,
                    SectionOperation.operation_code == op_code,
                )
            )
            if existing:
                existing.operation_name = op_name
                existing.is_significant = is_sig
                existing.icon = icon
                existing.icon_color = icon_color
                existing.group_code = group_code
                existing.group_name = group_name
                existing.sort_order = sort_order
                existing.resolver_type = resolver_type
                existing.resolver_config = resolver_config
            else:
                db.add(SectionOperation(
                    section_id=section.id,
                    operation_code=op_code,
                    operation_name=op_name,
                    is_significant=is_sig,
                    icon=icon,
                    icon_color=icon_color,
                    group_code=group_code,
                    group_name=group_name,
                    sort_order=sort_order,
                    resolver_type=resolver_type,
                    resolver_config=resolver_config,
                ))
            count += 1

    await db.flush()
    return count
