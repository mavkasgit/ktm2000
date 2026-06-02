from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup


async def seed_spgs(
    db: AsyncSession,
    spgs_data: list[dict],
    sections_map: dict[str, Section],
) -> int:
    """Upsert StorageProductionGroup records by code and bind sections.

    Returns count of SPGs upserted.
    """
    count = 0

    for data in spgs_data:
        section_codes = data["section_codes"]

        spg = await db.scalar(
            select(StorageProductionGroup).where(StorageProductionGroup.code == data["code"])
        )
        if spg is None:
            spg = StorageProductionGroup(
                code=data["code"],
                name=data["name"],
                description=data.get("description"),
                sort_order=data.get("sort_order", 0),
                is_active=True,
                icon=data.get("icon"),
                icon_color=data.get("icon_color"),
            )
            db.add(spg)
            await db.flush()
        else:
            spg.name = data["name"]
            spg.description = data.get("description")
            spg.sort_order = data.get("sort_order", 0)
            spg.is_active = True
            spg.icon = data.get("icon")
            spg.icon_color = data.get("icon_color")
            await db.flush()

        # Remove existing section bindings
        await db.execute(delete(SpgSection).where(SpgSection.spg_id == spg.id))

        # Add new bindings
        for idx, section_code in enumerate(section_codes):
            section = sections_map.get(section_code)
            if section is None:
                continue
            db.add(SpgSection(
                spg_id=spg.id,
                section_id=section.id,
                sort_order=idx * 10,
            ))

        count += 1

    await db.flush()
    return count
