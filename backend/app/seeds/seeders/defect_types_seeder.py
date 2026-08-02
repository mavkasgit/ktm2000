from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import DefectType
from app.seeds.canon.models import DefectTypeDef


async def seed_defect_types(
    db: AsyncSession,
    defect_types: list[DefectTypeDef],
) -> int:
    """Upsert DefectType records by code. Returns count of types upserted."""
    count = 0
    for type_def in defect_types:
        obj = await db.scalar(
            select(DefectType).where(DefectType.code == type_def.code)
        )
        if obj is None:
            obj = DefectType(
                code=type_def.code,
                name=type_def.name,
                category=type_def.category,
                severity=type_def.severity,
                requires_quality_decision=type_def.requires_quality_decision,
                is_active=type_def.is_active,
                description=type_def.description,
            )
            db.add(obj)
        else:
            obj.name = type_def.name
            obj.category = type_def.category
            obj.severity = type_def.severity
            obj.requires_quality_decision = type_def.requires_quality_decision
            obj.is_active = type_def.is_active
            obj.description = type_def.description
        count += 1

    await db.flush()
    return count
