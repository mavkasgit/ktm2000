from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import RouteRuleProfile


async def seed_route_rule_profile(
    db: AsyncSession,
    data: dict,
    *,
    import_template_id: int | None = None,
) -> RouteRuleProfile:
    """Upsert RouteRuleProfile by code. Returns the object with id set."""
    obj = await db.scalar(select(RouteRuleProfile).where(RouteRuleProfile.code == data["code"]))
    if obj is None:
        obj = RouteRuleProfile(
            code=data["code"],
            name=data["name"],
        )
        db.add(obj)
    else:
        obj.name = data["name"]

    obj.is_active = data.get("is_active", True)
    obj.priority = data.get("priority", 0)
    if "route_name_pattern" in data:
        obj.route_name_pattern = data["route_name_pattern"]
    if import_template_id is not None:
        obj.import_template_id = import_template_id
    if "excel_column_passport" in data:
        obj.excel_column_passport = data["excel_column_passport"]
    if "excel_passport_meta" in data:
        obj.excel_passport_meta = data["excel_passport_meta"]
    if "route_sections" in data:
        obj.route_sections = data["route_sections"]

    await db.flush()
    return obj
