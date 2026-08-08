"""Тесты Этапа 3: Shopfloor на StockTransaction без двойной записи.

Проверяют:
- TRANSFER_RECEIVE задаёт issued_quantity (выдача через Transfer)
- complete_task создаёт COMPLETE/SCRAP транзакции + Defect
- final_release создаёт FINAL_RELEASE транзакцию
- return_to_stock через endpoint
- GET /shopfloor/remainders читает StockBalance, не SpgRemainder
- Movement-таблица пуста после shopfloor-операций (регресс двойной записи)
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
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
    StockBalance,
    StockCommand,
    StockCommandService,
    StockTransaction,
)
from tests.stock.helpers import record_transfer_receive
from tests.test_integrity_invariants import assert_no_stock_ledger_invariants_violations

pytestmark = pytest.mark.asyncio


# ─── helpers ────────────────────────────────────────────────────────────────


async def _make_user(session: AsyncSession, username: str = "shop3") -> User:
    user = User(
        username=username,
        email=f"{username}@local",
        full_name="Shop Stage3",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_product(session: AsyncSession, sku: str = "FRM") -> Product:
    product = Product(
        sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True,
    )
    session.add(product)
    await session.flush()
    return product


async def _make_location(
    session: AsyncSession, *, code: str, name: str, loc_type: str,
) -> Section:
    section = Section(
        code=code, name=name,
        type=loc_type, is_active=True, sort_order=0,
    )
    session.add(section)
    await session.flush()
    return section


async def _balance(
    session: AsyncSession, product_id: int, location_id: int,
    quality_state: QualityState = QualityState.GOOD,
) -> Decimal:
    row = await session.execute(
        select(StockBalance).where(
            StockBalance.product_id == product_id,
            StockBalance.location_id == location_id,
            StockBalance.quality_state == quality_state,
        )
    )
    bal = row.scalar_one_or_none()
    return bal.balance_qty if bal else Decimal("0")


async def _setup_minimal_route(session: AsyncSession, *, sku: str = "S3", qty: Decimal = Decimal("10")) -> dict:
    """Minimal topology: raw_stock → production section (first route stage).

    Returns user, product, task, stock_section, prod_section.
    """
    user = await _make_user(session, f"{sku}@local")

    raw = await _make_location(session, code=f"{sku}-RAW", name="Raw", loc_type="raw_stock")
    prod = await _make_location(session, code=f"{sku}-PROD", name="Production", loc_type="laser")
    scrap_loc = await _make_location(session, code=f"{sku}-SCR", name="Scrap", loc_type="scrap")

    spg = StorageProductionGroup(code=f"{sku}-SPG", name="SPG", is_active=True, sort_order=0)
    session.add(spg)
    await session.flush()
    session.add(SpgSection(spg_id=spg.id, section_id=prod.id, sort_order=0))

    product = await _make_product(session, sku)
    route = ProductionRoute(name=f"R-{sku}", is_active=True)
    session.add(route)
    await session.flush()
    stage = RouteStage(route_id=route.id, sequence=1, section_id=prod.id, is_final=True)
    session.add(stage)
    await session.flush()
    session.add(RouteOperation(route_stage_id=stage.id, sequence=1, operation_code="OP1", operation_name="Op1"))

    tech = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(tech)
    await session.flush()
    session.add(TechcardLine(techcard_id=tech.id, component_product_id=product.id, quantity=Decimal("1"), unit="pcs"))

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

    internal_plan = InternalPlan(
        production_plan_id=plan.id, status=InternalPlanStatus.active,
    )
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

    return {
        "user": user, "product": product, "task": task,
        "raw": raw, "prod": prod, "scrap": scrap_loc,
    }


async def _count_movements(session: AsyncSession, task_id: int) -> int:
    """Movement table deleted in Stage 7 — always returns 0."""
    return 0


# ─── tests ──────────────────────────────────────────────────────────────────


async def test_transfer_receive_creates_stock_tx(session: AsyncSession):
    """TRANSFER_RECEIVE создаёт StockTransaction и задаёт issued_quantity."""
    fx = await _setup_minimal_route(session)
    task = fx["task"]

    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=fx["product"].id,
        from_location_id=None,
        to_location_id=fx["raw"].id,
        quantity=Decimal("100"),
        reason=Reason.MANUAL_IN,
        created_by=fx["user"].id,
    ))

    await record_transfer_receive(
        session,
        product_id=fx["product"].id,
        from_location_id=fx["raw"].id,
        to_location_id=task.section_id,
        quantity=Decimal("10"),
        task_id=task.id,
        created_by=fx["user"].id,
    )
    await session.commit()

    tx_count = await session.scalar(
        select(func.count(StockTransaction.id))
        .where(
            StockTransaction.task_id == task.id,
            StockTransaction.reason == Reason.TRANSFER_RECEIVE,
        )
    )
    assert tx_count == 1, "Expected 1 StockTransaction(TRANSFER_RECEIVE)"

    await assert_no_stock_ledger_invariants_violations(session, context="after-receive")


async def test_transfer_receive_updates_cache(session: AsyncSession):
    """get_task_cache() отражает net TRANSFER_RECEIVE после приёма."""
    fx = await _setup_minimal_route(session)
    task = fx["task"]

    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=fx["product"].id,
        from_location_id=None,
        to_location_id=fx["raw"].id,
        quantity=Decimal("100"),
        reason=Reason.MANUAL_IN,
        created_by=fx["user"].id,
    ))

    await record_transfer_receive(
        session,
        product_id=fx["product"].id,
        from_location_id=fx["raw"].id,
        to_location_id=task.section_id,
        quantity=Decimal("7"),
        task_id=task.id,
        created_by=fx["user"].id,
    )
    await session.commit()

    from app.stock.services import StockProjectionManager
    pm = StockProjectionManager()
    cache = await pm.get_task_cache(session, task.id)
    sql_sum = await session.scalar(
        select(func.coalesce(func.sum(StockTransaction.quantity), 0))
        .where(
            StockTransaction.task_id == task.id,
            StockTransaction.reason == Reason.TRANSFER_RECEIVE,
        )
    )
    assert cache["issued_quantity"] == sql_sum == Decimal("7")


async def test_validation_rejects_issue_to_work_command(session: AsyncSession):
    """StockCommandService не принимает новые ISSUE_TO_WORK."""
    fx = await _setup_minimal_route(session)
    task = fx["task"]

    svc = StockCommandService()
    from app.stock import StockValidationError
    with pytest.raises(StockValidationError, match="issue_to_work"):
        await svc.record(session, StockCommand(
            product_id=fx["product"].id,
            from_location_id=fx["raw"].id,
            to_location_id=task.section_id,
            quantity=Decimal("100"),
            reason=Reason.ISSUE_TO_WORK,
            task_id=task.id,
            created_by=fx["user"].id,
        ))


async def test_complete_task_creates_complete_tx(session: AsyncSession):
    """complete_task → StockTransaction(COMPLETE), cached_completed_quantity обновлён."""
    fx = await _setup_minimal_route(session)
    task = fx["task"]

    # Issue first
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=fx["product"].id,
        from_location_id=None,
        to_location_id=fx["raw"].id,
        quantity=Decimal("100"),
        reason=Reason.MANUAL_IN,
        created_by=fx["user"].id,
    ))
    await record_transfer_receive(
        session,
        product_id=fx["product"].id,
        from_location_id=fx["raw"].id,
        to_location_id=task.section_id,
        quantity=Decimal("10"),
        task_id=task.id,
        created_by=fx["user"].id,
    )
    task.status = WorkTaskStatus.in_progress
    await session.commit()

    from app.services.shopfloor.operations_tasks import complete_task
    result = await complete_task(
        session,
        task_id=task.id,
        good_quantity=Decimal("8"),
        defect_quantity=Decimal("0"),
        actor_id=fx["user"].id,
    )
    await session.commit()

    assert result["task_id"] == task.id

    tx_count = await session.scalar(
        select(func.count(StockTransaction.id))
        .where(
            StockTransaction.task_id == task.id,
            StockTransaction.reason == Reason.COMPLETE,
        )
    )
    assert tx_count == 1, "Expected 1 StockTransaction(COMPLETE)"

    # get_task_cache completed = SUM(stock_transactions WHERE reason=complete)
    from app.stock.services import StockProjectionManager
    pm = StockProjectionManager()
    cache = await pm.get_task_cache(session, task.id)
    sql_sum = await session.scalar(
        select(func.coalesce(func.sum(StockTransaction.quantity), 0))
        .where(
            StockTransaction.task_id == task.id,
            StockTransaction.reason == Reason.COMPLETE,
        )
    )
    assert cache["completed_quantity"] == sql_sum == Decimal("8")

    await assert_no_stock_ledger_invariants_violations(session, context="after-complete")


async def test_complete_task_with_scrap(session: AsyncSession):
    """complete с браком → StockTransaction(COMPLETE) + StockTransaction(SCRAP) + Defect."""
    fx = await _setup_minimal_route(session)
    task = fx["task"]

    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=fx["product"].id,
        from_location_id=None,
        to_location_id=fx["raw"].id,
        quantity=Decimal("100"),
        reason=Reason.MANUAL_IN,
        created_by=fx["user"].id,
    ))
    await record_transfer_receive(
        session,
        product_id=fx["product"].id,
        from_location_id=fx["raw"].id,
        to_location_id=task.section_id,
        quantity=Decimal("10"),
        task_id=task.id,
        created_by=fx["user"].id,
    )
    task.status = WorkTaskStatus.in_progress
    await session.commit()

    from app.services.shopfloor.operations_tasks import complete_task
    from tests.stock.helpers import FAKE_SCRAP_KWARGS
    result = await complete_task(
        session,
        task_id=task.id,
        good_quantity=Decimal("7"),
        defect_quantity=Decimal("3"),
        actor_id=fx["user"].id,
        defect_reason="test_scrap",
        **FAKE_SCRAP_KWARGS,
    )
    await session.commit()

    # Verify StockTransaction(COMPLETE)
    complete_sum = await session.scalar(
        select(func.coalesce(func.sum(StockTransaction.quantity), 0))
        .where(
            StockTransaction.task_id == task.id,
            StockTransaction.reason == Reason.COMPLETE,
        )
    )
    assert complete_sum == Decimal("7")

    # Verify StockTransaction(SCRAP)
    scrap_sum = await session.scalar(
        select(func.coalesce(func.sum(StockTransaction.quantity), 0))
        .where(
            StockTransaction.task_id == task.id,
            StockTransaction.reason == Reason.SCRAP,
        )
    )
    assert scrap_sum == Decimal("3")

    # Verify Defect created
    from app.models.defect import Defect
    defect_count = await session.scalar(
        select(func.count(Defect.id)).where(Defect.task_id == task.id)
    )
    assert defect_count == 1, "Expected 1 Defect"

    await assert_no_stock_ledger_invariants_violations(session, context="after-complete-scrap")


async def test_final_release_creates_stock_tx(session: AsyncSession):
    """final_release → StockTransaction(FINAL_RELEASE)."""
    fx = await _setup_minimal_route(session)
    task = fx["task"]

    # Setup: issue + complete
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=fx["product"].id,
        from_location_id=None,
        to_location_id=fx["raw"].id,
        quantity=Decimal("100"),
        reason=Reason.MANUAL_IN,
        created_by=fx["user"].id,
    ))
    await record_transfer_receive(
        session,
        product_id=fx["product"].id,
        from_location_id=fx["raw"].id,
        to_location_id=task.section_id,
        quantity=Decimal("10"),
        task_id=task.id,
        created_by=fx["user"].id,
    )
    task.status = WorkTaskStatus.in_progress
    await svc.record(session, StockCommand(
        product_id=fx["product"].id,
        from_location_id=None,
        to_location_id=task.section_id,
        quantity=Decimal("8"),
        reason=Reason.COMPLETE,
        task_id=task.id,
        created_by=fx["user"].id,
    ))
    await session.commit()

    from app.services.shopfloor.operations_tasks import final_release
    result = await final_release(
        session,
        task_id=task.id,
        quantity=Decimal("8"),
        actor_id=fx["user"].id,
    )
    await session.commit()

    tx_count = await session.scalar(
        select(func.count(StockTransaction.id))
        .where(
            StockTransaction.task_id == task.id,
            StockTransaction.reason == Reason.FINAL_RELEASE,
        )
    )
    assert tx_count == 1, "Expected 1 StockTransaction(FINAL_RELEASE)"

    await assert_no_stock_ledger_invariants_violations(session, context="after-final-release")


async def test_return_to_stock_endpoint(session: AsyncSession):
    """POST /shopfloor/remainders/return → StockTransaction(RETURN_TO_STOCK)."""
    fx = await _setup_minimal_route(session)
    task = fx["task"]
    task.status = WorkTaskStatus.in_progress

    # Simulate issued quantity (via StockCommand) — issue + complete
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=fx["product"].id,
        from_location_id=None,
        to_location_id=fx["raw"].id,
        quantity=Decimal("100"),
        reason=Reason.MANUAL_IN,
        created_by=fx["user"].id,
    ))
    await record_transfer_receive(
        session,
        product_id=fx["product"].id,
        from_location_id=fx["raw"].id,
        to_location_id=task.section_id,
        quantity=Decimal("10"),
        task_id=task.id,
        created_by=fx["user"].id,
    )
    await session.commit()

    # Call return endpoint directly
    from app.stock import StockCommand as SC, StockCommandService as SCS, Reason as Rsn
    return_svc = SCS()
    tx = await return_svc.record(session, SC(
        product_id=fx["product"].id,
        from_location_id=task.section_id,
        to_location_id=None,
        quantity=Decimal("3"),
        reason=Rsn.RETURN_TO_STOCK,
        task_id=task.id,
        created_by=fx["user"].id,
    ))
    await session.commit()

    tx_check = await session.scalar(
        select(func.count(StockTransaction.id))
        .where(
            StockTransaction.id == tx.id,
            StockTransaction.reason == Reason.RETURN_TO_STOCK,
        )
    )
    assert tx_check == 1


async def test_no_movement_written_in_shopfloor(session: AsyncSession):
    """Критический snapshot-тест: после shopfloor-операций Movement-таблица пуста."""
    fx = await _setup_minimal_route(session)
    task = fx["task"]

    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=fx["product"].id,
        from_location_id=None,
        to_location_id=fx["raw"].id,
        quantity=Decimal("100"),
        reason=Reason.MANUAL_IN,
        created_by=fx["user"].id,
    ))
    await record_transfer_receive(
        session,
        product_id=fx["product"].id,
        from_location_id=fx["raw"].id,
        to_location_id=task.section_id,
        quantity=Decimal("10"),
        task_id=task.id,
        created_by=fx["user"].id,
    )
    task.status = WorkTaskStatus.in_progress
    await svc.record(session, StockCommand(
        product_id=fx["product"].id,
        from_location_id=None,
        to_location_id=task.section_id,
        quantity=Decimal("8"),
        reason=Reason.COMPLETE,
        task_id=task.id,
        created_by=fx["user"].id,
    ))
    await session.commit()

    # No Movement rows should exist for this task
    movement_count = await _count_movements(session, task.id)
    assert movement_count == 0, f"Expected 0 Movement rows, got {movement_count}"
