from __future__ import annotations

IMPORT_TEMPLATES = [
    {
        "code": "upakovochnaya_karta_rp",
        "name": "Упаковочная карта РП",
        "is_active": True,
        "sort_order": 0,
        "column_mapping": {
            "sku": {"column": "A", "header": "Артикул"},
            "replenishment": {"column": "B", "header": "пополнение"},
            "product_name": {"column": "C", "header": "Наименование"},
            "raw_stock_ktm": {"column": "D", "header": "остатки сырья на КТМ"},
            "color": {"column": "E", "header": "Цвет"},
            "input_quantity": {"column": "F", "header": "кол-во шт. в 2,7"},
            "input_length": {"column": "G", "header": "Длина, м"},
            "operation": {"column": "H", "header": "Пробивка/сверловка"},
            "packaging": {"column": "I", "header": "Упаковка"},
            "note": {"column": "J", "header": "Примечание"},
            "output_length": {"column": "K", "header": "Длина после упак, м"},
            "output_quantity": {"column": "L", "header": "кол-во штук готовой продукции"},
            "west_quantity": {"column": "M", "header": "Запад"},
            "east_quantity": {"column": "N", "header": "Восток"},
            "output_kind": {"column": "O", "header": "Вид конечного продукта"},
            "comments": {"column": "P", "header": "Примечание"},
            "packaging_1_8_quantity": {"column": "S", "header": "Упаковка в 1,8"},
            "add_quantity": {"column": "T", "header": "Добавить"},
        },
    },
]
