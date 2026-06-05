from __future__ import annotations

from sqlalchemy import delete, exists
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import Defect, DefectDecision, DefectItem, TransferDiscrepancyDefectItem
from app.models.imports import ImportBatch, ImportFile
from app.models.internal_plan import InternalPlan, SectionPlanLine
from app.models.movement import Movement
from app.models.production_plan import PlanChangeItem, PlanChangeSet, PlanPosition, PositionStatusHistory, ProductionPlan
from app.models.release_batch import ReleaseBatch, ReleaseBatchPosition
from app.models.rework_task import ReworkTask
from app.models.transfer import Transfer, TransferDiscrepancy
from app.models.spg_remainder import SpgRemainder
from app.models.work_task import WorkTask


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

    await execute_delete(Movement, "movements")
    await execute_delete(TransferDiscrepancy, "transfer_discrepancies")
    await execute_delete(Transfer, "transfers")
    await execute_delete(SpgRemainder, "spg_remainders")

    await execute_delete(WorkTask, "work_tasks")
    await execute_delete(SectionPlanLine, "section_plan_lines")
    await execute_delete(InternalPlan, "internal_plans")

    await execute_delete(ReleaseBatchPosition, "release_batch_positions")
    await execute_delete(ReleaseBatch, "release_batches")

    await execute_delete(PositionStatusHistory, "position_status_history")
    await execute_delete(PlanChangeItem, "plan_change_items")
    await execute_delete(PlanChangeSet, "plan_change_sets")
    await execute_delete(PlanPosition, "plan_positions")
    await execute_delete(ImportBatch, "import_batches")
    await execute_delete(ProductionPlan, "production_plans")

    result = await db.execute(
        delete(ImportFile).where(
            ~exists().where(ImportBatch.source_file_id == ImportFile.id)
        )
    )
    deleted["orphan_import_files"] = result.rowcount or 0

    return deleted
