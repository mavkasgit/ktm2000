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
        "normalization_rules": {
            "version": 1,
            "operation": {
                "rules": [
                    {
                        "result": {
                            "operation_code": "PACK",
                            "operation_name": "Упаковка",
                            "normalized_pack_op_family": "CUSTOM",
                            "additional_pack_operations": [
                                {
                                    "operation_code": "PACK_CUSTOM",
                                    "operation_name_template": "Доп. операция упаковки: {raw}",
                                }
                            ],
                        },
                        "contains": ["Под заказ"],
                        "priority": 100,
                    },
                    {
                        "result": {
                            "operation_code": "PRESS_WINDOW",
                            "operation_name": "Пресс окно",
                            "normalized_pack_op_family": "NONE",
                            "additional_pack_operations": [],
                        },
                        "contains": ["Окно"],
                        "priority": 90,
                    },
                    {
                        "result": {
                            "operation_code": "PRESS_COMB",
                            "operation_name": "Пресс гребенка",
                            "normalized_pack_op_family": "NONE",
                            "additional_pack_operations": [],
                        },
                        "contains": ["Греб"],
                        "priority": 80,
                    },
                    {
                        "result": {
                            "operation_code": "DRILL",
                            "operation_name": "Сверловка",
                            "normalized_pack_op_family": "NONE",
                            "additional_pack_operations": [],
                        },
                        "contains": ["Сверл", "Отверст"],
                        "priority": 70,
                    },
                    {
                        "result": {
                            "operation_code": "PACK",
                            "operation_name": "Упаковка",
                            "normalized_pack_op_family": "GLUE",
                            "additional_pack_operations": [
                                {
                                    "operation_code": "PACK_GLUE",
                                    "operation_name": "Упаковка с клеевой лентой",
                                }
                            ],
                        },
                        "contains": ["Клей"],
                        "priority": 60,
                    },
                    {
                        "result": {
                            "operation_code": "PACK",
                            "operation_name": "Упаковка",
                            "normalized_pack_op_family": "DIFFUSER",
                            "additional_pack_operations": [
                                {
                                    "operation_code": "PACK_DIFFUSER",
                                    "operation_name": "Упаковка с диффузором",
                                }
                            ],
                        },
                        "contains": ["Диффуз"],
                        "priority": 50,
                    },
                ],
                "fallback": {
                    "operation_code": "PACK",
                    "operation_name": "Упаковка",
                    "normalized_pack_op_family": "CUSTOM",
                    "additional_pack_operations": [
                        {
                            "operation_code": "PACK_CUSTOM",
                            "operation_name_template": "Доп. операция упаковки: {raw}",
                        }
                    ],
                },
            },
            "output_kind": {
                "rules": [
                    {
                        "result": "finished_good",
                        "contains": ["ГП", "Г.П."],
                        "priority": 100,
                    },
                    {
                        "result": "semi_finished_shipment",
                        "contains": ["П/Ф", "П/Ф."],
                        "priority": 90,
                    },
                ],
                "fallback": "raw",
            },
        },
    },
]
