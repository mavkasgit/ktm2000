from __future__ import annotations

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import (
    Defect,
    DefectDecision,
    DefectItem,
    TransferDiscrepancyDefectItem,
)
from app.models.imports import ImportBatch, ImportFile
from app.models.internal_plan import InternalPlan, SectionPlanLine
from app.models.production_plan import (
    PlanChangeItem,
    PlanChangeSet,
    PlanPosition,
    ProductionPlan,
)
from app.models.release_batch import ReleaseBatch, ReleaseBatchPosition
from app.models.rework_task import ReworkTask
from app.models.transfer import Transfer, TransferDiscrepancy
from app.models.work_task import WorkTask
from app.stock.import_models import StockImportBatch
from app.stock.models import StockBalance, StockTransaction
from app.services.import_storage import schedule_import_file_purge


async def clear_generated_production_data(db: AsyncSession) -> dict[str, int]:
    """Delete generated/imported production data before force reseeding routes."""
    deleted: dict[str, int] = {}

    async def execute_delete(model, key: str) -> None:
        result = await db.execute(delete(model))
        deleted[key] = result.rowcount or 0

    await execute_delete(TransferDiscrepancyDefectItem, "transfer_discrepancy_defect_items")
    await execute_delete(DefectDecision, "defect_decisions")
    await execute_delete(DefectItem, "defect_items")
    await execute_delete(ReworkTask, "rework_tasks")
    await execute_delete(Defect, "defects")

    await execute_delete(TransferDiscrepancy, "transfer_discrepancies")
    await execute_delete(StockBalance, "stock_balances")
    await execute_delete(StockTransaction, "stock_transactions")
    await execute_delete(Transfer, "transfers")

    await execute_delete(WorkTask, "work_tasks")
    await execute_delete(SectionPlanLine, "section_plan_lines")
    await execute_delete(InternalPlan, "internal_plans")

    await execute_delete(ReleaseBatchPosition, "release_batch_positions")
    await execute_delete(ReleaseBatch, "release_batches")

    await execute_delete(PlanChangeItem, "plan_change_items")
    await execute_delete(PlanChangeSet, "plan_change_sets")
    await execute_delete(PlanPosition, "plan_positions")
    await execute_delete(ImportBatch, "import_batches")
    await execute_delete(ProductionPlan, "production_plans")

    # На ``import_files`` ссылаются две таблицы: план импорта и журнал импорта
    # остатков. Раньше здесь учитывался только план, и демо-сид падал на FK
    # ``fk_stock_import_batches_file_id_import_files``, если в базе была хотя бы
    # одна загрузка остатков: весь прогон откатывался и план не появлялся.
    #
    # #288: вместе со строкой уходит и файл с диска («записи нет — файла нет»).
    # Пути снимаем ДО удаления и по тому же предикату, что и сам DELETE:
    # строки, пережившие очистку (например, под батчами остатков), остаются
    # со своими файлами. Стирание байтов — на коммите вызывающей транзакции
    # (слушатель ``import_storage``), поэтому откат сида ничего не теряет.
    doomed_paths = (
        await db.execute(
            select(ImportFile.stored_path).where(
                ~exists().where(ImportBatch.source_file_id == ImportFile.id),
                ~exists().where(StockImportBatch.file_id == ImportFile.id),
            )
        )
    ).scalars().all()
    schedule_import_file_purge(db, doomed_paths)
    result = await db.execute(
        delete(ImportFile).where(
            ~exists().where(ImportBatch.source_file_id == ImportFile.id),
            ~exists().where(StockImportBatch.file_id == ImportFile.id),
        )
    )
    deleted["orphan_import_files"] = result.rowcount or 0

    return deleted
