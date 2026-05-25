from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_template import ImportTemplate


async def seed_import_template(db: AsyncSession, data: dict) -> ImportTemplate:
    """Upsert ImportTemplate by code. Returns the object with id set."""
    obj = await db.scalar(select(ImportTemplate).where(ImportTemplate.code == data["code"]))
    if obj is None:
        obj = ImportTemplate(
            code=data["code"],
            name=data["name"],
        )
        db.add(obj)
    else:
        obj.name = data["name"]

    obj.is_active = data.get("is_active", True)
    obj.sort_order = data.get("sort_order", 0)
    obj.column_mapping = data.get("column_mapping", {})
    obj.normalization_rules = data.get("normalization_rules", {})
    if "button_label" in data:
        obj.button_label = data["button_label"]
    if "description" in data:
        obj.description = data["description"]

    await db.flush()
    return obj
