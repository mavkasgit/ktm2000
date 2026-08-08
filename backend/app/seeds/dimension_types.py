from __future__ import annotations

# Базовые типы измерений (данные, а не код — ADR-0010).
# Новый тип размера = строка здесь, без миграции схемы.
DIMENSION_TYPES_DATA = [
    {"code": "length_mm", "name": "Длина", "unit": "мм", "value_type": "number"},
]
