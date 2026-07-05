"""Tests for stock→stock ready list and transfer (FG → SHIPMENT, same SPG)."""
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


async def _make_user(session, email: str = "fg@local") -> User:
    user = User(
        email=email,
        password_hash="x",
        full_name="FG Tester",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.email)
    return {"Authorization": f"Bearer {token}"}


async def _make_finished_stock_to_shipment_fixture(
    session,
    *,
    sku: str,
    qty: Decimal,
) -> dict:
    """FINISHED_STOCK → SHIPMENT в одной ГХП FG (как сид)."""
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

    fg_stock = Section(
        code=f"{sku}-FG",
        name="Склад ГП",
        type="finished_stock",
        is_active=True,
        sort_order=0,
    )
    shipment = Section(
        code=f"{sku}-SHIP",
        name="К отгрузке",
        type="finished_stock",
        is_active=True,
        sort_order=1,
    )
    session.add_all([fg_stock, shipment])
    await session.flush()

    spg = StorageProductionGroup(code=f"{sku}-FG-SPG", name="FG", is_active=True, sort_order=0)
    session.add(spg)
    await session.flush()
    session.add_all([
        SpgSection(spg_id=spg.id, section_id=fg_stock.id, sort_order=0),
        SpgSection(spg_id=spg.id, section_id=shipment.id, sort_order=1),
    ])

    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    route = ProductionRoute(name=f"Route {sku}", is_active=True)
    session.add(route)
    await session.flush()
    for idx, (sec, code) in enumerate([(fg_stock, "FG_WH"), (shipment, "SHIPMENT")], start=1):
        st = RouteStage(route_id=route.id, sequence=idx, section_id=sec.id, is_final=(idx == 2))
        session.add(st)
        await session.flush()
        session.add(
            RouteOperation(route_stage_id=st.id, sequence=1, operation_code=code, operation_name=code)
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
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
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
        "product": product,
        "plan": plan,
        "position": pos,
        "sections": [fg_stock, shipment],
        "spg": spg,
    }


async def _seed_stock_balance(
    session,
    *,
    user_id: int,
    location_id: int,
    product_id: int,
    qty: Decimal,
) -> None:
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
    resp = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [position_id]},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_finished_stock_to_shipment_appears_in_ready_and_transfers(client, session) -> None:
    """FG (одна SPG): FINISHED_STOCK → SHIPMENT в ready и POST /api/transfers."""
    user = await _make_user(session, "fg-xfer@test.local")
    headers = _auth_headers(user)
    plan_qty = Decimal("50")
    warehouse_qty = Decimal("200")
    fx = await _make_finished_stock_to_shipment_fixture(session, sku="FG2SHIP", qty=plan_qty)
    fg_sec = fx["sections"][0]
    ship_sec = fx["sections"][1]
    spg = fx["spg"]

    await _seed_stock_balance(
        session,
        user_id=user.id,
        location_id=fg_sec.id,
        product_id=fx["product"].id,
        qty=warehouse_qty,
    )

    await _release_via_take_to_work(client, fx["position"].id)

    tasks = (await session.execute(select(WorkTask))).scalars().all()
    assert len(tasks) == 0, "На stock-секциях WorkTask при release не создаётся"

    resp = await client.get(f"/api/transfers/ready?spg_id={spg.id}", headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["transferable_quantity"] == "50"
    assert items[0]["next_section_code"] == ship_sec.code
    task_id = items[0]["task_id"]

    xfer_qty = Decimal("30")
    send_resp = await client.post(
        "/api/transfers",
        json={
            "from_task_id": task_id,
            "quantity": str(xfer_qty),
            "idempotency_key": "fg2ship:send-30",
        },
        headers=headers,
    )
    assert send_resp.status_code == 200, send_resp.text
    assert send_resp.json()["status"] == "accepted"

    fg_bal = await _stock_balance_qty(
        session,
        location_id=fg_sec.id,
        product_id=fx["product"].id,
    )
    ship_bal = await _stock_balance_qty(
        session,
        location_id=ship_sec.id,
        product_id=fx["product"].id,
    )
    assert fg_bal == warehouse_qty - xfer_qty
    assert ship_bal == xfer_qty