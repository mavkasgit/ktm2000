#!/usr/bin/env python
"""Ручная уборка каталога ``imports/`` (#288).

Находит файлы без строки в ``import_files`` старше суточного порога, удаляет их
и печатает список. Файлы под записью и защищённые оригиналы не трогает —
полные правила в ``app.services.import_storage.sweep_orphan_import_files``.

    npm run imports:sweep

Фоновая уборка в lifespan приложения идёт тем же кодом; этот CLI — для ручного
запуска и разбора (например после массового удаления, пока планировщик ещё не
проснулся по интервалу).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session  # noqa: E402
from app.services.import_storage import sweep_orphan_import_files  # noqa: E402


async def main() -> int:
    async with async_session() as db:
        report = await sweep_orphan_import_files(db)
    print(f"#288 sweep imports/: {report.summary()}")
    if report.removed:
        print("Удалено сирот (без записи, старше порога):")
        for path in report.removed:
            print(f"  - {path}")
    else:
        print("Нет сирот старше порога — ничего не удалено.")
    if report.kept_young:
        print(f"Сохранено моложе порога (свежие импорты): {len(report.kept_young)}")
    if report.kept_pinned:
        print(f"Защищённых оригиналов не тронуто: {report.kept_pinned}")
    if report.failed:
        print(f"Сбоев удаления (доберёт следующий проход): {len(report.failed)}")
        for path in report.failed:
            print(f"  ! {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
