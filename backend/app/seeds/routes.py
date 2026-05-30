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
            {"section_code": "WH", "sequence": 1, "operation_code": None, "operation_name": ""},
            {"section_code": "DRILL", "sequence": 2, "operation_code": None, "operation_name": ""},
            {"section_code": "PRESS", "sequence": 3, "operation_code": None, "operation_name": ""},
            {"section_code": "SHOT", "sequence": 4, "operation_code": None, "operation_name": ""},
            {"section_code": "ANOD", "sequence": 5, "operation_code": None, "operation_name": ""},
            {"section_code": "WIP_WH", "sequence": 6, "operation_code": None, "operation_name": ""},
            {"section_code": "SAW", "sequence": 7, "operation_code": None, "operation_name": ""},
            {"section_code": "PACK", "sequence": 8, "operation_code": None, "operation_name": ""},
            {"section_code": "FG_WH", "sequence": 9, "operation_code": None, "operation_name": ""},
            {"section_code": "SHIPMENT", "sequence": 10, "operation_code": None, "operation_name": ""},
            {"section_code": "SENT", "sequence": 11, "operation_code": None, "operation_name": ""},
        ],
    },
]
