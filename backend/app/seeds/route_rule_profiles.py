from __future__ import annotations

ROUTE_RULE_PROFILES = [
    {
        "code": "packaging_map_rp",
        "name": "Упаковочная карта РП",
        "is_active": True,
        "priority": 1000,
        "route_name_pattern": "{output_kind} - {press_op} - {drill_op} - {shot_op} - {color} - {pack_op} - {packing_op} - {saw_op}",
        "import_template_code": "upakovochnaya_karta_rp",
        "route_sections": ["RAW_STOCK", "DRILLING", "PRESSING", "SHOT_BLAST", "PREP_STOCK", "ANODIZING", "WIP_STOCK", "SAWING", "PACKING", "FINISHED_STOCK", "SHIPMENT", "SHIPPED"],
        "excel_column_passport": [
            {"index": 1, "header": "Артикул", "letter": "A", "field_path": "sku"},
            {"index": 2, "header": "пополнение", "letter": "B", "field_path": "replenishment"},
            {"index": 3, "header": "Наименование", "letter": "C", "field_path": "product_name"},
            {"index": 4, "header": "остатки сырья на КТМ", "letter": "D", "field_path": "raw_stock_ktm"},
            {"index": 5, "header": "Цвет", "letter": "E", "field_path": "color"},
            {"index": 6, "header": "кол-во шт. в 2,7", "letter": "F", "field_path": "input_quantity"},
            {"index": 7, "header": "Длина, м", "letter": "G", "field_path": "input_length"},
            {"index": 8, "header": "Пробивка/сверловка", "letter": "H", "field_path": "operation"},
            {"index": 9, "header": "Упаковка", "letter": "I", "field_path": "packaging"},
            {"index": 10, "header": "Примечание", "letter": "J", "field_path": "note"},
            {"index": 11, "header": "Длина после упак, м", "letter": "K", "field_path": "output_length"},
            {"index": 12, "header": "кол-во штук готовой продукции", "letter": "L", "field_path": "output_quantity"},
            {"index": 13, "header": "Запад", "letter": "M", "field_path": "west_quantity"},
            {"index": 14, "header": "Восток", "letter": "N", "field_path": "east_quantity"},
            {"index": 16, "header": "Примечание", "letter": "P", "field_path": "comments"},
            {"index": 19, "header": "Упаковка в 1,8", "letter": "S", "field_path": "packaging_1_8_quantity"},
            {"index": 20, "header": "Добавить", "letter": "T", "field_path": "add_quantity"},
        ],
        "excel_passport_meta": {
            "source": "import_template",
            "synced_at": "2026-05-17T07:35:39.151Z",
        },
    },
    {
        # План подготовительного участка (#313): RAW_STOCK → участки подготовки
        # → PREP_STOCK. `route_sections` — СУПЕРСЕТСТВО всех трёх вариантов:
        # сверло+дробеструй, пресс+дробеструй, чистый дробеструй. Конкретный
        # вариант собирают правила `route_select` фазы (`selection_rules.py`),
        # снимая лишние участки через `exclude_section`.
        #
        # Один профиль, а не три: `imports.py::_resolve_template_context` берёт
        # РОВНО один профиль на шаблон (`.limit(1)`), поэтому три профиля на
        # одном шаблоне означали бы, что два из них никогда не участвуют в
        # импорте. Различия вариантов живут в данных правил, а не в профилях.
        "code": "prep_stage_plan",
        "name": "План подготовительного участка",
        "is_active": True,
        "priority": 900,
        "route_name_pattern": "{operations} - {shot_op}",
        "route_sections": ["RAW_STOCK", "DRILLING", "PRESSING", "SHOT_BLAST", "PREP_STOCK"],
        "excel_column_passport": [
            {"index": 1, "header": "Артикул", "letter": "A", "field_path": "sku"},
            {"index": 2, "header": "Наименование", "letter": "B", "field_path": "product_name"},
            {"index": 3, "header": "Цвет", "letter": "C", "field_path": "color"},
            {"index": 4, "header": "Операция", "letter": "D", "field_path": "operation"},
            {"index": 5, "header": "Длина, м", "letter": "E", "field_path": "output_length"},
            {"index": 6, "header": "Кол-во, шт", "letter": "F", "field_path": "quantity"},
            {"index": 7, "header": "Примечание", "letter": "G", "field_path": "note"},
        ],
        "excel_passport_meta": {
            "source": "import_template",
            "synced_at": "2026-10-03T00:00:00.000Z",
        },
    },
]

# field_map для table-driven upsert (ADR-0010): ORM-атрибут → ключ в строке.
ROUTE_RULE_PROFILE_FIELD_MAP = {
    "code": "code",
    "name": "name",
    "is_active": "is_active",
    "priority": "priority",
    "excel_passport_meta": "excel_passport_meta",
    "route_sections": "route_sections",
}
