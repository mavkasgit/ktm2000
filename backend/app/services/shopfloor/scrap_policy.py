"""Find-or-create SCRAP-секции по объекту канона ScrapPolicy (тикет #132).

Единственный владелец шва «канон → справочник секций»: и complete_task
(operations_tasks), и defect_decide (operations_defects) резолвят
SCRAP-участок только через этот модуль — дубль find-or-create из
operations_defects удалён.

Данные политики приходят из composition root (ADR-0004 §5, ADR-0007):
сервис не резолвит PlantConfig сам. Запись в справочник из операционного
пути сохраняется (сид мог не выполняться), но живёт за этим одним швом.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.section import Section
from app.seeds.canon.models import ScrapPolicy


async def find_or_create_scrap_section_id(
    db: AsyncSession,
    *,
    scrap_policy: ScrapPolicy | None,
) -> int:
    """Найти SCRAP-секцию по типу из политики; при отсутствии — создать.

    Args:
        db: Асинхронная сессия БД.
        scrap_policy: Объект канона ``plant_config.production.scrap_policy``.

    Returns:
        Id найденной либо созданной секции.

    Raises:
        ValueError: если политика не передана — брак без политики не
            регистрируется, данные обязаны прийти из composition root.
    """
    if scrap_policy is None:
        raise ValueError("scrap policy data is required when registering scrap")

    scrap_loc = await db.scalar(
        select(Section.id).where(Section.type == scrap_policy.section_type).limit(1)
    )
    if scrap_loc is not None:
        return scrap_loc

    scrap_sec = Section(
        code=scrap_policy.code,
        name=scrap_policy.name,
        type=scrap_policy.section_type,
        is_active=True,
        sort_order=scrap_policy.sort_order,
    )
    db.add(scrap_sec)
    await db.flush()
    return scrap_sec.id
