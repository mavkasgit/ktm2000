from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.seeds.import_templates import IMPORT_TEMPLATES
from app.seeds.route_rule_profiles import ROUTE_RULE_PROFILES
from app.seeds.routes import ROUTES
from app.seeds.selection_rules import SELECTION_RULES
from app.seeds.spgs import SPGS_DATA
from app.seeds.seeders.cleanup_seeder import clear_generated_production_data
from app.seeds.seeders.dimension_types_seeder import seed_dimension_types
from app.seeds.seeders.import_template_seeder import seed_import_template
from app.seeds.seeders.route_rule_profile_seeder import seed_route_rule_profile
from app.seeds.seeders.routes_seeder import seed_routes, seed_production_routes_from_profiles
from app.seeds.seeders.sections_seeder import seed_section_operations, seed_sections
from app.seeds.seeders.selection_rules_seeder import seed_selection_rules
from app.seeds.seeders.spgs_seeder import seed_spgs
from app.seeds.seeders.users_seeder import seed_users


async def run_full_seed(db: AsyncSession, force: bool = False) -> dict:
    """Seed all reference data in one transaction.

    Returns counters for each entity type.
    """
    result: dict = {}

    if force:
        result["cleanup"] = await clear_generated_production_data(db)

    # 0. System user + demo users (system is also seeded in migration 001)
    users_map = await seed_users(db)
    result["users"] = len(users_map)

    # 1. Sections (required by routes)
    sections_map = await seed_sections(db)
    result["sections"] = len(sections_map)

    # 1.1. Section operations
    ops_count = await seed_section_operations(db, sections_map)
    result["section_operations"] = ops_count

    # 1.2. Storage Production Groups (SPG)
    spgs_count = await seed_spgs(db, SPGS_DATA, sections_map)
    result["spgs"] = spgs_count

    # 1.2.1. Dimension types + length_mm bindings for existing products
    dimensions_result = await seed_dimension_types(db)
    result["dimension_types"] = dimensions_result["dimension_types"]
    result["product_dimensions"] = dimensions_result["product_dimensions"]

    # 1.3. ImportTemplate (needed by profile); сеем все шаблоны (#15):
    # план «Упаковочная карта РП» + остатки «Остатки КТМ».
    templates_by_code: dict[str, object] = {}
    for template_data in IMPORT_TEMPLATES:
        tpl = await seed_import_template(db, template_data)
        templates_by_code[tpl.code] = tpl
    if not templates_by_code:
        raise RuntimeError("No import templates defined")
    result["import_templates"] = len(templates_by_code)

    # 1.3. RouteRuleProfile (needs template.id); сеем все профили (#12):
    # каждый профиль привязан к шаблону через import_template_code.
    if not ROUTE_RULE_PROFILES:
        raise RuntimeError("No route rule profiles defined")
    profiles_by_code: dict[str, object] = {}
    for profile_data in ROUTE_RULE_PROFILES:
        template_code = profile_data.get("import_template_code")
        template_obj = templates_by_code.get(template_code) if template_code else None
        profile = await seed_route_rule_profile(
            db,
            profile_data,
            import_template_id=template_obj.id if template_obj else None,
        )
        profiles_by_code[profile.code] = profile
    result["route_rule_profiles"] = len(profiles_by_code)

    # 1.4. ProductionRoutes from RouteRuleProfile (ONE step per section)
    # Must run AFTER profile creation so lookup by profile.code/name works for idempotency
    dynamic_routes_count = await seed_production_routes_from_profiles(db)
    result["routes"] = dynamic_routes_count

    # 1.5. Static universal route (contains all sections, filtered by rules)
    if ROUTES:
        static_routes = await seed_routes(db, ROUTES, force=force)
        result["routes"] += len(static_routes)

    # 2. ImportTemplate and profile already seeded above (moved up for dependency order)

    # 3. Routes (static routes replaced by dynamic production routes above)

    # 4. SelectionRules (needs profile); group by profile_code (#12)
    rules_by_profile: dict[str, list[dict]] = {}
    for rule_def in SELECTION_RULES:
        pcode = rule_def.get("profile_code", "")
        rules_by_profile.setdefault(pcode, []).append(rule_def)

    total_rules = 0
    for pcode, profile_rules in rules_by_profile.items():
        target_profile = profiles_by_code.get(pcode)
        if target_profile is None:
            raise RuntimeError(f"Profile '{pcode}' not found for selection rules")
        total_rules += await seed_selection_rules(db, profile_rules, target_profile)
    result["selection_rules"] = total_rules

    return result
