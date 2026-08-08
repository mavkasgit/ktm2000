from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import DefectType
from app.seeds.canon.models import DefectTypeDef
from app.seeds.canon.quality_data import DEFECT_TYPES_FIELD_MAP
from app.seeds.upsert import upsert_by_key


async def seed_defect_types(
    db: AsyncSession,
    defect_types: list[DefectTypeDef],
) -> int:
    """Upsert DefectType records by code. Returns count of types upserted."""
    result = await upsert_by_key(
        db,
        DefectType,
        defect_types,
        key_field="code",
        field_map=DEFECT_TYPES_FIELD_MAP,
    )
    return len(result)
