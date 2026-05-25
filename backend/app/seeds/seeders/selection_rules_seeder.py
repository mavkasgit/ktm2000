from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import RouteRuleProfile, RouteSelectionRule
from app.models.section import Section


async def seed_selection_rules(
    db: AsyncSession,
    rules_data: list[dict],
    profile: RouteRuleProfile,
) -> int:
    """Upsert selection rules by code. Resolves section_code → section_id. Returns count."""
    # Load sections for code → id mapping
    sections_result = await db.execute(select(Section).where(Section.is_active.is_(True)))
    sections_by_code = {s.code: s for s in sections_result.scalars().all()}

    count = 0
    for rule_def in rules_data:
        # Build conditions
        conditions = []
        for cond in rule_def.get("conditions", []):
            conditions.append({
                "source": cond.get("source", "payload"),
                "field_path": cond.get("field_path", ""),
                "operator": cond.get("operator", ""),
                "value": cond.get("value"),
                "case_sensitive": False,
            })

        # Build actions — resolve section_code to section_id
        actions = []
        for action_def in rule_def.get("actions", []):
            section_code = action_def.get("section_code")
            if section_code and section_code not in sections_by_code:
                raise RuntimeError(f"Section '{section_code}' not found for rule '{rule_def['code']}'")

            action_dict = {
                "action": action_def["action"],
                "section_id": sections_by_code[section_code].id if section_code else None,
            }
            if "operation_code" in action_def:
                action_dict["operation_code"] = action_def["operation_code"]
            actions.append(action_dict)

        # Upsert by code
        rule = await db.scalar(select(RouteSelectionRule).where(RouteSelectionRule.code == rule_def["code"]))
        if rule is None:
            rule = RouteSelectionRule(code=rule_def["code"])
            db.add(rule)

        rule.profile_id = profile.id
        rule.name = rule_def["name"]
        rule.priority = rule_def["priority"]
        rule.is_active = rule_def.get("is_active", True)
        rule.phase = rule_def.get("phase", "route_select")
        rule.conditions = conditions
        rule.actions = actions
        count += 1

    await db.flush()
    return count
