"""Единый классификатор: «цех» vs. «склад» vs. «транзит».

Содержит функции для:
- Классификации ``Section`` (production / storage)
- Классификации ``SectionOperation`` (production / transport)
- Классификации ``RouteStage`` (production / transit)
- Построения display-имени для transit-этапа

Это единственная точка принятия решения «что считать pass-through» в системе.
Все остальные сервисы (``common.build_completed_stages_json``,
``plan_generation._resolve_route_stage_operation_name``, ``route_builder``,
API ``/api/sections/all/operations``) должны звать эти функции вместо собственных
ad-hoc эвристик.

Это также единственный модуль, которому позволено знать строковые литералы
``Section.type``.  Остальной код обязан звать предикаты (``is_production_section``,
``is_storage_section``, ``is_stock_section``) либо ссылаться на экспортируемые
константы/наборы — прямые сравнения ``section.type == "..."`` вне этого файла
запрещены (см. ``tests/test_section_type_literals_arch.py``).

Тип ``"quarantine"`` исключён из наборов: ни модель (``Section.type`` — простой
``String(20)`` без CHECK/enum), ни миграции, ни сиды, ни db-триггеры
(``app/db/triggers.py`` допускает только raw/wip/finished/scrap) не заводят такой
участок, поэтому классификация по нему была мёртвым кодом и расхождением с триггерами.
"""
from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import RouteStage
from app.models.section import Section


STAGE_KIND_PRODUCTION = "production"
STAGE_KIND_TRANSIT = "transit"

OPERATION_TYPE_PRODUCTION = "production"
OPERATION_TYPE_TRANSPORT = "transport"

# Единственное место в кодовой базе, где живут строковые литералы Section.type.
SECTION_TYPE_PRODUCTION = "production"
SECTION_TYPE_RAW_STOCK = "raw_stock"
SECTION_TYPE_WIP_STOCK = "wip_stock"
SECTION_TYPE_FINISHED_STOCK = "finished_stock"
SECTION_TYPE_SCRAP = "scrap"

# Все склады-хранилища (raw/wip/finished/scrap): участки, где остаток лежит «на
# полке», а не обрабатывается. Это же множество проверяют db-триггеры.
STORAGE_TYPES = frozenset({
    SECTION_TYPE_RAW_STOCK,
    SECTION_TYPE_WIP_STOCK,
    SECTION_TYPE_FINISHED_STOCK,
    SECTION_TYPE_SCRAP,
})

# Склады оборачиваемого запаса (без scrap): откуда сырьё/полуфабрикат реально
# перетекает по маршруту через Transfer. Брак (scrap) — тупик, его сюда не включаем.
STOCK_TYPES = frozenset({
    SECTION_TYPE_RAW_STOCK,
    SECTION_TYPE_WIP_STOCK,
    SECTION_TYPE_FINISHED_STOCK,
})


def is_storage_section(section: Section | None) -> bool:
    """``True`` если секция — это место хранения (склад), а не цех."""
    if section is None:
        return False
    return section.type in STORAGE_TYPES


def is_stock_section(section: Section | None) -> bool:
    """``True`` если секция — склад оборачиваемого запаса (raw/wip/finished, без scrap).

    Отличается от ``is_storage_section`` тем, что брак (``scrap``) не считается
    источником передач по маршруту.
    """
    if section is None:
        return False
    return section.type in STOCK_TYPES


def is_production_section(section: Section | None) -> bool:
    """``True`` если секция — это цех (место реальной работы)."""
    if section is None:
        return False
    return section.type == SECTION_TYPE_PRODUCTION


def classify_section_role(section: Section | None) -> str:
    """Возвращает роль секции: ``'production'`` или ``'storage'``."""
    if is_storage_section(section):
        return "storage"
    return "production"


def is_transit_stage(stage: RouteStage | None) -> bool:
    """``True`` если этап маршрута — транзитный (хранение, а не работа)."""
    if stage is None:
        return False
    return stage.stage_kind == STAGE_KIND_TRANSIT


def is_production_stage(stage: RouteStage | None) -> bool:
    """``True`` если этап — реальное производство (цех)."""
    if stage is None:
        return False
    return stage.stage_kind == STAGE_KIND_PRODUCTION and stage.section_id is not None


def stage_display_name(stage: RouteStage, storage_section: Section | None) -> str:
    """Человекочитаемое имя этапа для UI.

    Для ``production`` этапов возвращает имя секции (цеха).
    Для ``transit`` этапов — ``"Хранение: {name}"`` или ``"Транзит через {name}"``.
    """
    if is_transit_stage(stage):
        if storage_section is None:
            return "Транзит"
        return f"Хранение: {storage_section.name}"
    return stage.section.name if stage.section else ""


def infer_stage_kind(
    *,
    section: Section | None,
    storage_section_id: int | None = None,
) -> str:
    """Определить ``stage_kind`` по секции/контексту (для построения маршрута).

    Если указан ``storage_section_id`` или секция — склад, то ``transit``.
    Иначе ``production``.
    """
    if storage_section_id is not None:
        return STAGE_KIND_TRANSIT
    if is_storage_section(section):
        return STAGE_KIND_TRANSIT
    return STAGE_KIND_PRODUCTION


async def classify_stages(
    db: AsyncSession,
    stages: Iterable[RouteStage],
) -> tuple[list[RouteStage], list[RouteStage]]:
    """Разделить этапы на ``(production_stages, transit_stages)``.

    Единая функция-источник правды.  Использует ``stage.stage_kind`` и
    ``stage.storage_section_id`` — никаких ad-hoc проверок ``is_significant``
    или ``Section.type`` вне этого модуля.
    """
    stage_list = list(stages)
    if not stage_list:
        return [], []

    storage_ids = {s.storage_section_id for s in stage_list if s.storage_section_id}
    storage_sections: dict[int, Section] = {}
    if storage_ids:
        rows = (await db.execute(
            select(Section).where(Section.id.in_(storage_ids))
        )).scalars().all()
        storage_sections = {s.id: s for s in rows}

    production: list[RouteStage] = []
    transit: list[RouteStage] = []
    for stage in stage_list:
        if is_transit_stage(stage):
            transit.append(stage)
        else:
            production.append(stage)

    return production, transit


__all__ = [
    "STAGE_KIND_PRODUCTION",
    "STAGE_KIND_TRANSIT",
    "OPERATION_TYPE_PRODUCTION",
    "OPERATION_TYPE_TRANSPORT",
    "SECTION_TYPE_PRODUCTION",
    "SECTION_TYPE_RAW_STOCK",
    "SECTION_TYPE_WIP_STOCK",
    "SECTION_TYPE_FINISHED_STOCK",
    "SECTION_TYPE_SCRAP",
    "STORAGE_TYPES",
    "STOCK_TYPES",
    "is_storage_section",
    "is_stock_section",
    "is_production_section",
    "classify_section_role",
    "is_transit_stage",
    "is_production_stage",
    "stage_display_name",
    "infer_stage_kind",
    "classify_stages",
]
