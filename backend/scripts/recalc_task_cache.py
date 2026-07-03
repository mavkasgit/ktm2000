"""
Скрипт для пересчета кэша всех существующих задач из StockTransaction ledger.

Usage:
    cd backend
    python -c "import asyncio; from scripts.recalc_task_cache import main; asyncio.run(main())"
"""
import asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.models.work_task import WorkTask
from app.stock.services import StockProjectionManager
from app.services.shopfloor.cache import _refresh_section_plan_line_cache


async def main():
    async with async_session() as db:
        tasks = (await db.execute(select(WorkTask))).scalars().all()
        print(f"Найдено задач: {len(tasks)}")

        pm = StockProjectionManager()
        updated = 0
        errors = 0
        for task in tasks:
            try:
                # Создаём фиктивную транзакцию для вызова refresh_task_projection
                # для каждой задачи (пересчёт всех cached_* из StockTransaction)
                from app.stock.models import StockTransaction
                dummy_tx = StockTransaction(task_id=task.id)
                dummy_tx.task_id = task.id
                await pm.refresh_task_projection(db, dummy_tx)
                await _refresh_section_plan_line_cache(db, task.section_plan_line_id)
                updated += 1
                if updated % 50 == 0:
                    print(f"  [{task.id}] processed...")
            except Exception as e:
                errors += 1
                print(f"  [{task.id}] ОШИБКА: {e}")

        await db.commit()
        print(f"\nГотово! Обновлено: {updated}, Ошибок: {errors}")


if __name__ == "__main__":
    asyncio.run(main())
