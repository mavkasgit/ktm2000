from __future__ import annotations

# column_mapping каждого шаблона хранит заголовки, псевдонимы (aliases),
# позиции колонок (column) и служебный ключ ``_config`` (метаданные шаблона).
# Резолвер колонок (app/services/import_column_resolver.py) — единый
# потребитель этих данных для импорта плана.
# Дефолтный маппинг остатков живёт отдельно — JSON-файл
# ``app/stock/remainders_columns.json`` (не шаблон, см. ADR-0003 «Обновление»).
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
        # План подготовительного участка (#313): та же структура, что у
        # «Упаковочной карты РП», но состав колонок — только участки
        # подготовки. Лишние колонки (остатки, Запад/Восток, вид конечного
        # продукта) убраны: подготовительный маршрут до них не доходит.
        # Колонки операций ОСТАЮТСЯ — по ним строка получает свою операцию
        # и свой вариант маршрута (сверло / пресс / чистый дробеструй).
        "code": "plan_prep_stage",
        "name": "План подготовительного участка",
        "is_active": True,
        "sort_order": 10,
        "column_mapping": {
            "sku": {"column": "A", "header": "Артикул"},
            "product_name": {"column": "B", "header": "Наименование"},
            "color": {"column": "C", "header": "Цвет"},
            "operation": {"column": "D", "header": "Операция"},
            # Длина обязательна: подготовка работает линейным профилем, и без
            # неё позиция остаётся БЕЗ габаритов. Остаток на складе сырья
            # габарит имеет, и выдача на первый участок не находит пару —
            # задание висит `0/N`, а круг передач не стартует.
            "output_length": {"column": "E", "header": "Длина, м"},
            "quantity": {"column": "F", "header": "Кол-во, шт"},
            "note": {"column": "G", "header": "Примечание"},
        },
    },
]

# field_map для table-driven upsert (ADR-0010): ORM-атрибут → ключ в строке.
IMPORT_TEMPLATE_FIELD_MAP = {
    "code": "code",
    "name": "name",
}
