from __future__ import annotations

# Справочник флагов обработки техкарт (данные, а не код — ADR-0010).

# code, name, section_scope
PROCESSING_FLAGS_DATA: list[dict[str, str | None]] = [
    {"code": "skip_shot_blast", "name": "Пропуск дробеструя", "section_scope": "SHOT_BLAST"},
    {"code": "is_laminated", "name": "Ламинирование", "section_scope": None},
]

# field_map для table-driven upsert (ADR-0010): ORM-атрибут → ключ в строке.
PROCESSING_FLAGS_FIELD_MAP = {
    "code": "code",
    "name": "name",
    "section_scope": "section_scope",
}
