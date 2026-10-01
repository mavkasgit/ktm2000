#!/usr/bin/env python
"""Уборка маршрутов-сирот (#228).

Импорт плана создаёт маршрут под каждое новое состава, а ``db:seed``
ищет только свои ``code``/имена: маршруты, которые ни одна позиция
плана так и не выбрала, копятся и участвуют в подборе
(``app/services/route_selection.py``). Критерий сироты — «нет позиций
и нет истории» — зафиксирован в ``app/services/route_deletion.py``;
здесь только composition root.

По умолчанию скрипт **ничего не удаляет** (dry-run печатает список).
Удаление — только с ``--execute``; уборка трогает только маршруты, которые
создал импорт (кода нет либо он ``auto-``) и у которых нет ни позиций
плана, ни строк плана участков, ни заданий, ни позиций выпуска. Справочные
маршруты завода (``universal_rp``, ``dynamic_*``) и архивные уборка не
трогает ни в одном режиме.

    cd backend && python scripts/cleanup_orphan_routes.py            # посмотреть
    cd backend && python scripts/cleanup_orphan_routes.py --execute   # убрать

DSN берётся тем же способом, что и у ``check_canon_drift.py``: из
env-файла (ADR-0046), а не из окружения оболочки; путь к базе печатается
всегда, чтобы отчёт нельзя было прочесть как вывод по чужой базе.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.check_canon_drift import describe_target, env_file_problem


async def run_cleanup(session, *, execute: bool) -> int:
    """Напечатать отчёт об уборке; вернуть код выхода (0 — всё в порядке)."""
    from app.services.route_deletion import cleanup_orphan_routes

    report = await cleanup_orphan_routes(session, execute=execute)

    if not report.found:
        print("Сирот нет: у каждого маршрута есть позиции плана или история цеха.")
        return 0

    print(f"Маршрутов-сирот: {len(report.found)}")
    for orphan in report.found:
        print(orphan.render())

    if not report.executed:
        print(
            "\nЭто dry-run: ничего не удалено. Повторить с --execute, "
            "чтобы убрать перечисленные маршруты."
        )
        return 0

    print(f"\nУдалено маршрутов: {len(report.deleted_ids)} — {report.deleted_ids}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI: DSN из env-файла, dry-run по умолчанию."""
    parser = argparse.ArgumentParser(description="Уборка маршрутов-сирот (#228)")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="удалить найденных сирот (по умолчанию только показать)",
    )
    args = parser.parse_args(argv)

    # До импорта приложения: pydantic отдал бы приоритет окружению процесса.
    from app.core.env_file import apply_env_file, env_file_path

    problem = env_file_problem(env_file_path())
    if problem is not None:
        print(f"Уборка сирот невозможна: {problem}.", file=sys.stderr)
        return 2
    apply_env_file()

    from app.core.config import settings
    from app.core.database import async_session

    print(f"Проверяем БД: {describe_target(settings.DATABASE_URL)}")
    print("Режим: УДАЛЕНИЕ" if args.execute else "Режим: dry-run (ничего не удаляется)")

    async def _run() -> int:
        async with async_session() as session:
            return await run_cleanup(session, execute=args.execute)

    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
