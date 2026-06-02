from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.seeds.import_templates import IMPORT_TEMPLATES
from app.seeds.route_rule_profiles import ROUTE_RULE_PROFILES
from app.seeds.routes import ROUTES
from app.seeds.selection_rules import SELECTION_RULES
from app.seeds.spgs import SPGS_DATA
from app.seeds.seeders.cleanup_seeder import clear_generated_production_data
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

    # 0. System user (required by dev-mode _fake_user)
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

    # 1.3. ImportTemplate (needed by profile)
    template_data = IMPORT_TEMPLATES[0] if IMPORT_TEMPLATES else None
    if template_data is None:
        raise RuntimeError("No import templates defined")
    template = await seed_import_template(db, template_data)
    result["import_templates"] = 1

    # 1.3. RouteRuleProfile (needs template.id)
    profile_data = ROUTE_RULE_PROFILES[0] if ROUTE_RULE_PROFILES else None
    if profile_data is None:
        raise RuntimeError("No route rule profiles defined")
    profile = await seed_route_rule_profile(
        db,
        profile_data,
        import_template_id=template.id,
    )
    result["route_rule_profiles"] = 1

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

    # 4. SelectionRules (needs profile)
    rules_count = await seed_selection_rules(db, SELECTION_RULES, profile)
    result["selection_rules"] = rules_count

    return result
