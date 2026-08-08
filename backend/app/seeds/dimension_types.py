from __future__ import annotations

# Базовые типы измерений (данные, а не код — ADR-0010).
# Новый тип размера = строка здесь, без миграции схемы.
DIMENSION_TYPES_DATA = [
    {"code": "length_mm", "name": "Длина", "unit": "мм", "value_type": "number"},
    {"code": "width_mm", "name": "Ширина", "unit": "мм", "value_type": "number"},
    {"code": "thickness_mm", "name": "Толщина", "unit": "мм", "value_type": "number"},
    {"code": "height_mm", "name": "Высота", "unit": "мм", "value_type": "number"},
]

# field_map для table-driven upsert (ADR-0010): ORM-атрибут → ключ в строке.
DIMENSION_TYPES_FIELD_MAP = {
    "code": "code",
    "name": "name",
    "unit": "unit",
    "value_type": "value_type",
}
