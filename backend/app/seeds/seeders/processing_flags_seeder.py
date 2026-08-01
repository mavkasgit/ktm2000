"""Seeder for ProcessingFlag reference catalog.

Flags that were previously boolean columns on Product (skip_shot_blast, is_laminated)
are now managed as rows in the processing_flags table (#17).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import ProcessingFlag

# code, name, section_scope
PROCESSING_FLAGS_DATA: list[dict[str, str | None]] = [
    {"code": "skip_shot_blast", "name": "Пропуск дробеструя", "section_scope": "SHOT_BLAST"},
    {"code": "is_laminated", "name": "Ламинирование", "section_scope": None},
]


async def seed_processing_flags(db: AsyncSession) -> dict[str, ProcessingFlag]:
    """Upsert ProcessingFlag records. Returns map code → flag."""
    flags_map: dict[str, ProcessingFlag] = {}
    for data in PROCESSING_FLAGS_DATA:
        flag = await db.scalar(select(ProcessingFlag).where(ProcessingFlag.code == data["code"]))
        if flag is None:
            flag = ProcessingFlag(**data)
            db.add(flag)
            await db.flush()
        else:
            flag.name = data["name"]
            flag.section_scope = data["section_scope"]
            flag.is_active = True
        flags_map[flag.code] = flag
    return flags_map
