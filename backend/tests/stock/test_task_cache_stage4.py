"""Тесты Этапа 4: WorkTask cleanup — cached_* удалены, кэш из ledger.

Проверяют:
- get_task_cache возвращает корректные значения из StockTransaction
- Компенсации учитываются при подсчёте transferred/received
- available_quantity для first-stage задач
- bulk-вариант get_tasks_cache_bulk
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
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
from app.models.techcard import Techcard, TechcardLine
from app.models.work_task import WorkTask, WorkTaskStatus
from app.stock import (
    QualityState,
    Reason,
    StockCommand,
    StockCommandService,
    StockTransaction,
)
from app.stock.models import LocationType
from app.stock.services import StockProjectionManager

pytestmark = pytest.mark.asyncio


async def _make_user(session: AsyncSession, sku: str = "stg4") -> User:
    user = User(username=sku, email=f"{sku}@local", password_hash="x", full_name="Stage4", role=UserRole.operator, is_active=True)
    session.add(user)
    await session.flush()
    return user


async def _make_product(session: AsyncSession, sku: str = "STG4") -> Product:
    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()
    return product


async def _make_location(session: AsyncSession, *, code: str, name: str, loc_type: str) -> Section:
    section = Section(
        code=code, name=name,
        kind="production" if loc_type in ("laser", "welding", "painting", "assembly") else loc_type,
        type=loc_type, is_active=True, sort_order=0,
    )
    session.add(section)
    await session.flush()
    return section


async def _setup_one_task(session: AsyncSession, *, sku: str = "STG4", qty: Decimal = Decimal("10")) -> dict:
    """Minimal topology: raw_stock → production section (first route stage)."""
    user = await _make_user(session, sku)
    raw = await _make_location(session, code=f"{sku}-RAW", name="Raw", loc_type="raw_stock")
    prod = await _make_location(session, code=f"{sku}-PROD", name="Production", loc_type="laser")
    scrap_loc = await _make_location(session, code=f"{sku}-SCR", name="Scrap", loc_type="scrap")

    product = await _make_product(session, sku)
    route = ProductionRoute(name=f"R-{sku}", is_active=True)
    session.add(route)
    await session.flush()
    stage = RouteStage(route_id=route.id, sequence=1, section_id=prod.id, is_final=True)
    session.add(stage)
    await session.flush()
    session.add(RouteOperation(route_stage_id=stage.id, sequence=1, operation_code="OP1", operation_name="Op1"))

    plan = ProductionPlan(plan_no=f"P-{sku}", name="p", status=ProductionPlanStatus.approved,
                          period_start=date(2026, 7, 1), period_end=date(2026, 7, 31))
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
        internal_plan_id=internal_plan.id, plan_position_id=pos.id, section_id=prod.id,
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
    return {"user": user, "product": product, "task": task, "raw": raw, "prod": prod, "scrap": scrap_loc}


async def _sql_sum_transactions(session: AsyncSession, task_id: int, reason: Reason) -> Decimal:
    return await session.scalar(
        select(func.coalesce(func.sum(StockTransaction.quantity), 0))
        .where(StockTransaction.task_id == task_id, StockTransaction.reason == reason)
    ) or Decimal("0")


async def _sql_net_transactions(session: AsyncSession, task_id: int, reason: Reason) -> Decimal:
    """Net sum with compensation handling."""
    from sqlalchemy import case
    net = await session.scalar(
        select(func.coalesce(func.sum(
            case(
                (StockTransaction.compensates_tx_id.is_(None), StockTransaction.quantity),
                else_=-StockTransaction.quantity,
            )
        ), 0))
        .where(StockTransaction.task_id == task_id, StockTransaction.reason == reason)
    )
    return net or Decimal("0")


# ─── tests ───────────────────────────────────────────────────────────────────


async def test_completed_qty_from_ledger(session: AsyncSession):
    """После complete_task: get_task_cache()['completed_quantity'] == SUM(StockTransaction)."""
    fx = await _setup_one_task(session)
    task = fx["task"]

    svc = StockCommandService()
    # Seed stock
    await svc.record(session, StockCommand(
        product_id=fx["product"].id, from_location_id=None, to_location_id=fx["raw"].id,
        quantity=Decimal("100"), reason=Reason.manual_in, created_by=fx["user"].id,
    ))
    # Issue
    await svc.record(session, StockCommand(
        product_id=fx["product"].id, from_location_id=fx["raw"].id, to_location_id=task.section_id,
        quantity=Decimal("10"), reason=Reason.issue_to_work, task_id=task.id, created_by=fx["user"].id,
    ))
    task.status = WorkTaskStatus.in_progress
    await session.commit()

    # Complete
    from app.services.shopfloor.operations_tasks import complete_task
    await complete_task(session, task_id=task.id, good_quantity=Decimal("8"), defect_quantity=Decimal("0"), actor_id=fx["user"].id)
    await session.commit()

    pm = StockProjectionManager()
    cache = await pm.get_task_cache(session, task.id)
    sql_sum = await _sql_sum_transactions(session, task.id, Reason.complete)
    assert cache["completed_quantity"] == sql_sum == Decimal("8")


async def test_issued_qty_from_ledger(session: AsyncSession):
    """После issue_to_work: get_task_cache()['issued_quantity'] == SUM(StockTransaction)."""
    fx = await _setup_one_task(session)
    task = fx["task"]

    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=fx["product"].id, from_location_id=None, to_location_id=fx["raw"].id,
        quantity=Decimal("100"), reason=Reason.manual_in, created_by=fx["user"].id,
    ))
    await svc.record(session, StockCommand(
        product_id=fx["product"].id, from_location_id=fx["raw"].id, to_location_id=task.section_id,
        quantity=Decimal("7"), reason=Reason.issue_to_work, task_id=task.id, created_by=fx["user"].id,
    ))
    task.status = WorkTaskStatus.in_progress
    await session.commit()

    pm = StockProjectionManager()
    cache = await pm.get_task_cache(session, task.id)
    sql_sum = await _sql_sum_transactions(session, task.id, Reason.issue_to_work)
    assert cache["issued_quantity"] == sql_sum == Decimal("7")


async def test_transferred_qty_net_from_ledger(session: AsyncSession):
    """После transfer_send + cancel: transferred_quantity учитывает компенсации."""
    fx = await _setup_one_task(session, sku="T4NET", qty=Decimal("20"))
    from_task = fx["task"]

    # Need a second section/task for transfer destination
    prod2 = await _make_location(session, code="T4NET-PROD2", name="Prod2", loc_type="laser")
    from app.models.route import RouteStage as _RS
    stage = await session.get(_RS, from_task.route_stage_id)
    route_id = stage.route_id
    stage2 = _RS(route_id=route_id, sequence=2, section_id=prod2.id, is_final=True)
    session.add(stage2)
    await session.flush()
    session.add(RouteOperation(route_stage_id=stage2.id, sequence=1, operation_code="OP2", operation_name="Op2"))

    from app.models.internal_plan import SectionPlanLine as SPL
    orig_line = await session.get(SPL, from_task.section_plan_line_id)
    line2 = SPL(
        internal_plan_id=orig_line.internal_plan_id,
        plan_position_id=orig_line.plan_position_id,
        section_id=prod2.id, product_id=fx["product"].id,
        route_id=route_id, route_stage_id=stage2.id, sequence=2, planned_quantity=Decimal("20"),
    )
    session.add(line2)
    await session.flush()
    to_task = WorkTask(
        section_plan_line_id=line2.id, section_id=prod2.id,
        product_id=fx["product"].id, route_stage_id=stage2.id,
        planned_quantity=Decimal("20"), status=WorkTaskStatus.waiting_previous,
    )
    session.add(to_task)
    await session.commit()

    # Seed stock, issue, complete on from_task
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=fx["product"].id, from_location_id=None, to_location_id=fx["raw"].id,
        quantity=Decimal("100"), reason=Reason.manual_in, created_by=fx["user"].id,
    ))
    await svc.record(session, StockCommand(
        product_id=fx["product"].id, from_location_id=fx["raw"].id, to_location_id=from_task.section_id,
        quantity=Decimal("15"), reason=Reason.issue_to_work, task_id=from_task.id, created_by=fx["user"].id,
    ))
    from_task.status = WorkTaskStatus.in_progress
    await svc.record(session, StockCommand(
        product_id=fx["product"].id, from_location_id=None, to_location_id=from_task.section_id,
        quantity=Decimal("15"), reason=Reason.complete, task_id=from_task.id, created_by=fx["user"].id,
    ))
    # Transfer send
    from app.transfers.services import transfer_send
    transfer = await transfer_send(
        session,
        from_task_id=from_task.id, to_task_id=to_task.id, quantity=Decimal("10"),
        actor_id=fx["user"].id,
    )
    await session.commit()

    pm = StockProjectionManager()
    from_cache = await pm.get_task_cache(session, from_task.id)
    net_sql = await _sql_net_transactions(session, from_task.id, Reason.transfer_send)
    assert from_cache["transferred_quantity"] == net_sql == Decimal("10")

    # Issue material on the target task so cancel validation passes
    to_task.status = WorkTaskStatus.in_progress
    await svc.record(session, StockCommand(
        product_id=fx["product"].id, from_location_id=fx["raw"].id, to_location_id=to_task.section_id,
        quantity=Decimal("10"), reason=Reason.issue_to_work, task_id=to_task.id, created_by=fx["user"].id,
    ))
    await session.commit()

    # Cancel transfer
    from app.transfers.services import cancel_transfer
    await cancel_transfer(session, transfer_id=transfer["transfer_id"], actor_id=fx["user"].id)
    await session.commit()

    from_cache2 = await pm.get_task_cache(session, from_task.id)
    net_sql2 = await _sql_net_transactions(session, from_task.id, Reason.transfer_send)
    # After cancel: send - compensation = 0
    assert from_cache2["transferred_quantity"] == net_sql2 == Decimal("0")


async def test_available_qty_from_ledger(session: AsyncSession):
    """Для first-stage задачи: available = planned + received + returned - issued."""
    fx = await _setup_one_task(session, sku="T4AVAIL", qty=Decimal("20"))
    task = fx["task"]

    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=fx["product"].id, from_location_id=None, to_location_id=fx["raw"].id,
        quantity=Decimal("100"), reason=Reason.manual_in, created_by=fx["user"].id,
    ))
    # Issue 10
    await svc.record(session, StockCommand(
        product_id=fx["product"].id, from_location_id=fx["raw"].id, to_location_id=task.section_id,
        quantity=Decimal("10"), reason=Reason.issue_to_work, task_id=task.id, created_by=fx["user"].id,
    ))
    # Return 3 to stock
    await svc.record(session, StockCommand(
        product_id=fx["product"].id, from_location_id=task.section_id, to_location_id=None,
        quantity=Decimal("3"), reason=Reason.return_to_stock, task_id=task.id, created_by=fx["user"].id,
    ))
    task.status = WorkTaskStatus.in_progress
    await session.commit()

    pm = StockProjectionManager()
    cache = await pm.get_task_cache(session, task.id)
    # first-stage: base_available = planned=20, received=0, returned=3, issued=10
    # available = 20 + 0 + 3 - 10 = 13
    assert cache["available_quantity"] == Decimal("13")
    assert cache["issued_quantity"] == Decimal("10")


async def test_get_tasks_cache_bulk(session: AsyncSession):
    """get_tasks_cache_bulk возвращает корректные кэши для нескольких задач."""
    fx1 = await _setup_one_task(session, sku="BULK1", qty=Decimal("10"))
    fx2 = await _setup_one_task(session, sku="BULK2", qty=Decimal("20"))

    svc = StockCommandService()
    for fx in [fx1, fx2]:
        await svc.record(session, StockCommand(
            product_id=fx["product"].id, from_location_id=None, to_location_id=fx["raw"].id,
            quantity=Decimal("100"), reason=Reason.manual_in, created_by=fx["user"].id,
        ))
        await svc.record(session, StockCommand(
            product_id=fx["product"].id, from_location_id=fx["raw"].id, to_location_id=fx["task"].section_id,
            quantity=fx["task"].planned_quantity, reason=Reason.issue_to_work,
            task_id=fx["task"].id, created_by=fx["user"].id,
        ))
        fx["task"].status = WorkTaskStatus.in_progress
    await session.commit()

    pm = StockProjectionManager()
    bulk = await pm.get_tasks_cache_bulk(session, [fx1["task"].id, fx2["task"].id])
    assert len(bulk) == 2
    assert bulk[fx1["task"].id]["issued_quantity"] == Decimal("10")
    assert bulk[fx2["task"].id]["issued_quantity"] == Decimal("20")


async def test_zero_cache_for_unknown_task(session: AsyncSession):
    """get_task_cache для несуществующей задачи возвращает нули."""
    pm = StockProjectionManager()
    cache = await pm.get_task_cache(session, 99999)
    assert all(v == Decimal("0") for v in cache.values())
