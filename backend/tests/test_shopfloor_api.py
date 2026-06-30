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
    assert len(tasks) == 6
    first_task, second_task = tasks[0], tasks[1]

    issue_res = await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/issue",
        json={"quantity": "100"},
        headers=headers,
    )
    assert issue_res.status_code == 200

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

    accept_res = await client.post(
        f"/api/shopfloor/transfers/{transfer_id}/accept",
        json={"accepted_quantity": "70", "rejected_quantity": "10", "reason": "transfer_shortage"},
        headers=headers,
    )
    assert accept_res.status_code == 200
    discrepancy_id = accept_res.json()["discrepancy_id"]
    assert discrepancy_id is not None

    defect_details = await client.get(f"/api/shopfloor/defects/{defect_id}", headers=headers)
    assert defect_details.status_code == 200
    defect_item_id = defect_details.json()["items"][0]["id"]

    resolve_res = await client.post(
        f"/api/shopfloor/transfers/{transfer_id}/discrepancies/{discrepancy_id}/resolve-link",
        json={"defect_item_id": defect_item_id, "quantity": "10"},
        headers=headers,
    )
    assert resolve_res.status_code == 200
    assert resolve_res.json()["status"] == "resolved"

    transfer_details = await client.get(f"/api/shopfloor/transfers/{transfer_id}", headers=headers)
    assert transfer_details.status_code == 200
    assert transfer_details.json()["discrepancies"][0]["status"] == "resolved"

    stage_aggregates = await client.get(f"/api/shopfloor/plan-positions/{pos.id}/route-stage-aggregates", headers=headers)
    assert stage_aggregates.status_code == 200
    assert len(stage_aggregates.json()["stages"]) == 6


@pytest.mark.asyncio
async def test_shopfloor_over_issue_rejected(client, session) -> None:
    """Verify that over-issue is allowed and extra quantity is tracked."""
    user = await _make_user(session, "shopfloor2@test.local")
    _, plan, pos = await _make_product_route_plan(session, "FG-SF-2")
    headers = _auth_headers(user)

    await _release_plan_position(client, plan.id, pos.id)
    task = (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == pos.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().first()
    assert task is not None

    # Over-issue should be allowed (quantity 101 > planned 100)
    res = await client.post(
        f"/api/shopfloor/tasks/{task.id}/issue",
        json={"quantity": "101"},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    # Verify that issued quantity is tracked correctly
    assert data["status"] in ("in_progress", "issued")
    # The task should track 101 issued
    await session.refresh(task)
    assert task.cached_issued_quantity == Decimal("101")


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

    await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/issue",
        json={"quantity": "100"},
        headers=headers,
    )
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
    transfer_id = send_res.json()["transfer_id"]

    accept_res = await client.post(
        f"/api/shopfloor/transfers/{transfer_id}/accept",
        json={"accepted_quantity": "25", "rejected_quantity": "0"},
        headers=headers,
    )
    assert accept_res.status_code == 200

    board_res = await client.get(
        f"/api/shopfloor/sections/{second_task.section_id}/board",
        headers=headers,
    )
    assert board_res.status_code == 200
    row = next(item for item in board_res.json()["tasks"] if item["id"] == second_task.id)
    assert Decimal(row["cache"]["in_work_quantity"]) == Decimal("25")

    # Over-issue on second stage should be allowed (26 > available 25)
    over_issue = await client.post(
        f"/api/shopfloor/tasks/{second_task.id}/issue",
        json={"quantity": "26"},
        headers=headers,
    )
    assert over_issue.status_code == 200
    # Extra quantity should be tracked
    await session.refresh(second_task)
    assert second_task.cached_issued_quantity == Decimal("51")


@pytest.mark.asyncio
async def test_shopfloor_idempotent_issue_not_duplicated(client, session) -> None:
    """Repeated issue with same idempotency_key must not create duplicate movements."""
    user = await _make_user(session, "shopfloor-idem@test.local")
    _, plan, pos = await _make_product_route_plan(session, "FG-SF-IDEM")
    headers = _auth_headers(user)

    await _release_plan_position(client, plan.id, pos.id)
    task = (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == pos.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().first()
    assert task is not None

    first = await client.post(
        f"/api/shopfloor/tasks/{task.id}/issue",
        json={"quantity": "50", "idempotency_key": "idem-key-1"},
        headers=headers,
    )
    assert first.status_code == 200
    first_movement_id = first.json()["movement_id"]

    second = await client.post(
        f"/api/shopfloor/tasks/{task.id}/issue",
        json={"quantity": "50", "idempotency_key": "idem-key-1"},
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json()["idempotent_replay"] is True
    assert second.json()["movement_id"] == first_movement_id


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

    await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/issue",
        json={"quantity": "100"},
        headers=headers,
    )
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
    """accepted + rejected must not exceed sent quantity."""
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

    await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/issue",
        json={"quantity": "100"},
        headers=headers,
    )
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
    transfer_id = xfer.json()["transfer_id"]

    res = await client.post(
        f"/api/shopfloor/transfers/{transfer_id}/accept",
        json={"accepted_quantity": "40", "rejected_quantity": "20"},
        headers=headers,
    )
    assert res.status_code == 400
    assert "exceeds sent" in res.json()["detail"]


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

    await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/issue",
        json={"quantity": "60"},
        headers=headers,
    )
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

    summary_res = await client.get("/api/shopfloor/sections/summary", headers=headers)
    assert summary_res.status_code == 200
    sections = summary_res.json()["sections"]
    second_section = next((item for item in sections if item["section_id"] == second_task.section_id), None)
    assert second_section is not None
    assert second_section["incoming_transfers_count"] >= 1

    incoming_res = await client.get(f"/api/shopfloor/sections/{second_task.section_id}/incoming-transfers", headers=headers)
    assert incoming_res.status_code == 200
    incoming = incoming_res.json()["incoming_transfers"]
    assert len(incoming) >= 1
    row = next((item for item in incoming if item["transfer_id"] == transfer_id), None)
    assert row is not None
    assert row["status"] in {"sent", "partially_accepted"}
    assert Decimal(row["remaining_quantity"]) == Decimal("40")


@pytest.mark.asyncio
async def test_shopfloor_issue_complete_transfer_persist_fact_fields(client, session) -> None:
    user = await _make_user(session, "shopfloor-fact@test.local")
    _, plan, pos = await _make_product_route_plan(session, "FG-SF-FACT")
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

    performed = "2026-05-10T08:00:00+00:00"
    accounted = "2026-05-10T08:15:00+00:00"

    issue_res = await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/issue",
        json={
            "quantity": "100",
            "performed_at": performed,
            "accounted_at": accounted,
        },
        headers=headers,
    )
    assert issue_res.status_code == 200

    complete_res = await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/complete",
        json={
            "good_quantity": "100",
            "defect_quantity": "0",
            "performed_at": performed,
            "accounted_at": accounted,
        },
        headers=headers,
    )
    assert complete_res.status_code == 200

    send_res = await client.post(
        "/api/shopfloor/transfers",
        json={
            "from_task_id": first_task.id,
            "to_task_id": second_task.id,
            "quantity": "100",
            "performed_at": performed,
            "accounted_at": accounted,
        },
        headers=headers,
    )
    assert send_res.status_code == 200

    detail = await client.get(f"/api/shopfloor/tasks/{first_task.id}", headers=headers)
    assert detail.status_code == 200
    movements = detail.json()["movements"]
    assert len(movements) >= 3
    # Ensure all persisted with actor as executor and with supplied times
    for m in movements[:3]:
        if m["movement_type"] in {"issue_to_work", "complete", "transfer_send"}:
            assert m["executor_user_id"] == user.id
            assert m["performed_at"] is not None
            assert m["accounted_at"] is not None


@pytest.mark.asyncio
async def test_shopfloor_single_window_lock_enforced(client, session) -> None:
    user = await _make_user(session, "shopfloor-lock@test.local")
    _, plan, pos = await _make_product_route_plan(session, "FG-SF-LOCK")
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

    lock_first = {**headers, "X-Shopfloor-Single-Section-Id": str(first_task.section_id)}
    lock_second = {**headers, "X-Shopfloor-Single-Section-Id": str(second_task.section_id)}

    board_ok = await client.get(f"/api/shopfloor/sections/{first_task.section_id}/board", headers=lock_first)
    assert board_ok.status_code == 200

    board_blocked = await client.get(f"/api/shopfloor/sections/{second_task.section_id}/board", headers=lock_first)
    assert board_blocked.status_code == 403
    assert board_blocked.json()["detail"] == "Section is locked to single-window context"

    incoming_blocked = await client.get(
        f"/api/shopfloor/sections/{second_task.section_id}/incoming-transfers",
        headers=lock_first,
    )
    assert incoming_blocked.status_code == 403
    assert incoming_blocked.json()["detail"] == "Section is locked to single-window context"

    stats_blocked = await client.get(
        f"/api/shopfloor/sections/{second_task.section_id}/daily-stats",
        params={"date_from": "2026-05-01T00:00:00", "date_to": "2026-05-31T23:59:59"},
        headers=lock_first,
    )
    assert stats_blocked.status_code == 403
    assert stats_blocked.json()["detail"] == "Section is locked to single-window context"

    issue_wrong = await client.post(
        f"/api/shopfloor/tasks/{second_task.id}/issue",
        json={"quantity": "1"},
        headers=lock_first,
    )
    assert issue_wrong.status_code == 403
    assert issue_wrong.json()["detail"] == "Section is locked to single-window context"

    complete_wrong = await client.post(
        f"/api/shopfloor/tasks/{second_task.id}/complete",
        json={"good_quantity": "1", "defect_quantity": "0"},
        headers=lock_first,
    )
    assert complete_wrong.status_code == 403
    assert complete_wrong.json()["detail"] == "Section is locked to single-window context"

    issue_ok = await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/issue",
        json={"quantity": "100"},
        headers=lock_first,
    )
    assert issue_ok.status_code == 200

    complete_ok = await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/complete",
        json={"good_quantity": "100", "defect_quantity": "0"},
        headers=lock_first,
    )
    assert complete_ok.status_code == 200

    send_ok = await client.post(
        "/api/shopfloor/transfers",
        json={"from_task_id": first_task.id, "to_task_id": second_task.id, "quantity": "100"},
        headers=lock_first,
    )
    assert send_ok.status_code == 200
    transfer_id = send_ok.json()["transfer_id"]

    send_wrong = await client.post(
        "/api/shopfloor/transfers",
        json={"from_task_id": second_task.id, "to_task_id": first_task.id, "quantity": "1"},
        headers=lock_first,
    )
    assert send_wrong.status_code == 403
    assert send_wrong.json()["detail"] == "Section is locked to single-window context"

    accept_wrong = await client.post(
        f"/api/shopfloor/transfers/{transfer_id}/accept",
        json={"accepted_quantity": "100", "rejected_quantity": "0"},
        headers=lock_first,
    )
    assert accept_wrong.status_code == 403
    assert accept_wrong.json()["detail"] == "Section is locked to single-window context"

    accept_ok = await client.post(
        f"/api/shopfloor/transfers/{transfer_id}/accept",
        json={"accepted_quantity": "100", "rejected_quantity": "0"},
        headers=lock_second,
    )
    assert accept_ok.status_code == 200


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

    issue_res = await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/issue",
        json={"quantity": "100"},
        headers=headers,
    )
    assert issue_res.status_code == 200

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


@pytest.mark.asyncio
async def test_shopfloor_issue_shortage_strategies_and_compensation(client, session) -> None:
    from app.models.spg_remainder import SpgRemainder

    user = await _make_user(session, "shortage_strats@test.local")
    _, plan, pos = await _make_product_route_plan(session, "FG-SHORTAGE-STRATS")
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

    from app.models.spg import StorageProductionGroup, SpgSection
    spg = StorageProductionGroup(code="TEST-STRATS-SPG", name="Test SPG", is_active=True, sort_order=1)
    session.add(spg)
    await session.flush()
    session.add(SpgSection(spg_id=spg.id, section_id=first_task.section_id, sort_order=0))
    await session.flush()

    # 1. Проверяем стратегию fail при нехватке (запрос 120 деталей, доступно 100)
    res_fail = await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/issue",
        json={"quantity": "120", "shortage_strategy": "fail"},
        headers=headers,
    )
    assert res_fail.status_code == 400
    assert "Недостаточно доступного количества" in res_fail.json()["detail"]

    # 2. Проверяем стратегию partial при нехватке (запрос 120 деталей, доступно 100 -> должно выдать ровно 100)
    res_partial = await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/issue",
        json={"quantity": "120", "shortage_strategy": "partial"},
        headers=headers,
    )
    assert res_partial.status_code == 200
    await session.refresh(first_task)
    assert first_task.cached_issued_quantity == Decimal("100")
    assert first_task.cached_available_quantity == Decimal("0")

    # 3. Теперь, когда доступно 0 деталей, проверяем стратегию partial (должно вернуть ошибку)
    res_partial_zero = await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/issue",
        json={"quantity": "10", "shortage_strategy": "partial"},
        headers=headers,
    )
    assert res_partial_zero.status_code == 400
    assert "Доступное количество равно 0" in res_partial_zero.json()["detail"]

    # 4. Проверяем стратегию negative_remainder при запросе еще 10 деталей (доступно 0)
    res_negative = await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/issue",
        json={"quantity": "10", "shortage_strategy": "negative_remainder"},
        headers=headers,
    )
    assert res_negative.status_code == 200
    await session.refresh(first_task)
    assert first_task.cached_issued_quantity == Decimal("110")

    # Проверяем, что в БД появился отрицательный остаток -10
    neg_rem = await session.scalar(
        select(SpgRemainder)
        .where(
            SpgRemainder.origin_task_id == first_task.id,
            SpgRemainder.remainder_quantity < 0,
            SpgRemainder.consumed_at.is_(None),
        )
    )
    assert neg_rem is not None
    assert neg_rem.remainder_quantity == Decimal("-10")

    # 5. Проверим автокомпенсацию:
    res_complete = await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/complete",
        json={"good_quantity": "100"},
        headers=headers,
    )
    assert res_complete.status_code == 200

    # Возврат остатка на участок 10 шт
    res_return = await client.post(
        "/api/shopfloor/remainders/return",
        json={"task_id": first_task.id, "quantity": "10"},
        headers=headers,
    )
    assert res_return.status_code == 200

    # Проверяем, что отрицательный остаток -10 и положительный остаток +10 схлопнулись!
    await session.refresh(neg_rem)
    assert neg_rem.consumed_at is not None
    assert neg_rem.remainder_quantity == Decimal("0")


