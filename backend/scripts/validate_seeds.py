#!/usr/bin/env python
"""CI-скрипт валидации сидов (ADR-0004, тикет #22).

Тонкая обёртка над build_plant_config(). Запускается в CI для fail-fast
проверки целостности seed-данных без поднятия приложения.

Usage:
    python scripts/validate_seeds.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Добавляем backend/ в sys.path для импортов app.*
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))


def main() -> int:
    try:
        from app.seeds.canon import build_plant_config

        config = build_plant_config()
        print(f"OK: PlantConfig valid: {len(config.display.colors.tokens)} color tokens, "
              f"{len(config.display.labels.error_messages)} error messages")
        return 0
    except Exception as exc:
        print(f"FAIL: Seed validation FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
