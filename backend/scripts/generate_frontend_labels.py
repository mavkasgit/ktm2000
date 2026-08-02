#!/usr/bin/env python
"""Генерация TS-констант лейблов и ролей из PlantConfig (ADR-0004, тикет #26).

Вызывает build_plant_config() (канон = единственный источник), сериализует
config.display.labels и config.display.roles в frontend/shared/lib/
generated-labels.ts. Сгенерированный файл не коммитится (см. .gitignore).

Usage:
    python scripts/generate_frontend_labels.py [--check]
    --check  — только проверка актуальности (exit 1 при расхождении), для CI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Добавляем backend/ в sys.path для импортов app.*
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

FRONTEND_LIB = (
    Path(__file__).resolve().parent.parent.parent
    / "frontend"
    / "src"
    / "shared"
    / "lib"
)
OUTPUT_PATH = FRONTEND_LIB / "generated-labels.ts"

HEADER = "// GENERATED FILE — do not edit by hand. Regenerate: python scripts/generate_frontend_labels.py\n"


def _ts_dict(name: str, data: dict[str, str]) -> str:
    lines = [f"export const {name}: Record<string, string> = {{"]
    for key in sorted(data):
        lines.append(f"  {_quote(key)}: {_quote(data[key])},")
    lines.append("}")
    return "\n".join(lines)


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _render(config) -> str:
    labels = config.display.labels
    roles = config.display.roles.roles
    parts = [
        HEADER,
        "// Лейблы статусов позиции плана",
        _ts_dict("statusLabels", labels.status_labels),
        "",
        "// Лейблы видов выпуска",
        _ts_dict("outputKindLabels", labels.output_kind_labels),
        "",
        "// Тексты ошибок валидации (ключи — error codes сервера)",
        _ts_dict("errorLabels", labels.error_messages),
        "",
        "// Лейблы предупреждений (warning codes)",
        _ts_dict("warningLabels", labels.warning_labels),
        "",
        "// Лейблы статуса валидации позиции",
        _ts_dict("validationLabels", labels.validation_labels),
        "",
        "// Лейблы статусов задач участка",
        _ts_dict("taskStatusLabels", labels.task_status_labels),
        "",
        "// Лейблы статусов этапов выполнения",
        _ts_dict("stageStatusLabels", labels.stage_status_labels),
        "",
        "// Лейблы статусов bulk-операций",
        _ts_dict("bulkStatusLabels", labels.bulk_status_labels),
        "",
        "// Лейблы действий изменения плана",
        _ts_dict("actionLabels", labels.action_labels),
        "",
        "// Переводы серверных ошибок (англ. фразы с плейсхолдерами {0}, {1}, ...) → RU",
        _ts_dict("errorPhraseTranslations", labels.error_phrase_translations),
        "",
        "// Каталог ролей: code -> (label, sections)",
        "export interface RoleDef { code: string; label: string; sections: string[] }",
        "export const roles: RoleDef[] = [",
    ]
    for role in roles:
        sections = ", ".join(_quote(s) for s in role.sections)
        parts.append(
            f"  {{ code: {_quote(role.code.value)}, label: {_quote(role.label)}, sections: [{sections}] }},"
        )
    parts.append("]")
    parts.append("")
    return "\n".join(parts)


def main() -> int:
    from app.seeds.canon import build_plant_config

    config = build_plant_config()
    rendered = _render(config)

    if "--check" in sys.argv:
        if OUTPUT_PATH.exists() and OUTPUT_PATH.read_text(encoding="utf-8") == rendered:
            print(f"OK: {OUTPUT_PATH} is up to date")
            return 0
        print(f"FAIL: {OUTPUT_PATH} is stale — regenerate", file=sys.stderr)
        return 1

    FRONTEND_LIB.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    print(f"OK: wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
