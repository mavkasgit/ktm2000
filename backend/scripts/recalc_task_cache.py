"""
Скрипт для верификации кэша задач из StockTransaction ledger.

После Этапа 4 cached_* колонки удалены, кэш вычисляется на лету через
StockProjectionManager.get_task_cache(). Скрипт проверяет, что для всех
задач get_task_cache возвращает корректные значения (сверка с прямым SQL).

Usage:
    cd backend
    python -c "import asyncio; from scripts.recalc_task_cache import main; asyncio.run(main())"
"""
import asyncio
from decimal import Decimal

from sqlalchemy import case, func, select

from app.core.database import async_session
from app.models.work_task import WorkTask
from app.stock.models import Reason, StockTransaction
from app.stock.services import StockProjectionManager


async def main():
    async with async_session() as db:
        tasks = (await db.execute(select(WorkTask))).scalars().all()
        print(f"Найдено задач: {len(tasks)}")

        pm = StockProjectionManager()
        errors = 0
        verified = 0
        for task in tasks:
            try:
                cache = await pm.get_task_cache(db, task.id)

                # SQL-верификация: net TRANSFER_RECEIVE (issued = received only)
                sql_issued = await db.scalar(
                    select(
                        func.coalesce(
                            func.sum(
                                case(
                                    (
                                        StockTransaction.reverses_id.is_(None),
                                        StockTransaction.quantity,
                                    ),
                                    else_=-StockTransaction.quantity,
                                )
                            ),
                            0,
                        )
                    ).where(
                        StockTransaction.task_id == task.id,
                        StockTransaction.reason == Reason.TRANSFER_RECEIVE,
                    )
                ) or Decimal("0")

                if cache["issued_quantity"] != sql_issued:
                    print(f"  [{task.id}] MISMATCH issued: cache={cache['issued_quantity']}, sql={sql_issued}")
                    errors += 1
                    continue

                verified += 1
                if verified % 50 == 0:
                    print(f"  [{task.id}] verified OK...")
            except Exception as e:
                errors += 1
                print(f"  [{task.id}] ОШИБКА: {e}")

        print(f"\nГотово! Проверено: {verified}, Ошибок: {errors}")


if __name__ == "__main__":
    asyncio.run(main())