from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.section import Section
from app.models.spg import SpgSection, SpgStorageKind, StorageProductionGroup
from app.seeds.canon.models import SPGDef


def _resolve_storage_kind(value: object) -> SpgStorageKind:
    """Convert seed value to SpgStorageKind enum, defaulting to wip."""
    if value is None:
        return SpgStorageKind.wip
    if isinstance(value, SpgStorageKind):
        return value
    return SpgStorageKind(str(value))


async def seed_spgs(
    db: AsyncSession,
    spgs_data: list[SPGDef],
    sections_map: dict[str, Section],
) -> int:
    """Upsert StorageProductionGroup records by code and bind sections.

    Returns count of SPGs upserted.
    """
    count = 0

    for spg_def in spgs_data:
        section_codes = spg_def.section_codes or []
        storage_kind = _resolve_storage_kind(spg_def.storage_kind)

        spg = await db.scalar(
            select(StorageProductionGroup).where(StorageProductionGroup.code == spg_def.code)
        )
        if spg is None:
            spg = StorageProductionGroup(
                code=spg_def.code,
                name=spg_def.name,
                description=spg_def.description,
                storage_kind=storage_kind,
                sort_order=spg_def.sort_order,
                is_active=True,
                icon=spg_def.icon,
                icon_color=spg_def.icon_color,
            )
            db.add(spg)
            await db.flush()
        else:
            spg.name = spg_def.name
            spg.description = spg_def.description
            spg.storage_kind = storage_kind
            spg.sort_order = spg_def.sort_order
            spg.is_active = True
            spg.icon = spg_def.icon
            spg.icon_color = spg_def.icon_color
            await db.flush()

        # Load existing bindings for this SPG, keyed by section_id
        existing_rows = (
            await db.execute(
                select(SpgSection).where(SpgSection.spg_id == spg.id)
            )
        ).scalars().all()
        existing_by_section = {row.section_id: row for row in existing_rows}

        # Apply seed bindings (insert new / update sort_order of existing),
        # but never touch manual bindings for sections not in the seed.
        for idx, section_code in enumerate(section_codes):
            section = sections_map.get(section_code)
            if section is None:
                continue
            sort_order = idx * 10

            # Section may already be bound to THIS spg (from a previous seed)
            # or, in the case of data drift, to ANOTHER spg. The unique
            # constraint on section_id means at most one binding exists.
            current = existing_by_section.get(section.id)
            if current is None:
                current = await db.scalar(
                    select(SpgSection).where(SpgSection.section_id == section.id)
                )

            if current is not None and current.spg_id == spg.id:
                # Already bound to this SPG — just refresh sort_order
                current.sort_order = sort_order
                continue

            if current is not None:
                # Bound to a different SPG (data drift): detach from old SPG
                # so the unique-on-section_id constraint lets us bind it here.
                await db.delete(current)

            db.add(SpgSection(
                spg_id=spg.id,
                section_id=section.id,
                sort_order=sort_order,
            ))
            existing_by_section[section.id] = None  # type: ignore[assignment]

        # NOTE: bindings for sections that are not in `section_codes` are
        # intentionally preserved — those are manual user bindings (e.g. a
        # user-created section attached to this ГХП via the UI) and must
        # survive a re-seed.

        count += 1

    await db.flush()
    return count
