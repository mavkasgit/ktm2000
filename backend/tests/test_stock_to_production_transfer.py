"""Tests for stock-to-production auto-transfer and no-WorkTask-on-stock semantics.

When a route contains storage sections (raw_stock / wip_stock), they are
storage slots inside a GHP — not actual work steps.  ``take-to-work`` must
NOT create a WorkTask on them; instead, raw material flows from storage
to the production step via StockBalance + Transfer.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models.product import Product, ProductType
from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.user import User, UserRole
from app.models.work_task import WorkTask
from app.stock.models import QualityState, Reason, StockBalance
from app.stock.services import StockCommand, StockCommandService


# ─── helpers ─────────────────────────────────────────────────────────────────


async def _make_user(session, email: str = "raw@local") -> User:
    user = User(
        email=email,
        password_hash="x",
        full_name="Raw Tester",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.email)
    return {"Authorization": f"Bearer {token}"}


async def _make_raw_stock_to_production_fixture(
    session,
    *,
    sku: str,
    qty: Decimal,
    same_ghp: bool = False,
) -> dict:
    """raw_stock + production в разных ГХП (или одной, если same_ghp=True)."""
    from datetime import date
    from app.models.route import ProductionRoute, RouteStage, RouteOperation
    from app.models.techcard import Techcard, TechcardLine
    from app.models.production_plan import (
        PlanPosition,
        PlanPositionStatus,
        PlanPositionValidationStatus,
        PlanSourceType,
        ProductionPlan,
        ProductionPlanStatus,
    )

    raw_sec = Section(code=f"{sku}-RAW", name="RAW", type="raw_stock", is_active=True, sort_order=0)
    prod_sec = Section(code=f"{sku}-PROD", name="PROD", type="production", is_active=True, sort_order=1)
    session.add_all([raw_sec, prod_sec])
    await session.flush()

    if same_ghp:
        spg = StorageProductionGroup(code=f"{sku}-SPG", name="One", is_active=True, sort_order=0)
        session.add(spg)
        await session.flush()
        session.add_all([
            SpgSection(spg_id=spg.id, section_id=raw_sec.id, sort_order=0),
            SpgSection(spg_id=spg.id, section_id=prod_sec.id, sort_order=1),
        ])
        spgs = [spg]
    else:
        spg_a = StorageProductionGroup(code=f"{sku}-A", name="A", is_active=True, sort_order=0)
        spg_b = StorageProductionGroup(code=f"{sku}-B", name="B", is_active=True, sort_order=1)
        session.add_all([spg_a, spg_b])
        await session.flush()
        session.add_all([
            SpgSection(spg_id=spg_a.id, section_id=raw_sec.id, sort_order=0),
            SpgSection(spg_id=spg_b.id, section_id=prod_sec.id, sort_order=0),
        ])
        spgs = [spg_a, spg_b]

    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    route = ProductionRoute(name=f"Route {sku}", is_active=True)
    session.add(route)
    await session.flush()
    for idx, (sec, code) in enumerate([(raw_sec, "ISSUE_RAW"), (prod_sec, "PROD")], start=1):
        st = RouteStage(route_id=route.id, sequence=idx, section_id=sec.id, is_final=(idx == 2))
        session.add(st)
        await session.flush()
        session.add(RouteOperation(route_stage_id=st.id, sequence=1, operation_code=code, operation_name=code))

    tech = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(tech)
    await session.flush()
    session.add(TechcardLine(techcard_id=tech.id, component_product_id=product.id, quantity=Decimal("1"), unit="pcs"))

    plan = ProductionPlan(
        plan_no=f"P-{sku}", name="p", status=ProductionPlanStatus.approved,
        period_start=date(2026, 5, 1), period_end=date(2026, 5, 31),
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
    await session.commit()
    return {
        "product": product,
        "plan": plan,
        "position": pos,
        "sections": [raw_sec, prod_sec],
        "spgs": spgs,
        "same_ghp": same_ghp,
    }


async def _seed_stock_balance(session, *, user_id: int, location_id: int, product_id: int, qty: Decimal) -> None:
    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=product_id,
            to_location_id=location_id,
            quantity=qty,
            reason=Reason.MANUAL_IN,
            created_by=user_id,
        ),
    )
    await session.commit()


async def _stock_balance_qty(session, *, location_id: int, product_id: int) -> Decimal:
    bal = await session.scalar(
        select(StockBalance.balance_qty).where(
            StockBalance.location_id == location_id,
            StockBalance.product_id == product_id,
            StockBalance.quality_state == QualityState.GOOD,
        )
    )
    return bal or Decimal("0")


async def _release_via_take_to_work(client, position_id: int) -> None:
    resp = await client.post("/api/production-planning/rows/take-to-work", json={"position_ids": [position_id]})
    assert resp.status_code == 200, resp.text


# ─── tests ──────────────────────────────────────────────────────────────────


async def test_take_to_work_accepts_partial_release_quantity(client, session) -> None:
    """Запуск в работу с release_quantity создаёт задачу на указанное количество."""
    from app.models.release_batch import ReleaseBatchPosition

    fx = await _make_raw_stock_to_production_fixture(session, sku="PARTREL", qty=Decimal("216"))
    resp = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [fx["position"].id], "release_quantity": "100"},
    )
    assert resp.status_code == 200, resp.text

    batch_pos = (await session.execute(select(ReleaseBatchPosition))).scalar_one()
    assert batch_pos.release_quantity == Decimal("100")

    tasks = (await session.execute(select(WorkTask))).scalars().all()
    assert len(tasks) == 1
    assert tasks[0].planned_quantity == Decimal("100")


async def test_take_to_work_does_not_create_task_on_raw_stock(client, session) -> None:
    """WorkTask создаётся только на production-секции, даже если
    в маршруте есть raw_stock (склад)."""
    user = await _make_user(session)
    fx = await _make_raw_stock_to_production_fixture(session, sku="RAWTST", qty=Decimal("5"))
    await _release_via_take_to_work(client, fx["position"].id)

    tasks = (await session.execute(select(WorkTask))).scalars().all()
    assert len(tasks) == 1, f"Ожидался 1 WorkTask (только на production), получили {len(tasks)}"
    assert tasks[0].section_id == fx["sections"][1].id


@pytest.mark.asyncio
async def test_manual_stock_transfer_one_per_task_and_plan_cap(client, session) -> None:
    """Со склада: transferable = min(план, остаток); одна передача на задание."""
    user = await _make_user(session, "manual-xfer@test.local")
    headers = _auth_headers(user)
    plan_qty = Decimal("100")
    warehouse_qty = Decimal("4000")
    fx = await _make_raw_stock_to_production_fixture(session, sku="MANXFER", qty=plan_qty)
    raw_sec = fx["sections"][0]

    await _seed_stock_balance(
        session,
        user_id=user.id,
        location_id=raw_sec.id,
        product_id=fx["product"].id,
        qty=warehouse_qty,
    )

    await _release_via_take_to_work(client, fx["position"].id)

    resp = await client.get(f"/api/transfers/ready?section_id={raw_sec.id}", headers=headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["transferable_quantity"] == "100"
    assert items[0]["planned_quantity"] == "100"
    task_id = items[0]["task_id"]

    send_resp = await client.post(
        "/api/transfers",
        json={
            "from_task_id": task_id,
            "quantity": "40",
            "idempotency_key": "manual-xfer:send-40",
        },
        headers=headers,
    )
    assert send_resp.status_code == 200
    assert send_resp.json()["status"] == "accepted"

    resp = await client.get(f"/api/transfers/ready?section_id={raw_sec.id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["items"] == []

    dup_resp = await client.post(
        "/api/transfers",
        json={
            "from_task_id": task_id,
            "quantity": "10",
            "idempotency_key": "manual-xfer:send-dup",
        },
        headers=headers,
    )
    assert dup_resp.status_code == 400
    assert "активная передача" in dup_resp.json()["detail"].lower()

    bal = await _stock_balance_qty(
        session,
        location_id=raw_sec.id,
        product_id=fx["product"].id,
    )
    # TRANSFER_SEND списывает со склада; TRANSFER_RECEIVE не дублирует движение.
    assert bal == warehouse_qty - Decimal("40")


@pytest.mark.asyncio
async def test_full_stock_transfer_does_not_reappear_in_ready_list(client, session) -> None:
    """После полной передачи со склада задание не должно снова появляться в ready.

    Регрессия: completed fake_task + новый WorkTask на ту же section_plan_line
    обнулял already_transferred и позволял повторно передать весь план.
    """
    user = await _make_user(session, "full-xfer@test.local")
    headers = _auth_headers(user)
    plan_qty = Decimal("100")
    warehouse_qty = Decimal("4000")
    fx = await _make_raw_stock_to_production_fixture(session, sku="FULLXFER", qty=plan_qty)
    raw_sec = fx["sections"][0]

    await _seed_stock_balance(
        session,
        user_id=user.id,
        location_id=raw_sec.id,
        product_id=fx["product"].id,
        qty=warehouse_qty,
    )
    await _release_via_take_to_work(client, fx["position"].id)

    ready_before = await client.get(
        f"/api/transfers/ready?section_id={raw_sec.id}",
        headers=headers,
    )
    assert ready_before.status_code == 200
    items_before = ready_before.json()["items"]
    assert len(items_before) == 1
    task_id = items_before[0]["task_id"]

    send_resp = await client.post(
        "/api/transfers",
        json={
            "from_task_id": task_id,
            "quantity": str(plan_qty),
            "idempotency_key": "full-xfer:send-100",
        },
        headers=headers,
    )
    assert send_resp.status_code == 200
    assert send_resp.json()["status"] == "accepted"

    ready_after = await client.get(
        f"/api/transfers/ready?section_id={raw_sec.id}",
        headers=headers,
    )
    assert ready_after.status_code == 200
    assert ready_after.json()["items"] == []

    dup_resp = await client.post(
        "/api/transfers",
        json={
            "from_task_id": task_id,
            "quantity": "10",
            "idempotency_key": "full-xfer:send-dup",
        },
        headers=headers,
    )
    assert dup_resp.status_code == 400
    assert "активная передача" in dup_resp.json()["detail"].lower()

    tasks = (
        await session.execute(
            select(WorkTask).where(WorkTask.section_id == raw_sec.id)
        )
    ).scalars().all()
    assert len(tasks) == 1, "Не должно создаваться второго fake_task на складской линии"