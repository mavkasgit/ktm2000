from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import RouteRuleProfile
from app.seeds.canon.models import RouteRuleProfileDef
from app.seeds.route_rule_profiles import ROUTE_RULE_PROFILE_FIELD_MAP
from app.seeds.upsert import upsert_by_key


async def seed_route_rule_profile(
    db: AsyncSession,
    profile_def: RouteRuleProfileDef,
    *,
    import_template_id: int | None = None,
) -> RouteRuleProfile:
    """Upsert RouteRuleProfile by code. Returns the object with id set."""
    def resolve(row: RouteRuleProfileDef) -> dict:
        values: dict = {}
        if row.route_name_pattern is not None:
            values["route_name_pattern"] = row.route_name_pattern
        if import_template_id is not None:
            values["import_template_id"] = import_template_id
        values["excel_column_passport"] = [
            col.model_dump() for col in row.excel_column_passport
        ]
        return values

    result = await upsert_by_key(
        db,
        RouteRuleProfile,
        [profile_def],
        key_field="code",
        field_map=ROUTE_RULE_PROFILE_FIELD_MAP,
        resolve=resolve,
    )
    return result[profile_def.code]
