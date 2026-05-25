"""Временный эндпоинт для загрузки стандартных участков.
Удалить после того как участки будут загружены на всех стендах."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.section import Section
from app.models.route import SectionOperation

router = APIRouter(prefix="/sections-seed", tags=["sections-seed"])


class SectionOut(BaseModel):
    id: int
    code: str
    name: str
    description: str | None = None
    sort_order: int
    is_active: bool
    kind: str
    icon: str | None = None
    icon_color: str | None = None


DEFAULTS = [
    {"code": "WH", "name": "Склад сырья", "sort_order": 10, "is_active": True, "kind": "raw_stock", "icon": "Warehouse", "icon_color": "#F59E0B"},
    {"code": "DRILL", "name": "Сверловка", "sort_order": 20, "is_active": True, "kind": "production", "icon": "Drill", "icon_color": "#3B82F6"},
    {"code": "PRESS", "name": "Пресс", "sort_order": 30, "is_active": True, "kind": "production", "icon": "Anvil", "icon_color": "#EF4444"},
    {"code": "SHOT", "name": "Дробеструй", "sort_order": 40, "is_active": True, "kind": "production", "icon": "SprayCan", "icon_color": "#6B7280"},
    {"code": "ANOD", "name": "Анодирование", "sort_order": 50, "is_active": True, "kind": "production", "icon": "FlaskConical", "icon_color": "#06B6D4"},
    {"code": "WIP_WH", "name": "Склад полуфабриката", "sort_order": 60, "is_active": True, "kind": "wip_stock", "icon": "Boxes", "icon_color": "#84CC16"},
    {"code": "SAW", "name": "Пила", "sort_order": 70, "is_active": True, "kind": "production", "icon": "Fan", "icon_color": "#F97316"},
    {"code": "PACK", "name": "Упаковка", "sort_order": 80, "is_active": True, "kind": "production", "icon": "Package", "icon_color": "#10B981"},
    {"code": "FG_WH", "name": "Склад готовой продукции", "sort_order": 90, "is_active": True, "kind": "finished_stock", "icon": "Container", "icon_color": "#065F46"},
    {
        "code": "SHIPMENT",
        "name": "К отгрузке",
        "description": "ГП и ПФ укладываемая в ящики",
        "sort_order": 100,
        "is_active": True,
        "kind": "finished_stock",
        "icon": "PackageOpen",
        "icon_color": "#8B5CF6",
    },
    {
        "code": "SENT",
        "name": "Отправлено",
        "description": "ГП и ПФ отправленная",
        "sort_order": 110,
        "is_active": True,
        "kind": "finished_stock",
        "icon": "PackageCheck",
        "icon_color": "#EC4899",
    },
]

# Операции по умолчанию для каждого участка
# Формат: (code, name, is_significant, icon, icon_color)
# Когда операция одна — повторяем иконку/цвет участка.
# Когда несколько — подбираем осмысленные иконки + цвета из палитры участка.
SECTION_OPS = {
    "WH": [
        # Участок: Warehouse, #F59E0B
        ("ISSUE_RAW", "Выдача сырья", False, "Package", "#F59E0B"),
    ],
    "DRILL": [
        # Участок: Drill, #3B82F6
        ("DRILL", "Сверловка", True, "Drill", "#3B82F6"),
    ],
    "PRESS": [
        # Участок: Anvil, #EF4444
        ("PRESS_WINDOW", "Пресс (окно)", True, "LetterO", "#EF4444"),
        ("PRESS_COMB", "Пресс (гребенка)", True, "LetterSh", "#F97316"),
    ],
    "SHOT": [
        # Участок: SprayCan, #6B7280
        ("SHOT", "Дробеструй", True, "SprayCan", "#6B7280"),
    ],
    "ANOD": [
        # Участок: FlaskConical, #06B6D4 — без иконок, только цветной кружок
        # Реальные цвета анодирования из ekranchik
        ("ANOD_01", "Серебро", True, None, "#C0C0C0"),
        ("ANOD_02", "Золото", True, None, "#FFD700"),
        ("ANOD_03", "Бронза", True, None, "#8B5A2B"),
        ("ANOD_05", "Чёрный", True, None, "#1C1C1C"),
        ("ANOD_06", "Шампань", True, None, "#F7E7CE"),
        ("ANOD_07", "Медь", True, None, "#CD5C5C"),
        ("ANOD_08", "Титан", True, None, "#878681"),
        # Упаковка на анодировании
        ("PACK_SPUNBOND", "Спанбонд", True, None, "#06B6D4"),
        ("PACK_STRETCH", "Стрейч", True, None, "#0891B2"),
    ],
    "WIP_WH": [
        # Участок: Boxes, #84CC16
        ("MOVE_TO_WIP", "Передача на склад полуфабриката", False, "Truck", "#84CC16"),
    ],
    "SAW": [
        # Участок: Fan, #F97316
        ("SAW", "Резка на пиле", True, "Fan", "#F97316"),
    ],
    "PACK": [
        # Участок: Package, #10B981
        ("PACK", "Упаковка", True, "Package", "#10B981"),
    ],
    "FG_WH": [
        # Участок: Container, #065F46
        ("FG_WH", "Склад готовой продукции", False, "Container", "#065F46"),
    ],
    "SHIPMENT": [
        # Участок: PackageOpen, #8B5CF6
        ("SHIPMENT", "К отгрузке", False, "PackageOpen", "#8B5CF6"),
    ],
    "SENT": [
        # Участок: PackageCheck, #EC4899
        ("SENT", "Отправлено", False, "PackageCheck", "#EC4899"),
    ],
}


@router.post("", response_model=list[SectionOut], status_code=status.HTTP_201_CREATED)
async def seed_sections(db: AsyncSession = Depends(get_db)) -> list[SectionOut]:
    """Создать или обновить стандартные участки и операции."""
    created = 0
    for d in DEFAULTS:
        existing = await db.scalar(select(Section).where(Section.code == d["code"]))
        if existing:
            for k, v in d.items():
                setattr(existing, k, v)
        else:
            db.add(Section(**d))
            created += 1
    await db.flush()

    # Сидим операции
    sections_result = await db.execute(select(Section))
    sections = {s.code: s for s in sections_result.scalars().all()}

    for section_code, ops in SECTION_OPS.items():
        section = sections.get(section_code)
        if not section:
            continue
        for op_code, op_name, is_sig, icon, icon_color in ops:
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
            else:
                db.add(SectionOperation(
                    section_id=section.id,
                    operation_code=op_code,
                    operation_name=op_name,
                    is_significant=is_sig,
                    icon=icon,
                    icon_color=icon_color,
                ))

    await db.flush()
    result = await db.execute(select(Section).order_by(Section.sort_order, Section.id))
    return [SectionOut.model_validate(i, from_attributes=True) for i in result.scalars().all()]
