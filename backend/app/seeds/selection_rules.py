from __future__ import annotations

SELECTION_RULES = [
    {
        "code": "core_sections",
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
        "code": "drill",
        "name": "Операция сверловки",
        "profile_code": "packaging_map_rp",
        "priority": 900,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "contains", "value": "сверл"},
        ],
        "actions": [
            {"action": "require_section", "section_code": "DRILL"},
            {"action": "exclude_section", "section_code": "PRESS"},
        ],
    },
    {
        "code": "press_section",
        "name": "Пресс: участок маршрута",
        "profile_code": "packaging_map_rp",
        "priority": 850,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "contains", "value": "окн"},
            {"source": "payload", "field_path": "operation", "operator": "not_contains", "value": "сверл"},
        ],
        "condition_logic": "and",
        "actions": [
            {"action": "require_section", "section_code": "PRESS"},
            {"action": "exclude_section", "section_code": "DRILL"},
        ],
    },
    {
        "code": "press_section_comb",
        "name": "Пресс гребёнка: участок маршрута",
        "profile_code": "packaging_map_rp",
        "priority": 850,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "contains", "value": "греб"},
            {"source": "payload", "field_path": "operation", "operator": "not_contains", "value": "сверл"},
        ],
        "condition_logic": "and",
        "actions": [
            {"action": "require_section", "section_code": "PRESS"},
            {"action": "exclude_section", "section_code": "DRILL"},
        ],
    },
    {
        "code": "press_types",
        "name": "Пресс: определение типа",
        "profile_code": "packaging_map_rp",
        "priority": 100,
        "is_active": True,
        "phase": "resolve_operations",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "not_empty", "value": None},
        ],
        "actions": [
            {
                "action": "set_operation_by_mapping",
                "section_code": "PRESS",
                "group_code": "PRESS",
                "lookup_field": "operation",
                "mapping": [
                    {"keyword": "окн", "operation_code": "PRESS_WINDOW"},
                    {"keyword": "греб", "operation_code": "PRESS_COMB"},
                ],
            },
        ],
    },
    {
        "code": "empty_primary",
        "name": "Без первичной операции",
        "profile_code": "packaging_map_rp",
        "priority": 800,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "empty", "value": None},
        ],
        "actions": [
            {"action": "exclude_section", "section_code": "DRILL"},
            {"action": "exclude_section", "section_code": "PRESS"},
        ],
    },
    {
        "code": "pack_stretch_branch",
        "name": "Стрейч упаковка — полный маршрут (ГП)",
        "profile_code": "packaging_map_rp",
        "priority": 700,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "output_kind", "operator": "contains", "value": "ГП"},
        ],
        "actions": [
            {"action": "require_section", "section_code": "WIP_WH"},
            {"action": "require_section", "section_code": "SAW"},
            {"action": "require_section", "section_code": "PACK"},
        ],
    },
    {
        "code": "pack_spunbond_branch",
        "name": "Спанбонд упаковка — без промежуточных этапов (П/ф)",
        "profile_code": "packaging_map_rp",
        "priority": 700,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "output_kind", "operator": "contains", "value": "П/ф"},
        ],
        "actions": [
            {"action": "exclude_section", "section_code": "WIP_WH"},
            {"action": "exclude_section", "section_code": "SAW"},
            {"action": "exclude_section", "section_code": "PACK"},
        ],
    },
    {
        "code": "product_skip_shot",
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
        "code": "product_with_shot",
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

    # ANOD operation resolution — consolidated color mapping
    {
        "code": "anod_colors",
        "name": "Анод: определение цвета",
        "profile_code": "packaging_map_rp",
        "priority": 100,
        "is_active": True,
        "phase": "resolve_operations",
        "conditions": [
            {"source": "payload", "field_path": "color", "operator": "not_empty", "value": None},
        ],
        "actions": [
            {
                "action": "set_operation_by_mapping",
                "section_code": "ANOD",
                "group_code": "ANOD",
                "lookup_field": "color",
                "mapping": [
                    {"keyword": "серебр", "operation_code": "ANOD_01"},
                    {"keyword": "золот", "operation_code": "ANOD_02"},
                    {"keyword": "бронз", "operation_code": "ANOD_03"},
                    {"keyword": "чёрн", "operation_code": "ANOD_05"},
                    {"keyword": "черн", "operation_code": "ANOD_05"},
                    {"keyword": "шампань", "operation_code": "ANOD_06"},
                    {"keyword": "мед", "operation_code": "ANOD_07"},
                    {"keyword": "титан", "operation_code": "ANOD_08"},
                ],
            },
        ],
    },

    # PACK operation resolution — consolidated packaging type mapping
    {
        "code": "pack_types",
        "name": "Упаковка: определение типа",
        "profile_code": "packaging_map_rp",
        "priority": 100,
        "is_active": True,
        "phase": "resolve_operations",
        "conditions": [
            {"source": "payload", "field_path": "output_kind", "operator": "not_empty", "value": None},
        ],
        "actions": [
            {
                "action": "set_operation_by_mapping",
                "section_code": "ANOD",
                "group_code": "PACK",
                "lookup_field": "output_kind",
                "mapping": [
                    {"keyword": "ГП", "operation_code": "PACK_STRETCH"},
                    {"keyword": "П/ф", "operation_code": "PACK_SPUNBOND"},
                ],
            },
        ],
    },
]
