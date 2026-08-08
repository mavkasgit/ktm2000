from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_template import ImportTemplate
from app.seeds.upsert import upsert_by_code

IMPORT_TEMPLATE_FIELD_MAP = {
    "code": "code",
    "name": "name",
    "is_active": "is_active",
    "sort_order": "sort_order",
    "column_mapping": "column_mapping",
}


def _resolve_import_template(data: dict[str, Any]) -> dict[str, Any]:
    """Optional-поля шаблона: button_label/description только если заданы."""
    values: dict[str, Any] = {}
    for key in ("button_label", "description"):
        if data.get(key) is not None:
            values[key] = data[key]
    return values


async def seed_import_template(db: AsyncSession, data: dict) -> ImportTemplate:
    """Upsert ImportTemplate by code. Returns the object with id set."""
    result = await upsert_by_code(
        db,
        ImportTemplate,
        [data],
        key_field="code",
        field_map=IMPORT_TEMPLATE_FIELD_MAP,
        resolve=_resolve_import_template,
    )
    return result[data["code"]]
