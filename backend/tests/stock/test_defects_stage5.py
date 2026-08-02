"""Тесты Этапа 5: Defect → StockTransaction ledger.

Проверяют:
- complete_task связывает Defect со StockTransaction(SCRAP)
- defect_decide по всем веткам создаёт корректные StockTransaction
- идемпотентность defect_decide
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, ProductType, Section, User, UserRole
from app.models.defect import Defect, DefectDecision, DefectDecisionType, DefectStatus
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


async def _make_user(session: AsyncSession, username: str = "def5") -> User:
    user = User(
        username=username,
        email=f"{username}@local",
        full_name="Defect Stage5",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_product(session: AsyncSession, sku: str = "DEF5") -> Product:
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


async def _setup_minimal_route(session: AsyncSession, *, sku: str = "DEF5", qty: Decimal = Decimal("10")) -> dict:
    """Minimal topology: raw_stock → production section → scrap."""
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

    # Second stage for return_previous tests
    stage2 = RouteStage(route_id=route.id, sequence=2, section_id=scrap_loc.id, is_final=True)
    session.add(stage2)
    await session.flush()

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
        planned_quantity=qty, status=WorkTaskStatus.in_progress,
        due_date=plan.period_end,
    )
    session.add(task)
    await session.commit()

    return {
        "user": user, "product": product, "task": task,
        "raw": raw, "prod": prod, "scrap": scrap_loc, "stage2": stage2,
    }


# ─── tests ──────────────────────────────────────────────────────────────────


async def test_complete_task_scrap_links_defect_to_stock_tx(session: AsyncSession):
    """complete_task с браком → Defect.stock_transaction_id == tx_scrap.id, SCRAP c to_quality_state=scrap."""
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

    from app.services.shopfloor.operations_tasks import complete_task
    result = await complete_task(
        session,
        task_id=task.id,
        good_quantity=Decimal("7"),
        defect_quantity=Decimal("3"),
        actor_id=fx["user"].id,
        defect_reason="test_scrap",
    )
    await session.commit()

    assert result["defect_id"] is not None

    # Verify Defect.stock_transaction_id is set
    defect = await session.scalar(
        select(Defect).where(Defect.id == result["defect_id"])
    )
    assert defect is not None
    assert defect.stock_transaction_id is not None

    # Verify StockTransaction(SCRAP) exists with correct quality_state
    tx = await session.get(StockTransaction, defect.stock_transaction_id)
    assert tx is not None
    assert tx.reason == Reason.SCRAP
    assert tx.from_quality_state == QualityState.GOOD
    assert tx.to_quality_state == QualityState.SCRAP
    assert tx.quantity == Decimal("3")
    assert tx.task_id == task.id

    await assert_no_stock_ledger_invariants_violations(session, context="after-complete-scrap")


async def test_defect_decide_scrap_creates_stock_tx(session: AsyncSession):
    """defect_decide(scrap) → StockTransaction(SCRAP), defect.stock_transaction_id set, status=scrapped."""
    fx = await _setup_minimal_route(session)
    task = fx["task"]
    product = fx["product"]

    # Seed stock
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product.id,
        from_location_id=None,
        to_location_id=fx["raw"].id,
        quantity=Decimal("100"),
        reason=Reason.MANUAL_IN,
        created_by=fx["user"].id,
    ))
    await record_transfer_receive(
        session,
        product_id=product.id,
        from_location_id=fx["raw"].id,
        to_location_id=task.section_id,
        quantity=Decimal("10"),
        task_id=task.id,
        created_by=fx["user"].id,
    )
    await session.commit()

    # Create a defect via API
    from app.services.shopfloor.operations_defects import create_defect, defect_decide

    defect_resp = await create_defect(
        session,
        task_id=task.id,
        quantity=Decimal("5"),
        actor_id=fx["user"].id,
        reason="test",
        comment="defect for scrap test",
    )
    await session.commit()
    defect_id = defect_resp["defect_id"]

    # Decide scrap
    dec_resp = await defect_decide(
        session,
        defect_id=defect_id,
        decision_type=DefectDecisionType.scrap,
        quantity=Decimal("5"),
        actor_id=fx["user"].id,
        comment="scrap it",
        idempotency_key="scrap-test-1",
    )
    await session.commit()

    assert dec_resp["defect_status"] == DefectStatus.scrapped.value

    # Verify defect
    defect = await session.get(Defect, defect_id)
    assert defect is not None
    assert defect.stock_transaction_id is not None
    assert defect.status == DefectStatus.scrapped

    # Verify StockTransaction
    tx = await session.get(StockTransaction, defect.stock_transaction_id)
    assert tx is not None
    assert tx.reason == Reason.SCRAP
    assert tx.from_quality_state == QualityState.GOOD
    assert tx.to_quality_state == QualityState.SCRAP
    assert tx.quantity == Decimal("5")
    assert tx.task_id == task.id
    assert tx.product_id == product.id

    # Check StockBalance on scrap location
    scrap_bal = await _balance(session, product.id, fx["scrap"].id, QualityState.SCRAP)
    assert scrap_bal == Decimal("5")

    await assert_no_stock_ledger_invariants_violations(session, context="after-defect-scrap")


async def test_defect_decide_rework_creates_stock_tx(session: AsyncSession):
    """defect_decide(rework_current) → StockTransaction(REWORK, to_quality_state=rework), ReworkTask created."""
    fx = await _setup_minimal_route(session)
    task = fx["task"]

    # Seed stock
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

    from app.services.shopfloor.operations_defects import create_defect, defect_decide

    defect_resp = await create_defect(
        session,
        task_id=task.id,
        quantity=Decimal("3"),
        actor_id=fx["user"].id,
        reason="rework_test",
        comment="defect for rework test",
    )
    await session.commit()
    defect_id = defect_resp["defect_id"]

    # Decide rework_current — target a different section for rework
    dec_resp = await defect_decide(
        session,
        defect_id=defect_id,
        decision_type=DefectDecisionType.rework_current,
        quantity=Decimal("3"),
        actor_id=fx["user"].id,
        target_section_id=fx["raw"].id,
        idempotency_key="rework-test-1",
    )
    await session.commit()

    assert dec_resp["defect_status"] == DefectStatus.rework_task_created.value
    assert dec_resp["rework_task_id"] is not None

    # Verify defect
    defect = await session.get(Defect, defect_id)
    assert defect is not None
    assert defect.stock_transaction_id is not None
    assert defect.status == DefectStatus.rework_task_created

    # Verify StockTransaction(REWORK) — from production to rework location
    tx = await session.get(StockTransaction, defect.stock_transaction_id)
    assert tx is not None
    assert tx.reason == Reason.REWORK
    assert tx.from_location_id == task.section_id
    assert tx.to_location_id == fx["raw"].id
    assert tx.to_quality_state == QualityState.REWORK
    assert tx.quantity == Decimal("3")
    assert tx.task_id == task.id

    # Verify ReworkTask exists
    from app.models.rework_task import ReworkTask
    rwt = await session.get(ReworkTask, dec_resp["rework_task_id"])
    assert rwt is not None
    assert rwt.defect_id == defect_id

    await assert_no_stock_ledger_invariants_violations(session, context="after-defect-rework")


async def test_defect_decide_return_previous_creates_stock_tx(session: AsyncSession):
    """defect_decide(return_previous) → StockTransaction(RETURN_TO_PREVIOUS)."""
    fx = await _setup_minimal_route(session)
    task = fx["task"]

    # Seed stock
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

    from app.services.shopfloor.operations_defects import create_defect, defect_decide

    defect_resp = await create_defect(
        session,
        task_id=task.id,
        quantity=Decimal("4"),
        actor_id=fx["user"].id,
        reason="return_test",
    )
    await session.commit()
    defect_id = defect_resp["defect_id"]

    # Decide return_previous (target_section_id = task.section_id for now)
    dec_resp = await defect_decide(
        session,
        defect_id=defect_id,
        decision_type=DefectDecisionType.return_previous,
        quantity=Decimal("4"),
        actor_id=fx["user"].id,
        target_section_id=fx["raw"].id,
        idempotency_key="return-test-1",
    )
    await session.commit()

    assert dec_resp["defect_status"] == DefectStatus.rework_task_created.value

    # Verify defect
    defect = await session.get(Defect, defect_id)
    assert defect is not None
    assert defect.stock_transaction_id is not None

    # Verify StockTransaction(RETURN_TO_PREVIOUS)
    tx = await session.get(StockTransaction, defect.stock_transaction_id)
    assert tx is not None
    assert tx.reason == Reason.RETURN_TO_PREVIOUS
    assert tx.quantity == Decimal("4")
    assert tx.to_location_id == fx["raw"].id
    assert tx.task_id == task.id

    await assert_no_stock_ledger_invariants_violations(session, context="after-defect-return")


async def test_defect_decide_accept_deviation_creates_complete_tx(session: AsyncSession):
    """defect_decide(accept_with_deviation) → StockTransaction(COMPLETE)."""
    fx = await _setup_minimal_route(session)
    task = fx["task"]

    # Need issued quantity for complete to work
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

    from app.services.shopfloor.operations_defects import create_defect, defect_decide

    defect_resp = await create_defect(
        session,
        task_id=task.id,
        quantity=Decimal("3"),
        actor_id=fx["user"].id,
        reason="accept_test",
    )
    await session.commit()
    defect_id = defect_resp["defect_id"]

    # Decide accept_with_deviation
    dec_resp = await defect_decide(
        session,
        defect_id=defect_id,
        decision_type=DefectDecisionType.accept_with_deviation,
        quantity=Decimal("3"),
        actor_id=fx["user"].id,
        idempotency_key="accept-test-1",
    )
    await session.commit()

    assert dec_resp["defect_status"] == DefectStatus.accepted_with_deviation.value

    # Verify defect
    defect = await session.get(Defect, defect_id)
    assert defect is not None
    assert defect.stock_transaction_id is not None
    assert defect.status == DefectStatus.accepted_with_deviation

    # Verify StockTransaction(COMPLETE)
    tx = await session.get(StockTransaction, defect.stock_transaction_id)
    assert tx is not None
    assert tx.reason == Reason.COMPLETE
    assert tx.quantity == Decimal("3")
    assert tx.task_id == task.id
    assert tx.to_location_id == task.section_id

    await assert_no_stock_ledger_invariants_violations(session, context="after-defect-accept")


async def test_defect_decide_idempotent(session: AsyncSession):
    """Повторный defect_decide с тем же idempotency_key не создаёт вторую StockTransaction."""
    fx = await _setup_minimal_route(session)
    task = fx["task"]

    # Seed stock
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

    from app.services.shopfloor.operations_defects import create_defect, defect_decide

    defect_resp = await create_defect(
        session,
        task_id=task.id,
        quantity=Decimal("5"),
        actor_id=fx["user"].id,
        reason="idemp_test",
    )
    await session.commit()
    defect_id = defect_resp["defect_id"]

    # First call
    resp1 = await defect_decide(
        session,
        defect_id=defect_id,
        decision_type=DefectDecisionType.scrap,
        quantity=Decimal("5"),
        actor_id=fx["user"].id,
        idempotency_key="idemp-test-scrap-1",
    )
    await session.commit()
    assert resp1["defect_status"] == DefectStatus.scrapped.value

    # Get initial tx count for scrap
    scrap_tx_count_before = await session.scalar(
        select(func.count(StockTransaction.id))
        .where(
            StockTransaction.idempotency_key == "idemp-test-scrap-1",
            StockTransaction.reason == Reason.SCRAP,
        )
    )

    # Second call with same idempotency_key
    resp2 = await defect_decide(
        session,
        defect_id=defect_id,
        decision_type=DefectDecisionType.scrap,
        quantity=Decimal("5"),
        actor_id=fx["user"].id,
        idempotency_key="idemp-test-scrap-1",
    )
    await session.commit()
    assert resp2["idempotent_replay"] is True

    # Verify no extra StockTransaction was created
    scrap_tx_count_after = await session.scalar(
        select(func.count(StockTransaction.id))
        .where(
            StockTransaction.idempotency_key == "idemp-test-scrap-1",
            StockTransaction.reason == Reason.SCRAP,
        )
    )
    assert scrap_tx_count_before == scrap_tx_count_after == 1
