from __future__ import annotations

# One universal route containing all sections.
# Selection rules dynamically exclude/include sections and resolve operations.
ROUTES = [
    {
        "code": "universal_rp",
        "name": "Универсальный маршрут РП",
        "description": "Содержит все участки — правила выбора исключают ненужные динамически",
        "is_active": True,
        "sort_order": 1000,
        "steps": [
            {"section_code": "RAW_STOCK", "sequence": 1, "operation_code": None, "operation_name": ""},
            {"section_code": "DRILLING", "sequence": 2, "operation_code": None, "operation_name": ""},
            {"section_code": "PRESSING", "sequence": 3, "operation_code": None, "operation_name": ""},
            {"section_code": "SHOT_BLAST", "sequence": 4, "operation_code": None, "operation_name": ""},
            {"section_code": "PREP_STOCK", "sequence": 5, "operation_code": None, "operation_name": ""},
            {"section_code": "ANODIZING", "sequence": 6, "operation_code": None, "operation_name": ""},
            {"section_code": "WIP_STOCK", "sequence": 7, "operation_code": None, "operation_name": ""},
            {"section_code": "SAWING", "sequence": 8, "operation_code": None, "operation_name": "", "transforms_dimensions": True},
            {"section_code": "PACKING", "sequence": 9, "operation_code": None, "operation_name": ""},
            {"section_code": "FINISHED_STOCK", "sequence": 10, "operation_code": None, "operation_name": ""},
            {"section_code": "SHIPMENT", "sequence": 11, "operation_code": None, "operation_name": ""},
            {"section_code": "SHIPPED", "sequence": 12, "operation_code": None, "operation_name": ""},
        ],
    },
]
