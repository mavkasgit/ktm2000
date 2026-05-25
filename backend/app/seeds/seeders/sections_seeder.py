from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    {"code": "SHIPMENT", "name": "К отгрузке", "sort_order": 100, "kind": "shipment", "icon": "Truck", "icon_color": "#7C3AED"},
    {"code": "SENT", "name": "Отправлено", "sort_order": 110, "kind": "sent", "icon": "CheckCircle", "icon_color": "#059669"},
]


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
