from __future__ import annotations

# Справочник участков и операций завода (данные, а не код — ADR-0010).
# Конвертация в typed PlantConfig-модели — единственная, в canon/registry.py.
# Сырые dict'ы/кортежи живут здесь (authoring-модуль), а не в седерах.

SECTIONS_DATA = [
    {"code": "RAW_STOCK", "name": "Склад сырья", "sort_order": 10, "type": "raw_stock", "icon": "Warehouse", "icon_color": "#F59E0B"},
    {"code": "DRILLING", "name": "Сверловка", "sort_order": 20, "type": "production", "icon": "Drill", "icon_color": "#3B82F6"},
    {"code": "PRESSING", "name": "Пресс", "sort_order": 30, "type": "production", "icon": "Anvil", "icon_color": "#EF4444"},
    {"code": "SHOT_BLAST", "name": "Дробеструй", "sort_order": 40, "type": "production", "icon": "SprayCan", "icon_color": "#6B7280"},
    {"code": "PREP_STOCK", "name": "Склад подготовки", "sort_order": 45, "type": "wip_stock", "icon": "PackageX", "icon_color": "#7C3AED"},
    {"code": "ANODIZING", "name": "Анодирование", "sort_order": 50, "type": "production", "icon": "FlaskConical", "icon_color": "#06B6D4"},
    {"code": "WIP_STOCK", "name": "Склад полуфабриката", "sort_order": 60, "type": "wip_stock", "icon": "Boxes", "icon_color": "#84CC16"},
    {"code": "SAWING", "name": "Пила", "sort_order": 70, "type": "production", "icon": "Fan", "icon_color": "#F97316"},
    {"code": "PACKING", "name": "Упаковка", "sort_order": 80, "type": "production", "icon": "Package", "icon_color": "#10B981"},
    {"code": "FINISHED_STOCK", "name": "Склад готовой продукции", "sort_order": 90, "type": "finished_stock", "icon": "Container", "icon_color": "#065F46"},
    {"code": "SHIPMENT", "name": "К отгрузке", "sort_order": 100, "type": "finished_stock", "icon": "Truck", "icon_color": "#7C3AED"},
    {"code": "SHIPPED", "name": "Отправлено", "sort_order": 110, "type": "finished_stock", "icon": "CheckCircle", "icon_color": "#059669"},
]

# Operations for each section: (group_code, group_name, sort_order, op_code, op_name, is_significant, icon, icon_color, resolver_type, resolver_config, operation_type)
# group_code=None means the operation has no group (standalone).
# op_code=None means this is a placeholder operation (resolved dynamically).
# resolver_type=None means the operation code is explicit (no resolution needed).
# operation_type='transport' marks warehouse-issue/receive ops (they don't represent real work).

SECTION_OPS: dict[str, list[tuple[str | None, str | None, int, str | None, str, bool, str | None, str | None, str | None, dict, str]]] = {
    "RAW_STOCK": [
        ("RAW_STOCK", "Выдача сырья", 10, "ISSUE_RAW", "Выдача сырья", False, "Package", "#F59E0B", None, {}, "transport"),
    ],
    "DRILLING": [
        ("DRILLING", "Сверловка", 10, "DRILL", "Сверловка", True, "Drill", "#3B82F6", None, {}, "production"),
    ],
    "PRESSING": [
        ("PRESSING", "Пресс", 10, "PRESS_WINDOW", "Окно", True, "LetterO", "#EF4444", None, {}, "production"),
        ("PRESSING", "Пресс", 10, "PRESS_COMB", "Гребенка", True, "LetterSh", "#F97316", None, {}, "production"),
    ],
    "SHOT_BLAST": [
        ("SHOT_BLAST", "Дробеструй", 10, "SHOT", "Дробеструй", True, "SprayCan", "#6B7280", None, {}, "production"),
    ],
    "PREP_STOCK": [
        ("PREP_STOCK", "Передача на склад подготовки", 10, "MOVE_TO_PREP_STOCK", "Передача на склад подготовки", False, "Truck", "#7C3AED", None, {}, "transport"),
    ],
    "ANODIZING": [
        ("ANODIZING", "Анодирование", 10, "ANOD_01", "Серебро", True, None, "#C0C0C0", None, {}, "production"),
        ("ANODIZING", "Анодирование", 10, "ANOD_02", "Золото", True, None, "#FFD700", None, {}, "production"),
        ("ANODIZING", "Анодирование", 10, "ANOD_03", "Бронза", True, None, "#8B5A2B", None, {}, "production"),
        ("ANODIZING", "Анодирование", 10, "ANOD_05", "Чёрный", True, None, "#1C1C1C", None, {}, "production"),
        ("ANODIZING", "Анодирование", 10, "ANOD_06", "Шампань", True, None, "#F7E7CE", None, {}, "production"),
        ("ANODIZING", "Анодирование", 10, "ANOD_07", "Медь", True, None, "#CD5C5C", None, {}, "production"),
        ("ANODIZING", "Анодирование", 10, "ANOD_08", "Титан", True, None, "#878681", None, {}, "production"),

        ("PACK", "Упаковка", 20, "PACK_STRETCH", "Стрейч", True, None, "#0891B2", None, {}, "production"),
        ("PACK", "Упаковка", 20, "PACK_SPUNBOND", "Спанбонд", True, None, "#06B6D4", None, {}, "production"),
    ],
    "WIP_STOCK": [
        ("WIP_STOCK", "Передача на склад", 10, "MOVE_TO_WIP", "Передача на склад полуфабриката", False, "Truck", "#84CC16", None, {}, "transport"),
    ],
    "SAWING": [
        ("SAWING", "Резка", 10, "SAW", "Резка на пиле", True, "Fan", "#F97316", None, {}, "production"),
    ],
    "PACKING": [
        ("PACKING", "Упаковка", 10, "PACK", "Упаковка", True, "Package", "#10B981", None, {}, "production"),
    ],
    "FINISHED_STOCK": [
        ("FINISHED_STOCK", "Склад ГП", 10, "FG_WH", "Склад готовой продукции", False, "Container", "#065F46", None, {}, "transport"),
    ],
    "SHIPMENT": [
        ("SHIPMENT", "К отгрузке", 10, "SHIPMENT", "К отгрузке", False, "PackageOpen", "#8B5CF6", None, {}, "transport"),
    ],
    "SHIPPED": [
        ("SHIPPED", "Отправлено", 10, "SENT", "Отправлено", False, "PackageCheck", "#EC4899", None, {}, "transport"),
    ],
}

# Заводская настройка (ADR-0002): какие операции трансформируют габариты
# (резка: один вход → несколько выходов разной длины). Ядро читает маркер
# из справочника/этапа маршрута, а не сравнивает код секции со строкой.
TRANSFORMING_SECTION_OPS: set[tuple[str, str]] = {
    ("SAWING", "SAW"),
}

# field_map для table-driven upsert (ADR-0010): живут рядом с данными,
# которые описывают. ORM-атрибут → ключ в строке данных.
SECTIONS_FIELD_MAP = {
    "code": "code",
    "name": "name",
    "sort_order": "sort_order",
    "type": "type",
    "icon": "icon",
    "icon_color": "icon_color",
    "is_active": "is_active",
}

SECTION_OPERATIONS_FIELD_MAP = {
    "operation_code": "operation_code",
    "operation_name": "operation_name",
    "is_significant": "is_significant",
    "icon": "icon",
    "icon_color": "icon_color",
    "group_code": "group_code",
    "group_name": "group_name",
    "sort_order": "sort_order",
    "resolver_type": "resolver_type",
    "resolver_config": "resolver_config",
    "operation_type": "operation_type",
}
