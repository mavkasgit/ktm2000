from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.route import RouteRuleProfile, RouteSelectionRule
from app.models.section import Section
from app.seeds.canon.models import SelectionRuleDef


async def seed_selection_rules(
    db: AsyncSession,
    rules_data: list[SelectionRuleDef],
    profile: RouteRuleProfile,
) -> int:
    """Upsert selection rules by code. Resolves section_code → section_id. Returns count."""
    # Load sections for code → id mapping
    sections_result = await db.execute(select(Section).where(Section.is_active.is_(True)))
    sections_by_code = {s.code: s for s in sections_result.scalars().all()}

    count = 0
    for rule_def in rules_data:
        # Build conditions from typed models
        conditions = []
        for cond in rule_def.conditions:
            conditions.append({
                "source": cond.source,
                "field_path": cond.field_path,
                "operator": cond.operator,
                "value": cond.value,
                "case_sensitive": cond.case_sensitive,
            })

        # Build actions — resolve section_code to section_id
        actions = []
        for action_def in rule_def.actions:
            section_code = getattr(action_def, "section_code", None)
            if section_code and section_code not in sections_by_code:
                raise RuntimeError(f"Section '{section_code}' not found for rule '{rule_def.code}'")

            action_dict = action_def.model_dump()
            action_dict["section_id"] = (
                sections_by_code[section_code].id if section_code else None
            )
            actions.append(action_dict)

        # Upsert by code
        rule = await db.scalar(select(RouteSelectionRule).where(RouteSelectionRule.code == rule_def.code))
        if rule is None:
            rule = RouteSelectionRule(code=rule_def.code)
            db.add(rule)

        rule.profile_id = profile.id
        rule.name = rule_def.name
        rule.priority = rule_def.priority
        rule.is_active = rule_def.is_active
        rule.phase = rule_def.phase
        rule.conditions = conditions
        rule.actions = actions
        flag_modified(rule, "conditions")
        flag_modified(rule, "actions")
        count += 1

    await db.flush()
    return count
