#!/usr/bin/env python
"""Детектор дрейфа канона: падающая сверка «строка канона отсутствует в БД».

ADR-0046, тикет #216. Скрипт **только читает** и завершается с ненулевым
кодом, когда строка кода-канона (``PlantConfig``) не найдена в БД.
Однонаправленное правило: лишнее в БД (правило, созданное администратором) —
не дефект (ADR-0004 §2).

Запуск против боевой базы (порт Postgres в проде не проброшен на хост —
``infra/compose/docker-compose.prod.yml``), внутри контейнера backend, где
DSN задаёт compose и env-файла нет:

    docker exec ktm2000-backend-prod python scripts/check_canon_drift.py

Хост с доступным портом — DSN берётся из env-файла, а не из окружения
оболочки: ``apply_env_file()`` перекрывает ``DATABASE_URL`` (ADR-0046 п. 3,
``app/core/env_file.py``). ``$ENV_FILE`` на несуществующий файл — падение с
кодом ``2``: иначе DSN тихо взялся бы из окружения и «OK» был бы про чужую
базу. Проверяемая база печатается всегда.

    cd backend && ENV_FILE=../.env.prod python scripts/check_canon_drift.py

Восстановление после срабатывания — прогон ``POST /api/routes-seed``
(префикс ``app/api/routes/routes_seed.py:23``; ``/api/seed`` не тот) либо
точечная вставка недостающих строк. Правок в БД скрипт не вносит.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

BACKEND_DIR = Path(__file__).resolve().parent.parent


def env_file_problem(path: Path) -> str | None:
    """Причина, по которой DSN не взят из env-файла, либо ``None``.

    ``$ENV_FILE`` указывает на несуществующий файл — ``apply_env_file()`` это
    no-op, и DSN молча берётся из окружения оболочки. Для проверки дрейфа
    это ложное «всё хорошо» по чужой базе, поэтому такой запуск падает.
    Пустой путь (переменная не задана) — не проблема: файл опционален,
    DSN тогда задаёт compose (прод-контейнер).
    """
    if str(path) and not path.is_file():
        return f"env-файл {path} не найден — DSN взят бы из окружения оболочки"
    return None


def describe_target(url: str) -> str:
    """Человекочитаемое имя проверяемой базы; пароль не печатается."""
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    return f"{parsed.host}/{parsed.database}"


async def run_check(session: AsyncSession) -> int:
    """Напечатать отчёт о дрейфе; вернуть код выхода (0 — дрейфа нет).

    Публичный шов для тестов: принимает готовую ``AsyncSession`` и ничего
    не коммитит.
    """
    from app.services.canon_drift import check_canon_drift

    report = await check_canon_drift(session)
    if not report.has_drift:
        print("OK: дрейфа канона нет — все строки канона присутствуют в БД.")
        return 0

    print("ДРЕЙФ КАНОНА: строки канона отсутствуют в БД.")
    print(report.render())
    print(
        "Восстановление: POST /api/routes-seed (или точечная вставка). "
        "Правила без code (созданные из UI) — не дефект."
    )
    return 1


def _print_target() -> None:
    """Назвать проверяемую базу: «OK» без адреса БД обманчиво."""
    from app.core.config import settings

    print(f"Проверяем БД: {describe_target(settings.DATABASE_URL)}")


def main() -> int:
    """Точка входа CLI: DSN из env-файла, сессия — только на чтение."""
    sys.path.insert(0, str(BACKEND_DIR))

    # До импорта приложения: pydantic отдал бы приоритет окружению процесса.
    from app.core.env_file import apply_env_file, env_file_path

    problem = env_file_problem(env_file_path())
    if problem is not None:
        print(f"Проверка дрейфа невозможна: {problem}.", file=sys.stderr)
        return 2
    apply_env_file()

    from app.core.database import async_session

    _print_target()

    async def _run() -> int:
        async with async_session() as session:
            return await run_check(session)

    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
