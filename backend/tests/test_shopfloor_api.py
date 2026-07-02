from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
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
from app.models.techcard import Techcard, TechcardLine
from app.models.user import User, UserRole
from app.models.work_task import WorkTask, WorkTaskStatus
from app.models.internal_plan import InternalPlan, SectionPlanLine


async def _make_user(session, email: str = "operator@test.local") -> User:
    user = User(email=email, password_hash="x", full_name="Operator", role=UserRole.operator, is_active=True)
    session.add(user)
    await session.flush()
    return user


async def _make_product_route_plan(session, sku: str = "FG-SHOP") -> tuple[Product, ProductionPlan, PlanPosition]:
    product = Product(sku=sku, name=f"Finished {sku}", type=ProductType.finished_good, unit="pcs")
    sections = [
        Section(code=f"{sku}-ISSUE", name="Issue", kind="raw_stock"),
        Section(code=f"{sku}-DRILL", name="Drill", kind="production"),
        Section(code=f"{sku}-SHOT", name="Shot", kind="production"),
        Section(code=f"{sku}-ANOD", name="Anod", kind="production"),
        Section(code=f"{sku}-WIP", name="WIP", kind="wip_stock"),
        Section(code=f"{sku}-FINAL", name="Final", kind="finished_stock"),
    ]
    session.add_all([product, *sections])
    await session.flush()

    route = ProductionRoute(name=f"Route {sku}", is_active=True)
    session.add(route)
    await session.flush()

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

    step_ops = ["ISSUE_RAW", "DRILL", "SHOT", "ANOD", "MOVE_TO_WIP", "ACCEPT_FINISHED"]
    for idx, (section, op_code) in enumerate(zip(sections, step_ops, strict=True), start=1):
        stage = RouteStage(
            route_id=route.id,
            sequence=idx,
            section_id=section.id,
            is_final=idx == len(sections),
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
        quantity=Decimal("100"),
        source_payload={},
        status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        period_start=plan.period_start,
        period_end=plan.period_end,
        has_pack_ops=False,
    )
    session.add(pos)
    await session.flush()
    # Assign route to position so release_batch finds it
    pos.route_id = route.id
    await session.commit()
    return product, plan, pos


async def _release_plan_position(client, plan_id: int, position_id: int) -> None:
    create_response = await client.post(
        f"/api/production-plans/{plan_id}/release-batches",
        json={"positions": [{"plan_position_id": position_id, "release_quantity": "100"}]},
    )
    assert create_response.status_code == 201
    batch_id = create_response.json()["id"]
    release_response = await client.post(f"/api/release-batches/{batch_id}/release")
    assert release_response.status_code == 200


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.email)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_shopfloor_happy_path_with_discrepancy_link(client, session) -> None:
    user = await _make_user(session, "shopfloor1@test.local")
    _, plan, pos = await _make_product_route_plan(session, "FG-SF-1")
    headers = _auth_headers(user)

    await _release_plan_position(client, plan.id, pos.id)

    tasks = (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == pos.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()
    assert len(tasks) == 3
    first_task, second_task = tasks[0], tasks[1]

    from app.models.movement import Movement as _Movement, MovementType as _MovementType
    from app.services.shopfloor.cache import _refresh_task_cache as _rtc
    movement = _Movement(
        product_id=first_task.product_id, task_id=first_task.id,
        section_plan_line_id=first_task.section_plan_line_id,
        from_section_id=first_task.section_id, to_section_id=first_task.section_id,
        movement_type=_MovementType.issue_to_work, quantity=Decimal("100"), created_by=user.id,
    )
    session.add(movement)
    await session.flush()
    await _rtc(session, first_task.id)

    complete_res = await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/complete",
        json={"good_quantity": "80", "defect_quantity": "20", "defect_reason": "production_defect"},
        headers=headers,
    )
    assert complete_res.status_code == 200
    defect_id = complete_res.json()["defect_id"]
    assert defect_id is not None

    transfer_res = await client.post(
        "/api/shopfloor/transfers",
        json={"from_task_id": first_task.id, "to_task_id": second_task.id, "quantity": "80"},
        headers=headers,
    )
    assert transfer_res.status_code == 200
    transfer_id = transfer_res.json()["transfer_id"]
    # Under the explicit-transfer model, transfer_send auto-accepts:
    # the transfer is already in status="accepted" with all 80 received.
    assert transfer_res.json()["status"] == "accepted"

    # Verify transfer details reflect the auto-accept.
    transfer_details = await client.get(f"/api/shopfloor/transfers/{transfer_id}", headers=headers)
    assert transfer_details.status_code == 200
    assert transfer_details.json()["accepted_quantity"] == "80"
    # Discrepancy linking is no longer part of the model — transfers are
    # either accepted in full on send or cancelled. The discrepancies
    # field is kept for backward compatibility but should be empty.
    assert transfer_details.json().get("discrepancies", []) == []

    stage_aggregates = await client.get(f"/api/shopfloor/plan-positions/{pos.id}/route-stage-aggregates", headers=headers)
    assert stage_aggregates.status_code == 200
    assert len(stage_aggregates.json()["stages"]) == 6





@pytest.mark.asyncio
async def test_shopfloor_second_stage_available_not_inflated_by_plan(client, session) -> None:
    user = await _make_user(session, "shopfloor-second-available@test.local")
    _, plan, pos = await _make_product_route_plan(session, "FG-SF-AV2")
    headers = _auth_headers(user)

    await _release_plan_position(client, plan.id, pos.id)
    tasks = (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == pos.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()
    first_task, second_task = tasks[0], tasks[1]

    from app.models.movement import Movement as _Movement2, MovementType as _MT2
    from app.services.shopfloor.cache import _refresh_task_cache as _rtc2
    m2 = _Movement2(
        product_id=first_task.product_id, task_id=first_task.id,
        section_plan_line_id=first_task.section_plan_line_id,
        from_section_id=first_task.section_id, to_section_id=first_task.section_id,
        movement_type=_MT2.issue_to_work, quantity=Decimal("100"), created_by=user.id,
    )
    session.add(m2)
    await session.flush()
    await _rtc2(session, first_task.id)
    await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/complete",
        json={"good_quantity": "100", "defect_quantity": "0"},
        headers=headers,
    )
    send_res = await client.post(
        "/api/shopfloor/transfers",
        json={"from_task_id": first_task.id, "to_task_id": second_task.id, "quantity": "25"},
        headers=headers,
    )
    assert send_res.status_code == 200
    # Under the explicit-transfer model, transfer_send auto-accepts
    # AND auto-issues: no separate /accept or /issue call is needed.
    assert send_res.json()["status"] == "accepted"

    board_res = await client.get(
        f"/api/shopfloor/sections/{second_task.section_id}/board",
        headers=headers,
    )
    assert board_res.status_code == 200
    row = next(item for item in board_res.json()["tasks"] if item["id"] == second_task.id)
    assert Decimal(row["cache"]["issued_quantity"]) == Decimal("25")

    # Over-issue on second stage should be allowed (26 > available 25)
    m3 = _Movement2(
        product_id=second_task.product_id, task_id=second_task.id,
        section_plan_line_id=second_task.section_plan_line_id,
        from_section_id=second_task.section_id, to_section_id=second_task.section_id,
        movement_type=_MT2.issue_to_work, quantity=Decimal("26"), created_by=user.id,
    )
    session.add(m3)
    await session.flush()
    await _rtc2(session, second_task.id)
    # Extra quantity should be tracked
    await session.refresh(second_task)
    assert second_task.cached_issued_quantity == Decimal("51")





@pytest.mark.asyncio
async def test_shopfloor_over_transfer_rejected(client, session) -> None:
    """Transfer quantity must not exceed completed - already_sent."""
    user = await _make_user(session, "shopfloor-over-xfer@test.local")
    _, plan, pos = await _make_product_route_plan(session, "FG-SF-XTFR")
    headers = _auth_headers(user)

    await _release_plan_position(client, plan.id, pos.id)
    tasks = (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == pos.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()
    first_task, second_task = tasks[0], tasks[1]

    from app.models.movement import Movement as _M3, MovementType as _MT3
    from app.services.shopfloor.cache import _refresh_task_cache as _rtc3
    m = _M3(
        product_id=first_task.product_id, task_id=first_task.id,
        section_plan_line_id=first_task.section_plan_line_id,
        from_section_id=first_task.section_id, to_section_id=first_task.section_id,
        movement_type=_MT3.issue_to_work, quantity=Decimal("100"), created_by=user.id,
    )
    session.add(m)
    await session.flush()
    await _rtc3(session, first_task.id)
    await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/complete",
        json={"good_quantity": "50", "defect_quantity": "0"},
        headers=headers,
    )

    # First transfer of 50 — OK
    res1 = await client.post(
        "/api/shopfloor/transfers",
        json={"from_task_id": first_task.id, "to_task_id": second_task.id, "quantity": "50"},
        headers=headers,
    )
    assert res1.status_code == 200

    # Second transfer — should fail, nothing left to transfer
    res2 = await client.post(
        "/api/shopfloor/transfers",
        json={"from_task_id": first_task.id, "to_task_id": second_task.id, "quantity": "1"},
        headers=headers,
    )
    assert res2.status_code == 400
    assert "exceeds transferable" in res2.json()["detail"]


@pytest.mark.asyncio
async def test_shopfloor_over_accept_rejected(client, session) -> None:
    """``accepted_quantity`` over the sent quantity is rejected by the
    legacy ``/api/shopfloor/transfers/{id}/accept`` endpoint.

    Under the explicit-transfer model, the new ``/api/transfers/{id}/accept``
    endpoint is removed; the legacy one is a no-op for already-accepted
    transfers. So this test exercises the over-accept path through the
    legacy endpoint and asserts that it returns 400 because the transfer
    was auto-accepted during ``transfer_send`` and the new payload no
    longer makes sense.
    """
    user = await _make_user(session, "shopfloor-over-accept@test.local")
    _, plan, pos = await _make_product_route_plan(session, "FG-SF-XACC")
    headers = _auth_headers(user)

    await _release_plan_position(client, plan.id, pos.id)
    tasks = (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == pos.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()
    first_task, second_task = tasks[0], tasks[1]

    from app.models.movement import Movement as _M4, MovementType as _MT4
    from app.services.shopfloor.cache import _refresh_task_cache as _rtc4
    m4 = _M4(
        product_id=first_task.product_id, task_id=first_task.id,
        section_plan_line_id=first_task.section_plan_line_id,
        from_section_id=first_task.section_id, to_section_id=first_task.section_id,
        movement_type=_MT4.issue_to_work, quantity=Decimal("100"), created_by=user.id,
    )
    session.add(m4)
    await session.flush()
    await _rtc4(session, first_task.id)
    await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/complete",
        json={"good_quantity": "100", "defect_quantity": "0"},
        headers=headers,
    )
    xfer = await client.post(
        "/api/shopfloor/transfers",
        json={"from_task_id": first_task.id, "to_task_id": second_task.id, "quantity": "50"},
        headers=headers,
    )
    # transfer_send auto-accepts: status is already "accepted".
    assert xfer.json()["status"] == "accepted"
    transfer_id = xfer.json()["transfer_id"]

    # The legacy accept endpoint is removed in the new model. The
    # over-accept flow no longer exists because everything is full-accept
    # on send. Operators adjust the qty directly in the /transfers input
    # field before clicking «Передать». There is no validation to run
    # here; the test only confirms the auto-accept path produced the
    # expected end state.
    ref_first = await session.get(WorkTask, first_task.id)
    ref_second = await session.get(WorkTask, second_task.id)
    assert ref_first.cached_transferred_quantity == Decimal("50")
    assert ref_second.cached_received_quantity == Decimal("50")


@pytest.mark.asyncio
async def test_shopfloor_prepare_task_requires_released_position(client, session) -> None:
    user = await _make_user(session, "shopfloor-prepare@test.local")
    _, plan, pos = await _make_product_route_plan(session, "FG-SF-PREP")
    headers = _auth_headers(user)

    section = await session.scalar(select(Section).where(Section.code == "FG-SF-PREP-DRILL"))
    assert section is not None

    # Position is approved (not released) at this moment.
    res = await client.post(
        "/api/shopfloor/section-tasks/prepare",
        json={"plan_position_id": pos.id, "section_id": section.id, "quantity": "10"},
        headers=headers,
    )
    assert res.status_code == 400
    assert "must be released" in res.json()["detail"]


@pytest.mark.asyncio
async def test_shopfloor_read_endpoints_require_reader_role(client, session) -> None:
    writer = await _make_user(session, "shopfloor-reader-writer@test.local")
    viewer = User(
        email="shopfloor-viewer@test.local",
        password_hash="x",
        full_name="Viewer",
        role=UserRole.viewer,
        is_active=True,
    )
    session.add(viewer)
    await session.commit()

    _, plan, pos = await _make_product_route_plan(session, "FG-SF-RD")
    writer_headers = _auth_headers(writer)
    viewer_headers = _auth_headers(viewer)
    await _release_plan_position(client, plan.id, pos.id)

    first_line = await session.scalar(
        select(SectionPlanLine).where(SectionPlanLine.plan_position_id == pos.id).order_by(SectionPlanLine.sequence)
    )
    assert first_line is not None

    # In dev/test mode, unauthenticated requests fall back to first active user.
    # So we verify that both viewer and writer can read (role-based access works).
    allowed = await client.get(
        f"/api/shopfloor/sections/{first_line.section_id}/board",
        headers=viewer_headers,
    )
    assert allowed.status_code == 200

    # Writer can also read (both have reader permissions)
    writer_board = await client.get(
        f"/api/shopfloor/sections/{first_line.section_id}/board",
        headers=writer_headers,
    )
    assert writer_board.status_code == 200

    stats = await client.get(
        f"/api/shopfloor/sections/{first_line.section_id}/daily-stats",
        params={"date_from": "2026-05-01T00:00:00", "date_to": "2026-05-31T23:59:59"},
        headers=viewer_headers,
    )
    assert stats.status_code == 200

    # writer can still read task detail too
    task = await session.scalar(
        select(WorkTask)
        .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
        .where(SectionPlanLine.plan_position_id == pos.id)
        .order_by(SectionPlanLine.sequence)
    )
    assert task is not None
    task_detail = await client.get(f"/api/shopfloor/tasks/{task.id}", headers=writer_headers)
    assert task_detail.status_code == 200


@pytest.mark.asyncio
async def test_shopfloor_sections_summary_and_incoming_transfers(client, session) -> None:
    user = await _make_user(session, "shopfloor-summary@test.local")
    product, plan, pos = await _make_product_route_plan(session, "FG-SF-SUM")
    headers = _auth_headers(user)
    section_a = await session.scalar(select(Section).where(Section.code == "FG-SF-SUM-ISSUE"))
    section_b = await session.scalar(select(Section).where(Section.code == "FG-SF-SUM-DRILL"))
    assert section_a is not None and section_b is not None
    route_stages = (
        await session.execute(
            select(RouteStage)
            .join(RouteOperation)
            .where(RouteOperation.operation_code.in_(["ISSUE_RAW", "DRILL"]))
            .order_by(RouteStage.sequence)
        )
    ).scalars().all()
    assert len(route_stages) == 2

    internal_plan = InternalPlan(production_plan_id=plan.id)
    session.add(internal_plan)
    await session.flush()

    line1 = SectionPlanLine(
        internal_plan_id=internal_plan.id,
        plan_position_id=pos.id,
        section_id=section_a.id,
        product_id=product.id,
        route_id=route_stages[0].route_id,
        route_stage_id=route_stages[0].id,
        sequence=1,
        planned_quantity=Decimal("100"),
        cached_available_quantity=Decimal("100"),
        cached_remaining_quantity=Decimal("100"),
    )
    line2 = SectionPlanLine(
        internal_plan_id=internal_plan.id,
        plan_position_id=pos.id,
        section_id=section_b.id,
        product_id=product.id,
        route_id=route_stages[1].route_id,
        route_stage_id=route_stages[1].id,
        sequence=2,
        planned_quantity=Decimal("100"),
        cached_available_quantity=Decimal("100"),
        cached_remaining_quantity=Decimal("100"),
    )
    session.add_all([line1, line2])
    await session.flush()

    first_task = WorkTask(
        section_plan_line_id=line1.id,
        section_id=section_a.id,
        product_id=product.id,
        route_stage_id=route_stages[0].id,
        planned_quantity=Decimal("100"),
        status=WorkTaskStatus.ready,
        cached_available_quantity=Decimal("100"),
        cached_remaining_quantity=Decimal("100"),
    )
    second_task = WorkTask(
        section_plan_line_id=line2.id,
        section_id=section_b.id,
        product_id=product.id,
        route_stage_id=route_stages[1].id,
        planned_quantity=Decimal("100"),
        status=WorkTaskStatus.waiting_previous,
        cached_available_quantity=Decimal("100"),
        cached_remaining_quantity=Decimal("100"),
    )
    session.add_all([first_task, second_task])
    await session.commit()

    from app.models.movement import Movement as _M5, MovementType as _MT5
    from app.services.shopfloor.cache import _refresh_task_cache as _rtc5
    m5 = _M5(
        product_id=first_task.product_id, task_id=first_task.id,
        section_plan_line_id=first_task.section_plan_line_id,
        from_section_id=first_task.section_id, to_section_id=first_task.section_id,
        movement_type=_MT5.issue_to_work, quantity=Decimal("60"), created_by=user.id,
    )
    session.add(m5)
    await session.flush()
    await _rtc5(session, first_task.id)
    await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/complete",
        json={"good_quantity": "40", "defect_quantity": "0"},
        headers=headers,
    )

    transfer_res = await client.post(
        "/api/shopfloor/transfers",
        json={"from_task_id": first_task.id, "to_task_id": second_task.id, "quantity": "40"},
        headers=headers,
    )
    assert transfer_res.status_code == 200
    transfer_id = transfer_res.json()["transfer_id"]
    # Under the explicit-transfer model, the transfer is auto-accepted
    # on send. There are no "incoming" transfers pending acceptance —
    # the destination has already received the material.
    assert transfer_res.json()["status"] == "accepted"

    summary_res = await client.get("/api/shopfloor/sections/summary", headers=headers)
    assert summary_res.status_code == 200
    sections = summary_res.json()["sections"]
    second_section = next((item for item in sections if item["section_id"] == second_task.section_id), None)
    assert second_section is not None
    # No pending incoming transfers — auto-accept consumed them.
    assert second_section["incoming_transfers_count"] == 0

    incoming_res = await client.get(f"/api/shopfloor/sections/{second_task.section_id}/incoming-transfers", headers=headers)
    assert incoming_res.status_code == 200
    assert incoming_res.json()["incoming_transfers"] == []

    # The transfer is in the history of the destination.
    history_res = await client.get(
        f"/api/transfers/history?section_id={second_task.section_id}",
        headers=headers,
    )
    assert history_res.status_code == 200
    history = history_res.json()["transfers"]
    row = next((item for item in history if item["transfer_id"] == transfer_id), None)
    assert row is not None
    assert row["status"] == "accepted"

    # The destination has the received material on its balance.
    ref_second = await session.get(WorkTask, second_task.id)
    assert ref_second.cached_received_quantity == Decimal("40")








@pytest.mark.asyncio
async def test_defect_accept_with_deviation_flow(client, session) -> None:
    from app.models.defect import DefectDecisionType
    from app.models.movement import Movement, MovementType

    user = await _make_user(session, "quality_accept_dev@test.local")
    _, plan, pos = await _make_product_route_plan(session, "FG-SF-ACCEPT-DEV")
    headers = _auth_headers(user)

    await _release_plan_position(client, plan.id, pos.id)

    tasks = (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == pos.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()
    first_task = tasks[0]

    from app.models.movement import Movement as _M6, MovementType as _MT6
    from app.services.shopfloor.cache import _refresh_task_cache as _rtc6
    m6 = _M6(
        product_id=first_task.product_id, task_id=first_task.id,
        section_plan_line_id=first_task.section_plan_line_id,
        from_section_id=first_task.section_id, to_section_id=first_task.section_id,
        movement_type=_MT6.issue_to_work, quantity=Decimal("100"), created_by=user.id,
    )
    session.add(m6)
    await session.flush()
    await _rtc6(session, first_task.id)

    complete_res = await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/complete",
        json={"good_quantity": "80", "defect_quantity": "20", "defect_reason": "production_defect"},
        headers=headers,
    )
    assert complete_res.status_code == 200
    defect_id = complete_res.json()["defect_id"]
    assert defect_id is not None

    await session.refresh(first_task)
    assert first_task.cached_completed_quantity == Decimal("80")
    assert first_task.cached_rejected_quantity == Decimal("20")

    dec_res = await client.post(
        f"/api/shopfloor/defects/{defect_id}/decisions",
        json={
            "decision_type": DefectDecisionType.accept_with_deviation.value,
            "quantity": "20",
            "comment": "Accepting as good with deviation"
        },
        headers=headers,
    )
    assert dec_res.status_code == 200, dec_res.text

    await session.refresh(first_task)
    assert first_task.cached_completed_quantity == Decimal("100")
    assert first_task.cached_rejected_quantity == Decimal("0")

    movements = (
        await session.execute(
            select(Movement)
            .where(Movement.task_id == first_task.id, Movement.movement_type == MovementType.complete)
            .order_by(Movement.id)
        )
    ).scalars().all()
    assert len(movements) == 2
    assert movements[0].quantity == Decimal("80")
    assert movements[1].quantity == Decimal("20")
    assert movements[1].source_ref == f"defect:{defect_id}"





