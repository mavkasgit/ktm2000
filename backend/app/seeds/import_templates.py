from __future__ import annotations

# column_mapping каждого шаблона хранит заголовки, псевдонимы (aliases),
# позиции колонок (column) и служебный ключ ``_config`` (метаданные шаблона).
# Резолвер колонок (app/services/import_column_resolver.py) — единый
# потребитель этих данных для импорта плана и остатков.
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
            "comments": {
                "column": "P",
                "header": "Примечание",
                "aliases": ["Комментарии"],
            },
            "packaging_1_8_quantity": {"column": "S", "header": "Упаковка в 1,8"},
            "add_quantity": {
                "column": "T",
                "header": "Добавить",
                "aliases": ["добавить"],
            },
        },
    },
    {
        "code": "ostaki_ktm",
        "name": "Остатки КТМ",
        "is_active": True,
        "sort_order": 1,
        "column_mapping": {
            "_config": {"length_required": True},
            "sku": {
                "column": "A",
                "header": "Артикул",
                "aliases": ["sku", "код", "продукт", "sku/артикул", "артикул / sku", "артикул/sku"],
            },
            "quantity": {
                "column": "B",
                "header": "Кол-во",
                "aliases": [
                    "quantity",
                    "количество",
                    "кол-во",
                    "кол-во, шт",
                    "кол-во шт",
                    "кол-во шт.",
                    "кол-во,шт",
                ],
            },
            "quality_state": {
                "column": "C",
                "header": "Статус качества",
                "aliases": [
                    "quality_state",
                    "quality",
                    "качество",
                    "состояние качества",
                    "quality status",
                ],
            },
            "completed_operations": {
                "column": "D",
                "header": "Операции",
                "aliases": [
                    "выполненные операции",
                    "completed_operations",
                    "пройденные операции",
                    "этапы",
                ],
            },
            "target_section": {
                "column": "E",
                "header": "Участок",
                "aliases": [
                    "целевая секция",
                    "секция",
                    "target_section",
                    "целевой участок",
                    "целевая участок",
                ],
            },
            "comment": {
                "column": "F",
                "header": "Комментарий",
                "aliases": ["comment", "примечание"],
            },
            "length": {
                "column": "G",
                "header": "Длина",
                "aliases": ["длина, м", "длина м", "длина (м)", "длина,м", "length", "length_m", "length, m"],
            },
        },
    },
]

# field_map для table-driven upsert (ADR-0010): ORM-атрибут → ключ в строке.
IMPORT_TEMPLATE_FIELD_MAP = {
    "code": "code",
    "name": "name",
}
