from __future__ import annotations

ROUTE_RULE_PROFILES = [
    {
        "code": "packaging_map_rp",
        "name": "Упаковочная карта РП",
        "is_active": True,
        "priority": 1000,
        "import_template_code": "upakovochnaya_karta_rp",
        "excel_column_passport": [
            {"index": 1, "header": "Артикул", "letter": "A", "field_path": "sku"},
            {"index": 2, "header": "Пополнение", "letter": "B", "field_path": "replenishment"},
            {"index": 3, "header": "Наименование", "letter": "C", "field_path": "product_name"},
            {"index": 4, "header": "Биржа КТМ на складе", "letter": "D", "field_path": "raw_stock_ktm"},
            {"index": 5, "header": "Цвет", "letter": "E", "field_path": "color"},
            {"index": 6, "header": "Кол-во доп. в 2,7", "letter": "F", "field_path": "input_quantity"},
            {"index": 7, "header": "Длина, м", "letter": "G", "field_path": "input_length"},
            {"index": 8, "header": "Операция/Техпроцесс", "letter": "H", "field_path": "operation"},
            {"index": 9, "header": "Упаковка", "letter": "I", "field_path": "packaging"},
            {"index": 10, "header": "Примечание", "letter": "J", "field_path": "note"},
            {"index": 11, "header": "Длина после резки, м", "letter": "K", "field_path": "output_length"},
            {"index": 12, "header": "Кол-во после резки готовых изделий", "letter": "L", "field_path": "output_quantity"},
            {"index": 13, "header": "Запад", "letter": "M", "field_path": "west_quantity"},
            {"index": 14, "header": "Восток", "letter": "N", "field_path": "east_quantity"},
            {"index": 15, "header": "Вид готовой продукции", "letter": "O", "field_path": "output_kind"},
            {"index": 16, "header": "Комментарий", "letter": "P", "field_path": "comments"},
            {"index": 19, "header": "Упаковка в 1,8", "letter": "S", "field_path": "packaging_1_8_quantity"},
            {"index": 20, "header": "Добавить", "letter": "T", "field_path": "add_quantity"},
        ],
        "excel_passport_meta": {
            "source": "import_template",
            "synced_at": "2026-05-17T07:35:39.151Z",
        },
    },
]
