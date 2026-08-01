from app.seeds.import_templates import IMPORT_TEMPLATES
from app.seeds.route_rule_profiles import ROUTE_RULE_PROFILES
from app.seeds.routes import ROUTES
from app.seeds.selection_rules import SELECTION_RULES
from app.seeds.spgs import SPGS_DATA

# Типизированный канон (ADR-0004): сервисы импортируют отсюда, не из plant_policies.
from app.seeds.canon import (
    PlantConfig,
    build_plant_config,
    get_display_config,
    get_plant_config,
)

__all__ = [
    "IMPORT_TEMPLATES",
    "PlantConfig",
    "ROUTE_RULE_PROFILES",
    "ROUTES",
    "SELECTION_RULES",
    "SPGS_DATA",
    "build_plant_config",
    "get_display_config",
    "get_plant_config",
]
