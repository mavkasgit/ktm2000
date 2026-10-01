#!/usr/bin/env python
"""CLI script for demo production data only (remainders, defects).

Not part of the regular seed pipeline. Use from Dev Settings UI
(POST /api/routes-seed/demo-production) or run this script manually.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session
from app.seeds.seeders.demo_production_seeder import seed_demo_production

logger = logging.getLogger(__name__)


async def main() -> None:
    async with async_session() as db:
        try:
            stats = await seed_demo_production(db)
            await db.commit()
            print("Demo production seed completed:")
            for key, value in stats.items():
                print(f"  {key}: {value}")
        except Exception as e:
            # Точка входа CLI: откатываем транзакцию и выходим с кодом 1 на любой
            # ошибке сидинга, но не глотаем её — traceback уходит в лог.
            logger.exception("Demo production seed failed")
            await db.rollback()
            print(f"Demo seed failed: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())