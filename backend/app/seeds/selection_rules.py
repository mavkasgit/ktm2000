from __future__ import annotations

SELECTION_RULES = [
    {
        "code": "global_core_sections",
        "name": "Базовые участки маршрута",
        "profile_code": "packaging_map_rp",
        "priority": 1000,
        "is_active": True,
        "phase": "route_select",
        "conditions": [],
        "actions": [
            {"action": "require_section", "section_code": "WH"},
            {"action": "require_section", "section_code": "ANOD"},
            {"action": "require_section", "section_code": "FG_WH"},
            {"action": "require_section", "section_code": "SHIPMENT"},
            {"action": "require_section", "section_code": "SENT"},
        ],
    },
    {
        "code": "global_drill",
        "name": "Операция сверловки",
        "profile_code": "packaging_map_rp",
        "priority": 900,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "excel", "field_path": "operation", "operator": "contains", "value": "сверл"},
        ],
        "actions": [
            {"action": "require_section", "section_code": "DRILL"},
            {"action": "exclude_section", "section_code": "PRESS"},
        ],
    },
    {
        "code": "global_press_window",
        "name": "Операция пресса: окно",
        "profile_code": "packaging_map_rp",
        "priority": 890,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "excel", "field_path": "operation", "operator": "contains", "value": "окн"},
        ],
        "actions": [
            {"action": "require_section", "section_code": "PRESS", "operation_code": "PRESS_WINDOW"},
            {"action": "exclude_section", "section_code": "DRILL"},
        ],
    },
    {
        "code": "global_press_comb",
        "name": "Операция пресса: гребенка",
        "profile_code": "packaging_map_rp",
        "priority": 880,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "excel", "field_path": "operation", "operator": "contains", "value": "греб"},
        ],
        "actions": [
            {"action": "require_section", "section_code": "PRESS", "operation_code": "PRESS_COMB"},
            {"action": "exclude_section", "section_code": "DRILL"},
        ],
    },
    {
        "code": "global_empty_primary",
        "name": "Без первичной операции",
        "profile_code": "packaging_map_rp",
        "priority": 800,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "excel", "field_path": "operation", "operator": "empty", "value": None},
        ],
        "actions": [
            {"action": "exclude_section", "section_code": "DRILL"},
            {"action": "exclude_section", "section_code": "PRESS"},
        ],
    },
    {
        "code": "global_fg_branch",
        "name": "Готовая продукция",
        "profile_code": "packaging_map_rp",
        "priority": 700,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "excel", "field_path": "output_kind", "operator": "equals", "value": "ГП"},
        ],
        "actions": [
            {"action": "require_section", "section_code": "WIP_WH"},
            {"action": "require_section", "section_code": "SAW"},
            {"action": "require_section", "section_code": "PACK"},
        ],
    },
    {
        "code": "global_sf_branch",
        "name": "Полуфабрикат к отгрузке",
        "profile_code": "packaging_map_rp",
        "priority": 700,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "excel", "field_path": "output_kind", "operator": "equals", "value": "П/Ф"},
        ],
        "actions": [
            {"action": "exclude_section", "section_code": "WIP_WH"},
            {"action": "exclude_section", "section_code": "SAW"},
            {"action": "exclude_section", "section_code": "PACK"},
        ],
    },
    {
        "code": "global_product_skip_shot",
        "name": "Продукт без дробеструя",
        "profile_code": "packaging_map_rp",
        "priority": 600,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "product", "field_path": "skip_shot_blast", "operator": "equals", "value": True},
        ],
        "actions": [
            {"action": "exclude_section", "section_code": "SHOT"},
        ],
    },
    {
        "code": "global_product_with_shot",
        "name": "Продукт с дробеструем",
        "profile_code": "packaging_map_rp",
        "priority": 590,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "product", "field_path": "skip_shot_blast", "operator": "not_equals", "value": True},
        ],
        "actions": [
            {"action": "require_section", "section_code": "SHOT"},
        ],
    },
]
