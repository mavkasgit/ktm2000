from __future__ import annotations

# Справочник флагов обработки техкарт (данные, а не код — ADR-0010).

# code, name, section_scope
PROCESSING_FLAGS_DATA: list[dict[str, str | None]] = [
    {"code": "skip_shot_blast", "name": "Пропуск дробеструя", "section_scope": "SHOT_BLAST"},
    {"code": "is_laminated", "name": "Ламинирование", "section_scope": None},
]
