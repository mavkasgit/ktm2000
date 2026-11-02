"""Фоновая уборка сирот в ``imports/`` (#288).

Образец — ``backup_scheduler``: цикл в lifespan-задаче приложения, advisory
lock в PostgreSQL на каждый проход (несколько процессов с одной базой не
удвоят работу), лог-отчёт с списком удалённых файлов. Порог «сутки» и
правила выбора — в ``app.services.import_storage.sweep_orphan_import_files``.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from app.core.config import settings
from app.core.database import async_session
from app.services.import_storage import sweep_orphan_import_files

logger = logging.getLogger("app.import_orphan_scheduler")

#: Произвольный уникальный 64-битный ключ advisory lock (не пересекается с
#: ``BACKUP_SCHEDULER_LOCK_ID``).
ORPHAN_SWEEP_LOCK_ID = 618293455


async def run_orphan_sweep_once():
    """Один проход уборки; ``None`` — если слот lock уже у другого процесса."""
    async with async_session() as session, session.begin():
        locked = (
            await session.execute(
                text("SELECT pg_try_advisory_xact_lock(:id)"),
                {"id": ORPHAN_SWEEP_LOCK_ID},
            )
        ).scalar()
        if not locked:
            logger.debug("Уборка imports/: другой процесс уже убирает, пропуск.")
            return None
        report = await sweep_orphan_import_files(session)
    logger.info("Уборка imports/: %s", report.summary())
    return report


async def start_import_orphan_scheduler():
    """Цикл планировщика: первый проход сразу после старта, далее по интервалу."""
    logger.info(
        "Планировщик уборки imports/ запущен (порог %s ч, интервал %s мин)",
        settings.IMPORT_ORPHAN_TTL_HOURS,
        settings.IMPORT_ORPHAN_SWEEP_INTERVAL_MINUTES,
    )
    interval_seconds = max(60, settings.IMPORT_ORPHAN_SWEEP_INTERVAL_MINUTES * 60)
    while True:
        try:
            await run_orphan_sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ошибка в цикле уборки imports/")
        await asyncio.sleep(interval_seconds)
