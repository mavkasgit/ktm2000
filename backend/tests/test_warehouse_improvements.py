"""Tests for warehouse inventory improvements: zero remainders, consume limit, and final release FG.
"""

from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models.internal_plan import SectionPlanLine
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteStage, RouteOperation
from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.techcard import Techcard, TechcardLine
from app.models.user import User, UserRole
from app.models.spg_remainder import SpgRemainder
from app.models.movement import Movement, MovementType
from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.shopfloor.operations_tasks import consume_remainder, final_release
from app.services.shopfloor.cache import _refresh_task_cache


# ─── Helpers from test_transfers_module ──────────────────────────────────────


async def _make_user(session, email: str = "xfer@test.local") -> User:
    user = User(
        email=email,
        password_hash="x",
        full_name="Transfer Tester",
        role=UserRole.admin,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.email)
    return {"Authorization": f"Bearer {token}"}


async def _make_six_section_fixture(
    session,
    *,
    sku: str,
    planned_qty: Decimal,
    with_spg: bool = False,
) -> dict:
    section_specs: list[tuple[str, str]] = [
        ("ISSUE", "raw_stock"),
        ("DRILL", "production"),
        ("SHOT", "production"),
        ("ANOD", "production"),
        ("WIP", "wip_stock"),
        ("FINAL", "finished_stock"),
    ]
    sections: list[Section] = []
    for code, kind in section_specs:
        sec = Section(
            code=f"{sku}-{code}",
            name=code,
            kind=kind,
            sort_order=len(sections) * 10,
            is_active=True,
        )
        session.add(sec)
        sections.append(sec)
    await session.flush()

    spg = None
    if with_spg:
        spg = StorageProductionGroup(
            code=f"{sku}-SPG", name="Test SPG", is_active=True, sort_order=0
        )
        session.add(spg)
        await session.flush()
        for s in sections:
            session.add(SpgSection(spg_id=spg.id, section_id=s.id, sort_order=0))

    product = Product(
        sku=sku,
        name=f"Product {sku}",
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
    )
    session.add(product)
    await session.flush()

    route = ProductionRoute(name=f"Route {sku}", is_active=True)
    session.add(route)
    await session.flush()
    ops = ["ISSUE_RAW", "DRILL", "SHOT", "ANOD", "MOVE_TO_WIP", "FINAL"]
    for idx, (section, op_code) in enumerate(zip(sections, ops, strict=True), start=1):
        stage = RouteStage(
            route_id=route.id,
            sequence=idx,
            section_id=section.id,
            is_final=(idx == len(sections)),
        )
        session.add(stage)
        await session.flush()
        session.add(
            RouteOperation(
                route_stage_id=stage.id,
                sequence=1,
                operation_code=op_code,
                operation_name=op_code,
            )
        )

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(
        TechcardLine(
            techcard_id=techcard.id,
            component_product_id=product.id,
            quantity=Decimal("1"),
            unit="pcs",
        )
    )

    plan = ProductionPlan(
        plan_no=f"PLAN-{sku}",
        name=f"Plan {sku}",
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
        quantity=planned_qty,
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
    return {"product": product, "plan": plan, "position": pos, "sections": sections, "spg": spg}


async def _release_via_take_to_work(client, position_id: int) -> None:
    resp = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [position_id]},
    )
    assert resp.status_code == 200, resp.text
    res = resp.json()["results"][0]
    assert res["status"] == "success", res
    assert res["tasks_created"] == 6


async def _tasks_by_sequence(session, position_id: int) -> list[WorkTask]:
    return (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == position_id)
            .order_by(SectionPlanLine.sequence, WorkTask.id)
        )
    ).scalars().all()


# ─── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_manual_operation_zeros_are_consumed(client, session):
    """Test that remainders becoming exactly 0 are set to consumed_at != None."""
    user = await _make_user(session, "spg-zeros@test.local")
    ctx = await _make_six_section_fixture(session, sku="FG-ZEROS", planned_qty=Decimal("100"), with_spg=True)
    spg = ctx["spg"]
    sec_id = ctx["sections"][0].id

    # CASE A: IN (10) -> OUT (10)
    in_resp = await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": ctx["product"].id, "section_id": sec_id, "operation_type": "in", "quantity": 10},
    )
    assert in_resp.status_code == 200
    rid_a = in_resp.json()["remainder_id"]

    out_resp = await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": ctx["product"].id, "section_id": sec_id, "operation_type": "out", "quantity": 10},
    )
    assert out_resp.status_code == 200
    assert out_resp.json()["remainder_id"] == rid_a

    # Check remainder is consumed
    rem_a = (await session.execute(
        select(SpgRemainder).where(SpgRemainder.id == rid_a)
    )).scalar_one()
    assert rem_a.remainder_quantity == Decimal("0")
    assert rem_a.consumed_at is not None

    # CASE B: OUT (5) -> IN (5) (Resolving negative remainder)
    out_resp_b = await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": ctx["product"].id, "section_id": sec_id, "operation_type": "out", "quantity": 5},
    )
    assert out_resp_b.status_code == 200
    rid_b = out_resp_b.json()["remainder_id"]

    in_resp_b = await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": ctx["product"].id, "section_id": sec_id, "operation_type": "in", "quantity": 5},
    )
    assert in_resp_b.status_code == 200
    assert in_resp_b.json()["remainder_id"] == rid_b

    # Check remainder is consumed
    rem_b = (await session.execute(
        select(SpgRemainder).where(SpgRemainder.id == rid_b)
    )).scalar_one()
    assert rem_b.remainder_quantity == Decimal("0")
    assert rem_b.consumed_at is not None


@pytest.mark.asyncio
async def test_consume_remainder_limits(client, session) -> None:
    user = await _make_user(session, "con-lim@test.local")
    ctx = await _make_six_section_fixture(session, sku="FG-CON-LIM", planned_qty=Decimal("100"), with_spg=True)
    await _release_via_take_to_work(client, ctx["position"].id)
    tasks = await _tasks_by_sequence(session, ctx["position"].id)
    first_task = tasks[0]

    # Create a remainder of 5 units on the first task's SPG
    rem = SpgRemainder(
        product_id=ctx["product"].id,
        spg_id=ctx["spg"].id,
        remainder_quantity=Decimal("5"),
        original_issued=Decimal("5"),
        source="manual",
    )
    session.add(rem)
    await session.flush()

    # Consuming 6 from remainder of 5 should succeed and go negative
    await consume_remainder(
        session,
        remainder_id=rem.id,
        task_id=first_task.id,
        quantity=Decimal("6"),
        actor_id=user.id,
    )
    assert rem.remainder_quantity == Decimal("-1")


@pytest.mark.asyncio
async def test_final_release_creates_fg_remainder(client, session) -> None:
    user = await _make_user(session, "final-rel@test.local")
    headers = _auth_headers(user)
    ctx = await _make_six_section_fixture(session, sku="FG-FINAL-REL", planned_qty=Decimal("100"), with_spg=True)
    await _release_via_take_to_work(client, ctx["position"].id)
    tasks = await _tasks_by_sequence(session, ctx["position"].id)
    
    # Final step task (last task in sequence, index 5)
    final_task = tasks[5]
    
    # Force status to ready so we can issue to work (since it starts as waiting_previous)
    final_task.status = WorkTaskStatus.ready
    await session.flush()
    
    # We must mark final_task as completed so it can be final-released
    # First issue to work, then complete
    resp_issue = await client.post(
        f"/api/shopfloor/tasks/{final_task.id}/issue",
        json={"quantity": "100", "idempotency_key": "final:issue"},
        headers=headers,
    )
    assert resp_issue.status_code == 200, resp_issue.text
 
    resp_complete = await client.post(
        f"/api/shopfloor/tasks/{final_task.id}/complete",
        json={"good_quantity": "100", "defect_quantity": "0", "idempotency_key": "final:complete"},
        headers=headers,
    )
    assert resp_complete.status_code == 200, resp_complete.text
    
    # Expire and refresh task to get new completed quantity cache
    session.expire(final_task)
    await session.refresh(final_task)
    
    # Now run final_release
    res = await final_release(
        session,
        task_id=final_task.id,
        quantity=Decimal("40"),
        actor_id=user.id,
    )
    assert res["remainder_id"] is not None

    # Check remainder was created
    remainder = (await session.execute(
        select(SpgRemainder).where(SpgRemainder.id == res["remainder_id"])
    )).scalar_one()
    assert remainder.remainder_quantity == Decimal("40")
    assert remainder.source == "final_release"
    assert remainder.completed_stages_json[-1]["operation_code"] == "FINAL"

    # Check movement
    movement = (await session.execute(
        select(Movement).where(Movement.id == res["movement_id"])
    )).scalar_one()
    assert movement.movement_type == MovementType.final_release
    assert movement.quantity == Decimal("40")


@pytest.mark.asyncio
async def test_refresh_task_cache_with_remainders(client, session) -> None:
    user = await _make_user(session, "cache-rem@test.local")
    ctx = await _make_six_section_fixture(session, sku="FG-CACHE-REM", planned_qty=Decimal("100"), with_spg=True)
    await _release_via_take_to_work(client, ctx["position"].id)
    tasks = await _tasks_by_sequence(session, ctx["position"].id)
    
    # Task on stage sequence=2 (index 1)
    second_task = tasks[1]

    # Create a remainder of 15 units on second task's SPG
    rem = SpgRemainder(
        product_id=ctx["product"].id,
        spg_id=ctx["spg"].id,
        remainder_quantity=Decimal("15"),
        original_issued=Decimal("15"),
        source="manual",
    )
    session.add(rem)
    await session.flush()

    # 1. Simulate incoming transfer of 5 units
    m_receive = Movement(
        product_id=ctx["product"].id,
        task_id=second_task.id,
        section_plan_line_id=second_task.section_plan_line_id,
        from_section_id=second_task.section_id,
        to_section_id=second_task.section_id,
        movement_type=MovementType.transfer_receive,
        quantity=Decimal("5"),
        created_by=user.id,
    )
    session.add(m_receive)
    await session.flush()

    # Set task status to ready (mimics API transfer_receive status change)
    second_task.status = WorkTaskStatus.ready
    await session.flush()

    # 2. Consume 10 units from remainder
    await consume_remainder(
        session,
        remainder_id=rem.id,
        task_id=second_task.id,
        quantity=Decimal("10"),
        actor_id=user.id,
    )

    # Verify task cached availability
    await _refresh_task_cache(session, second_task.id)
    assert second_task.cached_issued_quantity == Decimal("10")
    # available = base_available (0) + received (5) + consumed (10) - issued (10) = 5
    assert second_task.cached_available_quantity == Decimal("5")


# ─── MRP / Smart Planning Tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mrp_compatible_remainder_reduces_planned_quantity(client, session):
    """MRP: compatible SPG remainder reduces planned_quantity for early stages.

    Setup:
    - Route has 6 stages (seq 1..6).
    - There's a compatible remainder that has completed stages 1..2
      (section_ids match the route prefix).
    - Release quantity = 100, remainder_quantity = 30.

    Expected:
    - Stages 1 and 2 get planned_quantity = max(0, 100 - 30) = 70... wait,
      actually stage 3+ gets planned_quantity = 100 - 0 = 100 (remainder covers
      seq 1 and 2, so for stages 3+ covered_qty = 0).
      For stage 1 and 2: covered_qty = 30 (max_seq=2 >= 1,2), so planned_qty = 70.
    - The remainder gets reserved_for_plan_position_id set.
    """
    ctx = await _make_six_section_fixture(session, sku="FG-MRP-COMPAT", planned_qty=Decimal("100"), with_spg=True)
    product = ctx["product"]
    sections = ctx["sections"]
    spg = ctx["spg"]
    position = ctx["position"]

    # Get the route stages to build completed_stages_json
    from sqlalchemy import select
    from app.models.route import RouteStage as RS
    stages_q = (await session.execute(
        select(RS).where(RS.route_id == position.route_id).order_by(RS.sequence)
    )).scalars().all()

    # Create a compatible remainder: completed stages 1 and 2 (sections[0] and sections[1])
    completed_stages_json = [
        {"sequence": stages_q[0].sequence, "section_id": sections[0].id, "operation_code": "ISSUE_RAW", "operation_name": "ISSUE_RAW"},
        {"sequence": stages_q[1].sequence, "section_id": sections[1].id, "operation_code": "DRILL", "operation_name": "DRILL"},
    ]
    rem = SpgRemainder(
        product_id=product.id,
        spg_id=spg.id,
        route_stage_id=stages_q[1].id,  # last completed stage
        remainder_quantity=Decimal("30"),
        original_issued=Decimal("100"),
        source="task",
        completed_stages_json=completed_stages_json,
    )
    session.add(rem)
    await session.commit()

    # Take to work — triggers MRP logic
    resp = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [position.id]},
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert result["status"] == "success", result

    # Reload session
    await session.refresh(rem)

    # Remainder should be reserved for this position
    assert rem.reserved_for_plan_position_id == position.id

    # Load created tasks ordered by sequence
    tasks = (await session.execute(
        select(WorkTask)
        .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
        .where(SectionPlanLine.plan_position_id == position.id)
        .order_by(SectionPlanLine.sequence, WorkTask.id)
    )).scalars().all()

    assert len(tasks) == 6

    # Stages 1 and 2 (seq 1,2): covered by remainder (max_seq=2 >= 1,2) → planned_qty = 70
    assert tasks[0].planned_quantity == Decimal("70"), f"Stage 1 qty: {tasks[0].planned_quantity}"
    assert tasks[1].planned_quantity == Decimal("70"), f"Stage 2 qty: {tasks[1].planned_quantity}"
    # Stages 3-6: not covered → planned_qty = 100
    for i in range(2, 6):
        assert tasks[i].planned_quantity == Decimal("100"), f"Stage {i+1} qty: {tasks[i].planned_quantity}"

    # First stage with qty > 0 (stage 1, qty=70) should be ready
    assert tasks[0].status == WorkTaskStatus.ready


@pytest.mark.asyncio
async def test_mrp_zero_quantity_stages_are_autocompleted(client, session):
    """MRP: stages fully covered by remainder get planned_quantity=0 and status=completed.

    Setup:
    - Release quantity = 30, remainder_quantity = 30 covering stages 1..2.
    - Stages 1 and 2 get planned_qty = max(0, 30-30) = 0 → auto-completed.
    - Stage 3+ gets planned_qty = 30 → ready (first nonzero stage).
    """
    ctx = await _make_six_section_fixture(session, sku="FG-MRP-ZERO", planned_qty=Decimal("30"), with_spg=True)
    product = ctx["product"]
    sections = ctx["sections"]
    spg = ctx["spg"]
    position = ctx["position"]

    from sqlalchemy import select
    from app.models.route import RouteStage as RS
    stages_q = (await session.execute(
        select(RS).where(RS.route_id == position.route_id).order_by(RS.sequence)
    )).scalars().all()

    completed_stages_json = [
        {"sequence": stages_q[0].sequence, "section_id": sections[0].id, "operation_code": "ISSUE_RAW", "operation_name": "ISSUE_RAW"},
        {"sequence": stages_q[1].sequence, "section_id": sections[1].id, "operation_code": "DRILL", "operation_name": "DRILL"},
    ]
    rem = SpgRemainder(
        product_id=product.id,
        spg_id=spg.id,
        route_stage_id=stages_q[1].id,
        remainder_quantity=Decimal("30"),
        original_issued=Decimal("30"),
        source="task",
        completed_stages_json=completed_stages_json,
    )
    session.add(rem)
    await session.commit()

    resp = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [position.id]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"][0]["status"] == "success"

    tasks = (await session.execute(
        select(WorkTask)
        .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
        .where(SectionPlanLine.plan_position_id == position.id)
        .order_by(SectionPlanLine.sequence, WorkTask.id)
    )).scalars().all()

    # Stages 1 and 2: covered → planned=0, status=completed
    assert tasks[0].planned_quantity == Decimal("0")
    assert tasks[0].status == WorkTaskStatus.completed
    assert tasks[1].planned_quantity == Decimal("0")
    assert tasks[1].status == WorkTaskStatus.completed

    # Stage 3: first nonzero → ready
    assert tasks[2].planned_quantity == Decimal("30")
    assert tasks[2].status == WorkTaskStatus.ready

    # Stages 4-6: waiting
    for i in range(3, 6):
        assert tasks[i].status == WorkTaskStatus.waiting_previous


@pytest.mark.asyncio
async def test_mrp_cancel_position_releases_reserved_remainders(client, session):
    """MRP: cancelling a plan position releases reserved SpgRemainder reservations."""
    await _make_user(session)
    ctx = await _make_six_section_fixture(session, sku="FG-MRP-CANCEL", planned_qty=Decimal("50"), with_spg=True)
    product = ctx["product"]
    sections = ctx["sections"]
    spg = ctx["spg"]
    position = ctx["position"]

    from sqlalchemy import select
    from app.models.route import RouteStage as RS
    stages_q = (await session.execute(
        select(RS).where(RS.route_id == position.route_id).order_by(RS.sequence)
    )).scalars().all()

    completed_stages_json = [
        {"sequence": stages_q[0].sequence, "section_id": sections[0].id, "operation_code": "ISSUE_RAW", "operation_name": "ISSUE_RAW"},
    ]
    rem = SpgRemainder(
        product_id=product.id,
        spg_id=spg.id,
        route_stage_id=stages_q[0].id,
        remainder_quantity=Decimal("20"),
        original_issued=Decimal("50"),
        source="task",
        completed_stages_json=completed_stages_json,
    )
    session.add(rem)
    await session.commit()

    # Release to work → remainder gets reserved
    resp = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [position.id]},
    )
    assert resp.status_code == 200
    assert resp.json()["results"][0]["status"] == "success"

    await session.refresh(rem)
    assert rem.reserved_for_plan_position_id == position.id, "Remainder should be reserved after release"

    # Cancel the position → remainder should be freed
    cancel_resp = await client.post(f"/api/production-planning/rows/{position.id}/cancel")
    assert cancel_resp.status_code == 200, cancel_resp.text

    await session.refresh(rem)
    assert rem.reserved_for_plan_position_id is None, "Remainder reservation should be released after cancel"

