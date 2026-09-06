"""Прямой статус-ассерт после complete_task (тикет #132).

``sync_work_task_status`` — ЯВНЫЙ шаг оркестратора complete_task (без
event-bus). Здесь проверяется результат синхронизации по факту ledger:
- частичная порция → ``partially_completed``;
- полная порция с авто-передачей на следующий участок (cross-GHP) →
  ``completed``: transferred >= planned после transfer_send внутри
  auto_create_transfer_after_complete.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, ProductType, Section, User, UserRole
from app.models.internal_plan import InternalPlan, InternalPlanStatus, SectionPlanLine
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.work_task import WorkTask, WorkTaskStatus
from app.stock import Reason, StockCommand, StockCommandService
from app.services.shopfloor.operations_tasks import complete_task
from tests.stock.helpers import record_transfer_receive
from tests.test_integrity_invariants import assert_no_stock_ledger_invariants_violations

pytestmark = pytest.mark.asyncio


# ─── fixtures ────────────────────────────────────────────────────────────────


async def _make_single_stage_setup(
    session: AsyncSession, *, sku: str = "STAT-S1", qty: Decimal = Decimal("10"),
) -> dict:
    """Один этап в одном GHP — без передачи дальше (частичная порция)."""
    user = User(
        username=f"{sku}@local",
        email=f"{sku}@local",
        full_name="Status Sync Op",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()

    raw = Section(code=f"{sku}-RAW", name="Raw", type="raw_stock", is_active=True, sort_order=0)
    prod = Section(code=f"{sku}-PROD", name="Production", type="laser", is_active=True, sort_order=1)
    session.add_all([raw, prod])
    await session.flush()

    spg = StorageProductionGroup(code=f"{sku}-SPG", name="SPG", is_active=True, sort_order=0)
    session.add(spg)
    await session.flush()
    session.add(SpgSection(spg_id=spg.id, section_id=prod.id, sort_order=0))

    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    route = ProductionRoute(name=f"R-{sku}", is_active=True)
    session.add(route)
    await session.flush()
    stage = RouteStage(route_id=route.id, sequence=1, section_id=prod.id, is_final=True)
    session.add(stage)
    await session.flush()
    session.add(RouteOperation(route_stage_id=stage.id, sequence=1, operation_code="OP1", operation_name="Op1"))

    await session.flush()

    plan = ProductionPlan(
        plan_no=f"P-{sku}", name="p", status=ProductionPlanStatus.approved,
        period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
    )
    session.add(plan)
    await session.flush()

    pos = PlanPosition(
        production_plan_id=plan.id, product_id=product.id,
        source_type=PlanSourceType.manual, source_sku=product.sku, source_name=product.name,
        quantity=qty, source_payload={}, status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid, validation_errors=[],
        period_start=plan.period_start, period_end=plan.period_end,
        has_pack_ops=False, route_id=route.id, route_assigned_at=None,
    )
    session.add(pos)
    await session.flush()

    internal_plan = InternalPlan(production_plan_id=plan.id, status=InternalPlanStatus.active)
    session.add(internal_plan)
    await session.flush()

    line = SectionPlanLine(
        internal_plan_id=internal_plan.id,
        plan_position_id=pos.id, section_id=prod.id,
        route_stage_id=stage.id, product_id=product.id,
        route_id=route.id, sequence=1, planned_quantity=qty,
    )
    session.add(line)
    await session.flush()

    task = WorkTask(
        section_plan_line_id=line.id, section_id=prod.id,
        product_id=product.id, route_stage_id=stage.id,
        planned_quantity=qty, status=WorkTaskStatus.ready,
        due_date=plan.period_end,
    )
    session.add(task)
    await session.commit()

    return {"user": user, "product": product, "task": task, "raw": raw, "prod": prod}


async def _make_two_ghp_setup(
    session: AsyncSession, *, sku: str = "STAT-X", qty: Decimal = Decimal("10"),
) -> dict:
    """Два этапа в разных GHP: авто-передача между ними возможна (тикет #91)."""
    user = User(
        username=f"{sku}@local",
        email=f"{sku}@local",
        full_name="Status Sync Op X",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()

    sec1 = Section(code=f"{sku}-S1", name="S1", type="production", is_active=True, sort_order=0)
    sec2 = Section(code=f"{sku}-S2", name="S2", type="production", is_active=True, sort_order=1)
    raw = Section(code=f"{sku}-RAW", name="Raw", type="raw_stock", is_active=True, sort_order=2)
    session.add_all([sec1, sec2, raw])
    await session.flush()

    spg_a = StorageProductionGroup(code=f"{sku}-A", name="A", is_active=True, sort_order=0)
    spg_b = StorageProductionGroup(code=f"{sku}-B", name="B", is_active=True, sort_order=1)
    session.add_all([spg_a, spg_b])
    await session.flush()
    session.add_all([
        SpgSection(spg_id=spg_a.id, section_id=sec1.id, sort_order=0),
        SpgSection(spg_id=spg_b.id, section_id=sec2.id, sort_order=0),
    ])

    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    route = ProductionRoute(name=f"R-{sku}", is_active=True)
    session.add(route)
    await session.flush()
    stages = []
    for idx, (sec, code) in enumerate([(sec1, "OP1"), (sec2, "OP2")], start=1):
        stage = RouteStage(route_id=route.id, sequence=idx, section_id=sec.id, is_final=(idx == 2))
        session.add(stage)
        await session.flush()
        session.add(RouteOperation(route_stage_id=stage.id, sequence=1, operation_code=code, operation_name=code))
        stages.append(stage)

    await session.flush()

    plan = ProductionPlan(
        plan_no=f"P-{sku}", name="p", status=ProductionPlanStatus.approved,
        period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
    )
    session.add(plan)
    await session.flush()

    pos = PlanPosition(
        production_plan_id=plan.id, product_id=product.id,
        source_type=PlanSourceType.manual, source_sku=product.sku, source_name=product.name,
        quantity=qty, source_payload={}, status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid, validation_errors=[],
        period_start=plan.period_start, period_end=plan.period_end,
        has_pack_ops=False, route_id=route.id, route_assigned_at=None,
    )
    session.add(pos)
    await session.flush()

    internal_plan = InternalPlan(production_plan_id=plan.id, status=InternalPlanStatus.active)
    session.add(internal_plan)
    await session.flush()

    lines = []
    for idx, (sec, stage) in enumerate(zip([sec1, sec2], stages), start=1):
        line = SectionPlanLine(
            internal_plan_id=internal_plan.id,
            plan_position_id=pos.id, section_id=sec.id,
            route_stage_id=stage.id, product_id=product.id,
            route_id=route.id, sequence=idx, planned_quantity=qty,
        )
        session.add(line)
        lines.append(line)
    await session.flush()

    task_a = WorkTask(
        section_plan_line_id=lines[0].id, section_id=sec1.id,
        product_id=product.id, route_stage_id=stages[0].id,
        planned_quantity=qty, status=WorkTaskStatus.ready,
        due_date=plan.period_end,
    )
    task_b = WorkTask(
        section_plan_line_id=lines[1].id, section_id=sec2.id,
        product_id=product.id, route_stage_id=stages[1].id,
        planned_quantity=qty, status=WorkTaskStatus.waiting_previous,
        due_date=plan.period_end,
    )
    session.add_all([task_a, task_b])
    await session.commit()

    return {"user": user, "product": product, "task_a": task_a, "task_b": task_b, "raw": raw}


async def _issue_to(session: AsyncSession, fx: dict, task: WorkTask, *, quantity: Decimal) -> None:
    """Выдача материала на конкретную задачу: MANUAL_IN + TRANSFER_RECEIVE."""
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=fx["product"].id,
        from_location_id=None,
        to_location_id=fx["raw"].id,
        quantity=quantity,
        reason=Reason.MANUAL_IN,
        created_by=fx["user"].id,
    ))
    await record_transfer_receive(
        session,
        product_id=fx["product"].id,
        from_location_id=fx["raw"].id,
        to_location_id=task.section_id,
        quantity=quantity,
        task_id=task.id,
        created_by=fx["user"].id,
    )
    task.status = WorkTaskStatus.in_progress
    await session.commit()


# ─── tests ──────────────────────────────────────────────────────────────────


async def test_complete_task_syncs_status_to_partially_completed(session: AsyncSession):
    """Частичная порция: и ответ complete_task, и задача в partially_completed."""
    fx = await _make_single_stage_setup(session, sku="STAT-PART")
    await _issue_to(session, fx, fx["task"], quantity=Decimal("10"))

    result = await complete_task(
        session,
        task_id=fx["task"].id,
        good_quantity=Decimal("4"),
        defect_quantity=Decimal("0"),
        actor_id=fx["user"].id,
    )
    await session.commit()

    assert result["status"] == WorkTaskStatus.partially_completed.value
    task = await session.get(WorkTask, fx["task"].id)
    assert task.status == WorkTaskStatus.partially_completed

    await assert_no_stock_ledger_invariants_violations(session, context="status-sync-partial")


async def test_completed_requires_transfer_beyond_production(session: AsyncSession):
    """Полная порция без передачи: produced == planned, но transferred == 0 —
    резолвер статуса не даёт completed (нужна передача дальше) и не даёт
    partially_completed (частичный — только при produced < planned): статус
    остаётся прежним in_progress. Документирует семантику sync_work_task_status."""
    fx = await _make_single_stage_setup(session, sku="STAT-FULL")
    await _issue_to(session, fx, fx["task"], quantity=Decimal("10"))

    await complete_task(
        session,
        task_id=fx["task"].id,
        good_quantity=Decimal("10"),
        defect_quantity=Decimal("0"),
        actor_id=fx["user"].id,
    )
    await session.commit()

    task = await session.get(WorkTask, fx["task"].id)
    assert task.status == WorkTaskStatus.in_progress

    await assert_no_stock_ledger_invariants_violations(session, context="status-sync-full-no-transfer")


async def test_auto_transfer_next_completes_source_task(session: AsyncSession):
    """Полная порция + auto_transfer_next (cross-GHP): источник уходит в completed,
    приёмник — в in_progress; ответ complete_task несёт итоговый статус."""
    fx = await _make_two_ghp_setup(session, sku="STAT-DONE")
    await _issue_to(session, fx, fx["task_a"], quantity=Decimal("10"))

    result = await complete_task(
        session,
        task_id=fx["task_a"].id,
        good_quantity=Decimal("10"),
        defect_quantity=Decimal("0"),
        actor_id=fx["user"].id,
        auto_transfer_next=True,
    )
    await session.commit()

    assert result["status"] == WorkTaskStatus.completed.value
    task_a = await session.get(WorkTask, fx["task_a"].id)
    task_b = await session.get(WorkTask, fx["task_b"].id)
    assert task_a.status == WorkTaskStatus.completed
    assert task_b.status == WorkTaskStatus.in_progress

    await assert_no_stock_ledger_invariants_violations(session, context="status-sync-auto-transfer")
