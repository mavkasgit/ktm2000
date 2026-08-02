from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import RouteRuleProfile
from app.seeds.canon.models import RouteRuleProfileDef


async def seed_route_rule_profile(
    db: AsyncSession,
    profile_def: RouteRuleProfileDef,
    *,
    import_template_id: int | None = None,
) -> RouteRuleProfile:
    """Upsert RouteRuleProfile by code. Returns the object with id set."""
    obj = await db.scalar(
        select(RouteRuleProfile).where(RouteRuleProfile.code == profile_def.code)
    )
    if obj is None:
        obj = RouteRuleProfile(
            code=profile_def.code,
            name=profile_def.name,
        )
        db.add(obj)
    else:
        obj.name = profile_def.name

    obj.is_active = profile_def.is_active
    obj.priority = profile_def.priority
    if profile_def.route_name_pattern is not None:
        obj.route_name_pattern = profile_def.route_name_pattern
    if import_template_id is not None:
        obj.import_template_id = import_template_id
    obj.excel_column_passport = [
        col.model_dump() for col in profile_def.excel_column_passport
    ]
    obj.excel_passport_meta = profile_def.excel_passport_meta
    obj.route_sections = profile_def.route_sections

    await db.flush()
    return obj
