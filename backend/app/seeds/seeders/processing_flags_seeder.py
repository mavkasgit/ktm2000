"""Seeder for ProcessingFlag reference catalog.

Flags that were previously boolean columns on Product (skip_shot_blast, is_laminated)
are now managed as rows in the processing_flags table (#17).
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import ProcessingFlag
from app.seeds.processing_flags import PROCESSING_FLAGS_DATA
from app.seeds.upsert import upsert_by_code

PROCESSING_FLAGS_FIELD_MAP = {
    "code": "code",
    "name": "name",
    "section_scope": "section_scope",
}


async def seed_processing_flags(db: AsyncSession) -> dict[str, ProcessingFlag]:
    """Upsert ProcessingFlag records. Returns map code → flag.

    is_active всегда True (данные справочника не несут флаг; исходный седер
    принудительно активировал строку при update).
    """
    return await upsert_by_code(
        db,
        ProcessingFlag,
        PROCESSING_FLAGS_DATA,
        key_field="code",
        field_map=PROCESSING_FLAGS_FIELD_MAP,
        resolve=lambda _row: {"is_active": True},
    )
