from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_template import ImportTemplate
from app.seeds.upsert import upsert_by_code

IMPORT_TEMPLATE_FIELD_MAP = {
    "code": "code",
    "name": "name",
}


def _resolve_import_template(data: dict[str, Any]) -> dict[str, Any]:
    """Необязательные и дефолтные поля шаблона.

    is_active/sort_order/column_mapping имеют дефолты (как в исходном седере);
    button_label/description задаются только если присутствуют в данных.
    """
    values: dict[str, Any] = {
        "is_active": data.get("is_active", True),
        "sort_order": data.get("sort_order", 0),
        "column_mapping": data.get("column_mapping", {}),
    }
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
