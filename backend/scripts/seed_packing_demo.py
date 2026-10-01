#!/usr/bin/env python
"""CLI — демо-данные «Участков» на основе реального упаковочного плана.

    npm run db:seed:packing-demo            # снести оперативку и пересобрать демо
    npm run db:seed:packing-demo -- --keep  # пересобрать демо поверх текущих данных
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session
from app.seeds.seeders.packing_plan_demo_seeder import seed_packing_plan_demo

logger = logging.getLogger(__name__)


async def main():
    reset = "--keep" not in sys.argv
    async with async_session() as db:
        try:
            result = await seed_packing_plan_demo(db, reset=reset)
            print("Демо упаковочного плана загружены:")
            for key, value in result.items():
                print(f"  {key}: {value}")
        except Exception as e:
            # Точка входа CLI: откатываем транзакцию и выходим с кодом 1 на любой
            # ошибке сидинга, но не глотаем её — traceback уходит в лог.
            logger.exception("Демо упаковочного плана: ошибка загрузки")
            await db.rollback()
            print(f"Не удалось загрузить демо-данные: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
