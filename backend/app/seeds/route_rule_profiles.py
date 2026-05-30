from __future__ import annotations

ROUTE_RULE_PROFILES = [
    {
        "code": "packaging_map_rp",
        "name": "Упаковочная карта РП",
        "is_active": True,
        "priority": 1000,
        "route_name_pattern": "{output_kind} - {press_op} - {drill_op} - {shot_op} - {color} - {pack_op}",
        "import_template_code": "upakovochnaya_karta_rp",
        "route_sections": ["WH", "DRILL", "PRESS", "SHOT", "ANOD", "WIP_WH", "SAW", "PACK", "FG_WH", "SHIPMENT", "SENT"],
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
]
