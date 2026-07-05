"""Production-flow tests: completed_stages in GET /api/stock/balance after transfers/complete."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models import Product, ProductType, Section, User, UserRole
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteOperation, RouteStage, SectionOperation
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.techcard import Techcard, TechcardLine
from app.models.work_task import WorkTask, WorkTaskStatus
from app.stock import QualityState, Reason, StockCommand, StockCommandService
from app.transfers.services import transfer_send
from tests.stock.helpers import record_transfer_receive
from tests.test_integrity_invariants import _release_via_take_to_work


async def _make_user(session: AsyncSession, email: str) -> User:
    user = User(
        username=email.split("@")[0],
        email=email,
        password_hash="x",
        full_name="Ops Tester",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.email)
    return {"Authorization": f"Bearer {token}"}


async def _make_two_section_fixture(
    session: AsyncSession,
    *,
    sku: str = "SECOPS",
    qty: Decimal = Decimal("10"),
) -> dict:
    """Two production sections with significant SectionOperation + two-step route."""
    user = await _make_user(session, f"{sku}@local")

    sec1 = Section(code=f"{sku}-S1", name="Пила", type="production", is_active=True, sort_order=10)
    sec2 = Section(code=f"{sku}-S2", name="Сверловка", type="production", is_active=True, sort_order=20)
    session.add_all([sec1, sec2])
    await session.flush()
    session.add_all([
        SectionOperation(
            section_id=sec1.id,
            operation_code="SAW_CUT",
            operation_name="Пила",
            is_significant=True,
            operation_type="production",
            sort_order=10,
        ),
        SectionOperation(
            section_id=sec2.id,
            operation_code="DRILL",
            operation_name="Сверловка",
            is_significant=True,
            operation_type="production",
            sort_order=20,
        ),
    ])

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
    for idx, (sec, code, op_name) in enumerate(
        [(sec1, "SAW_CUT", "Пила"), (sec2, "DRILL", "Сверловка")],
        start=1,
    ):
        stage = RouteStage(route_id=route.id, sequence=idx, section_id=sec.id, is_final=(idx == 2))
        session.add(stage)
        await session.flush()
        session.add(
            RouteOperation(
                route_stage_id=stage.id,
                sequence=1,
                operation_code=code,
                operation_name=op_name,
            )
        )

    tech = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(tech)
    await session.flush()
    session.add(
        TechcardLine(
            techcard_id=tech.id,
            component_product_id=product.id,
            quantity=Decimal("1"),
            unit="pcs",
        )
    )

    plan = ProductionPlan(
        plan_no=f"P-{sku}",
        name="p",
        status=ProductionPlanStatus.approved,
        period_start=datetime(2026, 5, 1),
        period_end=datetime(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()

    pos = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=qty,
        source_payload={},
        status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        period_start=plan.period_start,
        period_end=plan.period_end,
        has_pack_ops=False,
        route_id=route.id,
        route_assigned_at=None,
    )
    session.add(pos)
    await session.commit()

    return {
        "user": user,
        "product": product,
        "position": pos,
        "sections": [sec1, sec2],
    }


async def _prepare_source_task_ready(
    session: AsyncSession,
    client,
    setup: dict,
) -> dict:
    """Take-to-work, seed stock, issue to source section, complete source task."""
    await _release_via_take_to_work(client, setup["position"].id)
    tasks = (await session.execute(select(WorkTask).order_by(WorkTask.id))).scalars().all()
    assert len(tasks) >= 2
    src = tasks[0]

    stock = Section(code="SECOPS-STK", name="Stock", type="raw_stock", is_active=True, sort_order=0)
    session.add(stock)
    await session.flush()

    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=src.product_id,
            to_location_id=stock.id,
            quantity=src.planned_quantity,
            reason=Reason.MANUAL_IN,
            created_by=setup["user"].id,
        ),
    )
    await record_transfer_receive(
        session,
        product_id=src.product_id,
        from_location_id=stock.id,
        to_location_id=src.section_id,
        quantity=src.planned_quantity,
        task_id=src.id,
        created_by=setup["user"].id,
    )
    await svc.record(
        session,
        StockCommand(
            product_id=src.product_id,
            from_location_id=src.section_id,
            to_location_id=src.section_id,
            quantity=src.planned_quantity,
            reason=Reason.COMPLETE,
            task_id=src.id,
            source_ref="test_seed",
            created_by=setup["user"].id,
        ),
    )
    await session.commit()
    return {"from_task_id": src.id, "to_task_id": tasks[1].id, "user": setup["user"]}


@pytest.mark.asyncio
async def test_transfer_receive_populates_completed_stages_on_destination_balance(
    client,
    session: AsyncSession,
) -> None:
    """После transfer_send остаток на участке-получателе содержит пройденные операции."""
    setup = await _make_two_section_fixture(session, sku="XFEROPS", qty=Decimal("10"))
    ctx = await _prepare_source_task_ready(session, client, setup)
    headers = _auth_headers(ctx["user"])

    await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("5"),
        actor_id=ctx["user"].id,
        idempotency_key="xferops:send",
    )
    await session.commit()

    to_task = await session.get(WorkTask, ctx["to_task_id"])
    assert to_task is not None

    resp = await client.get(
        f"/api/stock/balance?product_id={to_task.product_id}&location_id={to_task.section_id}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    balances = resp.json()["balances"]
    assert len(balances) == 1
    stage_names = [stage["operation_name"] for stage in balances[0]["completed_stages"]]
    assert stage_names == ["Пила"]


@pytest.mark.asyncio
async def test_complete_task_populates_completed_stages_on_section_balance(
    client,
    session: AsyncSession,
) -> None:
    """После complete_task с остатком на участке баланс содержит пройденные операции."""
    setup = await _make_two_section_fixture(session, sku="CMPOPS", qty=Decimal("10"))
    await _release_via_take_to_work(client, setup["position"].id)
    task = (await session.execute(select(WorkTask).order_by(WorkTask.id))).scalars().first()
    assert task is not None

    stock = Section(code="CMPOPS-STK", name="Stock", type="raw_stock", is_active=True, sort_order=0)
    session.add(stock)
    await session.flush()

    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=task.product_id,
            to_location_id=stock.id,
            quantity=task.planned_quantity,
            reason=Reason.MANUAL_IN,
            created_by=setup["user"].id,
        ),
    )
    await record_transfer_receive(
        session,
        product_id=task.product_id,
        from_location_id=stock.id,
        to_location_id=task.section_id,
        quantity=task.planned_quantity,
        task_id=task.id,
        created_by=setup["user"].id,
    )
    task.status = WorkTaskStatus.in_progress
    await session.commit()

    from app.services.shopfloor.operations_tasks import complete_task

    await complete_task(
        session,
        task_id=task.id,
        good_quantity=Decimal("6"),
        defect_quantity=Decimal("0"),
        actor_id=setup["user"].id,
    )
    await session.commit()

    headers = _auth_headers(setup["user"])
    resp = await client.get(
        f"/api/stock/balance?product_id={task.product_id}&location_id={task.section_id}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    balances = resp.json()["balances"]
    assert len(balances) == 1
    stage_names = [stage["operation_name"] for stage in balances[0]["completed_stages"]]
    assert stage_names == ["Пила"]