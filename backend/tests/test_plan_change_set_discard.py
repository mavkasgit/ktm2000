"""Отклонение черновика пакета импорта: DELETE .../change-sets/{id} (#256).

Роут удаляет черновик сета и обязан записать в аудит событие «импорт
отклонён» с `entity_id = import_batch_id`. До фикса `batch_id` читался уже
*после* `log_action`, то есть роут падал `NameError` на любом вызове.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditEntityType, AuditLog
from app.models.imports import ImportBatch, ImportBatchMode, ImportFile
from app.models.production_plan import (
    PlanChangeSet,
    PlanChangeSetStatus,
    ProductionPlan,
    ProductionPlanStatus,
)

pytestmark = pytest.mark.asyncio


async def _make_plan(session: AsyncSession, tag: str) -> ProductionPlan:
    plan = ProductionPlan(
        plan_no=f"PLAN-{tag}",
        name=f"Plan {tag}",
        status=ProductionPlanStatus.draft,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()
    return plan


async def _make_batch(session: AsyncSession, plan: ProductionPlan, tag: str) -> ImportBatch:
    file = ImportFile(
        original_filename=f"{tag}.xlsx",
        stored_path=f"/tmp/{tag}.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_extension=".xlsx",
        detected_format="zip-workbook",
        file_sha256=tag.ljust(64, "0")[:64],
        size_bytes=10,
    )
    session.add(file)
    await session.flush()
    batch = ImportBatch(
        source_file_id=file.id,
        production_plan_id=plan.id,
        mode=ImportBatchMode.create_plan,
        sheet_name="План",
        header_row_number=1,
        total_rows=1,
        parsed_rows=1,
        summary={},
    )
    session.add(batch)
    await session.flush()
    return batch


async def test_discard_draft_change_set_logs_import_batch_audit(
    session: AsyncSession, client
) -> None:
    plan = await _make_plan(session, "DISCARD-1")
    batch = await _make_batch(session, plan, "discard-1")
    change_set = PlanChangeSet(
        production_plan_id=plan.id,
        import_batch_id=batch.id,
        status=PlanChangeSetStatus.draft,
        summary={},
    )
    session.add(change_set)
    await session.flush()
    change_set_id = change_set.id
    batch_id = batch.id

    response = await client.delete(f"/api/production-plans/{plan.id}/change-sets/{change_set_id}")

    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": True, "change_set_id": change_set_id}
    assert (await session.get(PlanChangeSet, change_set_id)) is None

    audit_rows = (
        (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.entity_type == AuditEntityType.IMPORT_BATCH.value,
                    AuditLog.entity_id == batch_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1
    assert audit_rows[0].action == "cancel"
