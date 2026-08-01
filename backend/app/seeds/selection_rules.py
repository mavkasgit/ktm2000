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
            {"action": "require_section", "section_code": "RAW_STOCK"},
            {"action": "require_section", "section_code": "ANODIZING"},
            {"action": "require_section", "section_code": "FINISHED_STOCK"},
            {"action": "require_section", "section_code": "SHIPMENT"},
            {"action": "require_section", "section_code": "SHIPPED"},
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
            {"action": "require_section", "section_code": "DRILLING"},
            {"action": "require_section", "section_code": "PREP_STOCK"},
            {"action": "exclude_section", "section_code": "PRESSING"},
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
            {"action": "require_section", "section_code": "PRESSING"},
            {"action": "require_section", "section_code": "PREP_STOCK"},
            {"action": "exclude_section", "section_code": "DRILLING"},
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
            {"action": "require_section", "section_code": "PRESSING"},
            {"action": "require_section", "section_code": "PREP_STOCK"},
            {"action": "exclude_section", "section_code": "DRILLING"},
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
                "section_code": "PRESSING",
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
            {"action": "exclude_section", "section_code": "DRILLING"},
            {"action": "exclude_section", "section_code": "PRESSING"},
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
            {"action": "require_section", "section_code": "WIP_STOCK"},
            {"action": "require_section", "section_code": "SAWING"},
            {"action": "require_section", "section_code": "PACKING"},
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
            {"action": "exclude_section", "section_code": "WIP_STOCK"},
            {"action": "exclude_section", "section_code": "SAWING"},
            {"action": "exclude_section", "section_code": "PACKING"},
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
            {"action": "exclude_section", "section_code": "SHOT_BLAST"},
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
            {"action": "require_section", "section_code": "SHOT_BLAST"},
            {"action": "require_section", "section_code": "PREP_STOCK"},
        ],
    },
    {
        "code": "prep_stock_no_prep_path",
        "name": "Без подготовки — исключить склад подготовки",
        "profile_code": "packaging_map_rp",
        "priority": 580,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "empty", "value": None},
            {"source": "product", "field_path": "skip_shot_blast", "operator": "equals", "value": True},
        ],
        "condition_logic": "and",
        "actions": [
            {"action": "exclude_section", "section_code": "PREP_STOCK"},
        ],
    },

    # Normalize: extract color from source_name when Excel color column is empty
    {
        "code": "anod_color_from_source_name",
        "name": "Анод: цвет из наименования",
        "profile_code": "packaging_map_rp",
        "priority": 200,
        "is_active": True,
        "phase": "normalize",
        "conditions": [
            {"source": "payload", "field_path": "color", "operator": "empty", "value": None},
            {"source": "payload", "field_path": "source_name", "operator": "not_empty", "value": None},
        ],
        "condition_logic": "and",
        "actions": [
            {
                "action": "set_field_from_color_extraction",
                "target_field": "color",
                "source_field": "source_name",
            },
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
                "section_code": "ANODIZING",
                "group_code": "ANOD",
                "lookup_field": "color",
                "mapping": [
                    {"keyword": "анодсеребро", "operation_code": "ANOD_01"},
                    {"keyword": "анодтитан", "operation_code": "ANOD_08"},
                    {"keyword": "анодчерный", "operation_code": "ANOD_05"},
                    {"keyword": "анодчёрный", "operation_code": "ANOD_05"},
                    {"keyword": "анодшампань", "operation_code": "ANOD_06"},
                    {"keyword": "анодзолото", "operation_code": "ANOD_02"},
                    {"keyword": "анодбронза", "operation_code": "ANOD_03"},
                    {"keyword": "анодмедь", "operation_code": "ANOD_07"},
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

    # ===== resolve_signatures rules =====
    {
        "code": "output_kind_gp",
        "name": "Вид выпуска: ГП",
        "profile_code": "packaging_map_rp",
        "priority": 100,
        "is_active": True,
        "phase": "resolve_signatures",
        "conditions": [
            {"source": "ctx", "field_path": "included_sections", "operator": "contains", "value": "PACKING"},
            {"source": "ctx", "field_path": "included_sections", "operator": "contains", "value": "WIP_STOCK"},
            {"source": "ctx", "field_path": "included_sections", "operator": "contains", "value": "SAWING"},
        ],
        "condition_logic": "and",
        "actions": [
            {"action": "set_field", "path": "payload.output_kind", "value": "ГП"},
        ],
    },
    {
        "code": "output_kind_pf",
        "name": "Вид выпуска: П/Ф",
        "profile_code": "packaging_map_rp",
        "priority": 90,
        "is_active": True,
        "phase": "resolve_signatures",
        "conditions": [
            {"source": "ctx", "field_path": "included_sections", "operator": "not_contains", "value": "PACKING"},
            {"source": "ctx", "field_path": "included_sections", "operator": "not_contains", "value": "WIP_STOCK"},
            {"source": "ctx", "field_path": "included_sections", "operator": "not_contains", "value": "SAWING"},
        ],
        "condition_logic": "and",
        "actions": [
            {"action": "set_field", "path": "payload.output_kind", "value": "П/Ф"},
        ],
    },
    {
        "code": "shot_op_bez_operatsiy",
        "name": "Дробеструй: без операций",
        "profile_code": "packaging_map_rp",
        "priority": 100,
        "is_active": True,
        "phase": "resolve_signatures",
        "conditions": [
            {"source": "ctx", "field_path": "included_sections", "operator": "not_contains", "value": "SHOT_BLAST"},
        ],
        "actions": [
            {"action": "set_field", "path": "payload.shot_op", "value": "Без операций"},
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
                "section_code": "ANODIZING",
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
