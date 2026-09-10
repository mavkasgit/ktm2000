"""Удаление батча импорта: 409 с blockers/safe_action + частичное удаление (тикет #167, спека §4.4)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.imports import ImportBatch, ImportBatchMode, ImportFile
from app.models.internal_plan import InternalPlan, InternalPlanStatus, SectionPlanLine
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanChangeAction,
    PlanChangeItem,
    PlanChangeItemStatus,
    PlanChangeSet,
    PlanChangeSetStatus,
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteStage
from app.models.section import Section
from app.models.work_task import WorkTask, WorkTaskStatus
from tests.test_integrity_invariants import assert_no_invariants_violations
from app.models.transfer import Transfer
from app.stock.models import Reason
from app.stock.services import StockCommand, StockCommandService
from app.models.user import User, UserRole
from app.transfers.services import transfer_send

pytestmark = pytest.mark.asyncio


async def _make_product(session: AsyncSession, sku: str) -> Product:
    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()
    return product


async def _make_plan_file_batch(session: AsyncSession, tag: str) -> tuple[ProductionPlan, ImportBatch]:
    plan = ProductionPlan(
        plan_no=f"PLAN-{tag}", name=f"Plan {tag}", status=ProductionPlanStatus.draft,
        period_start=date(2026, 5, 1), period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()
    file = ImportFile(
        original_filename=f"{tag}.xlsx",
        stored_path=f"/tmp/{tag}.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_extension=".xlsx",
        detected_format="zip-workbook",
        file_sha256=f"{tag:<64}"[:64].replace(" ", "0"),
        size_bytes=10,
    )
    session.add(file)
    await session.flush()
    batch = ImportBatch(
        source_file_id=file.id, production_plan_id=plan.id, mode=ImportBatchMode.create_plan,
        sheet_name="План", header_row_number=1, total_rows=2, parsed_rows=2, summary={},
    )
    session.add(batch)
    await session.flush()
    return plan, batch


def _make_position(
    session: AsyncSession, plan: ProductionPlan, product: Product, batch: ImportBatch,
    *, status: PlanPositionStatus, row: int,
) -> PlanPosition:
    pos = PlanPosition(
        production_plan_id=plan.id, product_id=product.id, import_batch_id=batch.id,
        source_type=PlanSourceType.excel_import, source_sku=product.sku, source_name=product.name,
        quantity=Decimal("10"), source_payload={}, source_row_number=row,
        source_fingerprint=f"fp-{batch.id}-{row}", source_row_hash=f"hash-{batch.id}-{row}",
        status=status, validation_status=PlanPositionValidationStatus.valid, validation_errors=[],
        period_start=plan.period_start, period_end=plan.period_end, has_pack_ops=False,
    )
    session.add(pos)
    return pos


async def _make_change_set(
    session: AsyncSession, plan: ProductionPlan, batch: ImportBatch,
    positions: list[PlanPosition], *, applied: bool,
) -> PlanChangeSet:
    cs = PlanChangeSet(
        production_plan_id=plan.id, import_batch_id=batch.id, summary={},
        status=PlanChangeSetStatus.applied if applied else PlanChangeSetStatus.draft,
    )
    session.add(cs)
    await session.flush()
    for pos in positions:
        session.add(
            PlanChangeItem(
                change_set_id=cs.id, source_row_number=pos.source_row_number, source_ref=f"rows:{pos.source_row_number}",
                change_action=PlanChangeAction.create_position, before_data=None,
                status=PlanChangeItemStatus.pending,
                after_data={"product_id": pos.product_id, "quantity": "10"},
                plan_position_id=pos.id,
            )
        )
    await session.flush()
    return cs


async def _make_transfer_chain(
    session: AsyncSession, plan: ProductionPlan, product: Product, pos: PlanPosition, *, tag: str,
) -> Transfer:
#: Передача создаётся доменным transfer_send: две проводки StockTransaction
#: (SEND+RECEIVE) пишутся одним каноническим путём — S6/D1 инварианты держатся
#: по построению, и assert_no_invariants_violations применим к тесту целиком.
    user = User(username=f"{tag}-op", full_name=f"Operator {tag}", role=UserRole.operator)
    session.add(user)
    await session.flush()
    sec1 = Section(code=f"{tag}-S1", name="S1", type="laser", is_active=True, sort_order=1)
    sec2 = Section(code=f"{tag}-S2", name="S2", type="laser", is_active=True, sort_order=2)
    session.add_all([sec1, sec2])
    await session.flush()
    route = ProductionRoute(name=f"R-{tag}", is_active=True)
    session.add(route)
    await session.flush()
    st1 = RouteStage(route_id=route.id, sequence=1, section_id=sec1.id, is_final=False)
    st2 = RouteStage(route_id=route.id, sequence=2, section_id=sec2.id, is_final=True)
    session.add_all([st1, st2])
    await session.flush()
    internal = InternalPlan(production_plan_id=plan.id, status=InternalPlanStatus.active)
    session.add(internal)
    await session.flush()
    line1 = SectionPlanLine(
        internal_plan_id=internal.id, plan_position_id=pos.id, section_id=sec1.id,
        product_id=product.id, route_id=route.id, route_stage_id=st1.id,
        sequence=1, planned_quantity=Decimal("10"),
    )
    line2 = SectionPlanLine(
        internal_plan_id=internal.id, plan_position_id=pos.id, section_id=sec2.id,
        product_id=product.id, route_id=route.id, route_stage_id=st2.id,
        sequence=2, planned_quantity=Decimal("10"),
    )
    session.add_all([line1, line2])
    await session.flush()
    task1 = WorkTask(
        section_plan_line_id=line1.id, section_id=sec1.id, product_id=product.id,
        route_stage_id=st1.id, planned_quantity=Decimal("10"), status=WorkTaskStatus.ready,
    )
    task2 = WorkTask(
        section_plan_line_id=line2.id, section_id=sec2.id, product_id=product.id,
        route_stage_id=st2.id, planned_quantity=Decimal("10"), status=WorkTaskStatus.waiting_previous,
    )
    session.add_all([task1, task2])
    await session.flush()
    #: Материал должен реально лежать на участке-источнике: transfer_send
    #: списывает остаток StockBalance (SEND-проводка), иначе — Insufficient stock.
    await StockCommandService().record(
        session,
        StockCommand(
            product_id=product.id,
            from_location_id=None,
            to_location_id=sec1.id,
            quantity=Decimal("5"),
            reason=Reason.MANUAL_IN,
            created_by=user.id,
        ),
    )
    result = await transfer_send(
        session, from_task_id=task1.id, to_task_id=task2.id, quantity=Decimal("5"),
        actor_id=user.id, allow_over_plan=True,
    )
    transfer = await session.get(Transfer, result["transfer_id"])
    assert transfer is not None
    return transfer


async def test_delete_batch_all_drafts_full_delete(session: AsyncSession, client) -> None:
    product = await _make_product(session, "DELB-D1")
    plan, batch = await _make_plan_file_batch(session, "DELB-D1")
    positions = [
        _make_position(session, plan, product, batch, status=PlanPositionStatus.draft, row=2),
        _make_position(session, plan, product, batch, status=PlanPositionStatus.draft, row=3),
    ]
    await session.flush()
    await _make_change_set(session, plan, batch, positions, applied=True)
    await session.commit()

    resp = await client.delete(f"/api/production-plans/{plan.id}/batches/{batch.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": True, "batch_id": batch.id}
    await assert_no_invariants_violations(session, context="batch-delete-drafts")


async def test_delete_batch_released_409_then_safe_delete(session: AsyncSession, client) -> None:
    product = await _make_product(session, "DELB-R1")
    plan, batch = await _make_plan_file_batch(session, "DELB-R1")
    draft_pos = _make_position(session, plan, product, batch, status=PlanPositionStatus.draft, row=2)
    rel_pos = _make_position(session, plan, product, batch, status=PlanPositionStatus.released, row=3)
    await session.flush()
    cs = await _make_change_set(session, plan, batch, [draft_pos, rel_pos], applied=True)
    await session.commit()
    plan_id, batch_id = plan.id, batch.id
    draft_id, rel_id, cs_id = draft_pos.id, rel_pos.id, cs.id

    resp = await client.delete(f"/api/production-plans/{plan_id}/batches/{batch_id}")
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["code"] == "batch_has_released_positions"
    assert body["blockers"] == [{"position_id": rel_id, "reason": "released"}]
    assert body["safe_action"] == "delete_drafts_only"
    assert body["drafts"] == 1

    safe = await client.delete(f"/api/production-plans/{plan_id}/batches/{batch_id}?delete_drafts_only=true")
    assert safe.status_code == 200, safe.text
    safe_body = safe.json()
    assert safe_body["deleted"] is False
    assert safe_body["deleted_drafts"] == 1
    assert safe_body["blockers"] == [{"position_id": rel_id, "reason": "released"}]

    assert await session.get(PlanPosition, draft_id) is None
    assert await session.get(PlanPosition, rel_id) is not None
    assert await session.get(PlanChangeSet, cs_id) is not None

    again = await client.delete(f"/api/production-plans/{plan_id}/batches/{batch_id}")
    assert again.status_code == 409, again.text
    await assert_no_invariants_violations(session, context="batch-delete-safe")


async def test_delete_batch_transfer_blocker_409(session: AsyncSession, client) -> None:
    product = await _make_product(session, "DELB-T1")
    plan, batch = await _make_plan_file_batch(session, "DELB-T1")
    pos = _make_position(session, plan, product, batch, status=PlanPositionStatus.approved, row=2)
    await session.flush()
    transfer = await _make_transfer_chain(session, plan, product, pos, tag="DELB-T1")
    await session.commit()
    plan_id, batch_id = plan.id, batch.id
    pos_id, transfer_id, transfer_no = pos.id, transfer.id, transfer.transfer_no

    resp = await client.delete(f"/api/production-plans/{plan_id}/batches/{batch_id}")
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["code"] == "downstream_transfers_exist"
    assert body["blockers"] == [{"position_id": pos_id, "reason": f"transfer №{transfer_no}"}]
    assert body["drafts"] == 0

    safe = await client.delete(f"/api/production-plans/{plan_id}/batches/{batch_id}?delete_drafts_only=true")
    assert safe.status_code == 200, safe.text
    assert await session.get(PlanPosition, pos_id) is not None
    assert await session.get(Transfer, transfer_id) is not None
    await assert_no_invariants_violations(session, context="batch-delete-transfer")
