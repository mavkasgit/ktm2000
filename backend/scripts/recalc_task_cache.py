"""
Скрипт для пересчета кэша всех существующих задач.
Запускать после фикса инициализации cached_available_quantity.

Usage:
    cd backend
    python -c "import asyncio; from scripts.recalc_task_cache import main; asyncio.run(main())"
"""
import asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.models.work_task import WorkTask
from app.services.shopfloor_service import _refresh_task_cache, _refresh_section_plan_line_cache


async def main():
    async with async_session() as db:
        tasks = (await db.execute(select(WorkTask))).scalars().all()
        print(f"Найдено задач: {len(tasks)}")

        updated = 0
        errors = 0
        for task in tasks:
            try:
                await _refresh_task_cache(db, task.id)
                await _refresh_section_plan_line_cache(db, task.section_plan_line_id)
                updated += 1
                print(f"  [{task.id}] available={task.cached_available_quantity}, issued={task.cached_issued_quantity}")
            except Exception as e:
                errors += 1
                print(f"  [{task.id}] ОШИБКА: {e}")

        await db.commit()
        print(f"\nГотово! Обновлено: {updated}, Ошибок: {errors}")


if __name__ == "__main__":
    asyncio.run(main())
