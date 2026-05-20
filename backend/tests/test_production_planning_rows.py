from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.internal_plan import InternalPlan, SectionPlanLine
from app.models.movement import Movement
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteStep
from app.models.routing import RouteOperationFamily, RouteOutputKind
from app.models.section import Section
from app.models.techcard import Techcard, TechcardLine
from app.models.transfer import Transfer
from app.models.user import User, UserRole
from app.models.work_task import WorkTask, WorkTaskStatus


async def _make_product_with_route(session, sku: str = "FG-EXEC") -> tuple[Product, ProductionRoute]:
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

    route = ProductionRoute(name=f"Route-{sku}", is_active=True)
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
        session.add(
            RouteStep(
                route_id=route.id,
                sequence=idx,
                section_id=section.id,
                operation_code=op_code,
                operation_name=op_code,
                is_final=idx == len(sections),
            )
        )
    await session.flush()
    return product, route


async def _make_plan(session, code: str = "EXEC") -> ProductionPlan:
    plan = ProductionPlan(
        plan_no=f"PLAN-{code}",
        name=f"Plan {code}",
        status=ProductionPlanStatus.approved,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()
    return plan


async def _ensure_system_user(session) -> User:
    user = User(
        email="system@local",
        password_hash="x",
        full_name="System User",
        role=UserRole.admin,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_position(
    session,
    *,
    plan_id: int,
    sku: str,
    name: str,
    quantity: Decimal = Decimal("100"),
    product_id: int | None = None,
    status: PlanPositionStatus = PlanPositionStatus.approved,
    row_num: int | None = None,
    operation_family: RouteOperationFamily | None = RouteOperationFamily.DRILL,
    output_kind: RouteOutputKind | None = RouteOutputKind.finished_good,
    has_pack_ops: bool = False,
) -> PlanPosition:
    position = PlanPosition(
        production_plan_id=plan_id,
        product_id=product_id,
        source_type=PlanSourceType.manual,
        source_sku=sku,
        source_name=name,
        quantity=quantity,
        source_payload={},
        source_row_number=row_num,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        status=status,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        operation_family=operation_family,
        output_kind=output_kind,
        has_pack_ops=has_pack_ops,
    )
    session.add(position)
    await session.flush()
    return position


@pytest.mark.asyncio
async def test_rows_detail_for_released_position_with_tasks(client, session) -> None:
    product, route = await _make_product_with_route(session, "FG-REL")
    plan = await _make_plan(session, "REL")
    position = await _make_position(
        session,
        plan_id=plan.id,
        sku=product.sku,
        name=product.name,
        quantity=Decimal("100"),
        product_id=product.id,
    )
    position.route_id = route.id
    await session.commit()

    create_batch_response = await client.post(
        f"/api/production-plans/{plan.id}/release-batches",
        json={"positions": [{"plan_position_id": position.id, "release_quantity": "100"}]},
    )
    assert create_batch_response.status_code == 201
    batch_id = create_batch_response.json()["id"]

    release_response = await client.post(f"/api/release-batches/{batch_id}/release")
    assert release_response.status_code == 200

    tasks = (await session.execute(select(WorkTask).order_by(WorkTask.id))).scalars().all()
    assert tasks
    tasks[0].cached_completed_quantity = Decimal("30")
    tasks[0].cached_transferred_quantity = Decimal("20")
    tasks[0].cached_rejected_quantity = Decimal("5")
    await session.commit()

    response = await client.get(f"/api/production-planning/rows/{position.id}")
    assert response.status_code == 200
    data = response.json()

    assert data["plan_position_id"] == position.id
    assert data["route_id"] == route.id
    assert data["has_tasks"] is True
    assert data["not_started"] is False
    assert len(data["stages"]) == 6

    first_stage = data["stages"][0]
    assert first_stage["planned_quantity"] == 100.0
    assert first_stage["completed_quantity"] == 30.0
    assert first_stage["transferred_quantity"] == 20.0
    assert first_stage["rejected_quantity"] == 5.0
    assert first_stage["execution_percent"] == 30.0
    assert first_stage["transfer_percent"] == 20.0
    assert first_stage["reject_percent"] == 5.0


@pytest.mark.asyncio
async def test_rows_detail_for_not_started_position(client, session) -> None:
    product, route = await _make_product_with_route(session, "FG-NOSTART")
    plan = await _make_plan(session, "NOSTART")
    position = await _make_position(
        session,
        plan_id=plan.id,
        sku=product.sku,
        name=product.name,
        quantity=Decimal("50"),
        product_id=product.id,
    )
    position.route_id = route.id
    await session.commit()

    response = await client.get(f"/api/production-planning/rows/{position.id}")
    assert response.status_code == 200
    data = response.json()

    assert data["route_id"] == route.id
    assert data["has_tasks"] is False
    assert data["not_started"] is True
    assert len(data["stages"]) == 6
    assert all(stage["not_started"] is True for stage in data["stages"])
    assert all(stage["planned_quantity"] == 50.0 for stage in data["stages"])
    assert all(stage["completed_quantity"] == 0.0 for stage in data["stages"])
    assert all(stage["execution_percent"] == 0.0 for stage in data["stages"])


async def _tasks_for_position(session, position_id: int) -> list[WorkTask]:
    return (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == position_id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()


async def _route_steps(session, route_id: int) -> list[RouteStep]:
    return (
        await session.execute(
            select(RouteStep)
            .where(RouteStep.route_id == route_id)
            .order_by(RouteStep.sequence)
        )
    ).scalars().all()


@pytest.mark.asyncio
async def test_manual_pass_to_first_stage_creates_tasks_without_movements(client, session) -> None:
    product, route = await _make_product_with_route(session, "FG-MAN-FIRST")
    plan = await _make_plan(session, "MAN-FIRST")
    position = await _make_position(
        session,
        plan_id=plan.id,
        sku=product.sku,
        name=product.name,
        quantity=Decimal("25"),
        product_id=product.id,
    )
    position.route_id = route.id
    await session.commit()
    first_step = (await _route_steps(session, route.id))[0]

    response = await client.post(
        f"/api/production-planning/rows/{position.id}/manual-pass",
        json={"target_route_step_id": first_step.id, "idempotency_key": "manual-first"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["target_route_step_id"] == first_step.id
    assert body["tasks_created"] == 6
    assert body["movements_created"] == 0
    assert body["transfers_created"] == 0
    assert body["skipped_stages"] == 0

    tasks = await _tasks_for_position(session, position.id)
    assert len(tasks) == 6
    assert tasks[0].status == WorkTaskStatus.ready
    assert [task.status for task in tasks[1:]] == [WorkTaskStatus.waiting_previous] * 5


@pytest.mark.asyncio
async def test_manual_pass_to_middle_stage_creates_manual_facts_and_ready_target(client, session) -> None:
    await _ensure_system_user(session)
    product, route = await _make_product_with_route(session, "FG-MAN-MID")
    plan = await _make_plan(session, "MAN-MID")
    position = await _make_position(
        session,
        plan_id=plan.id,
        sku=product.sku,
        name=product.name,
        quantity=Decimal("40"),
        product_id=product.id,
    )
    position.route_id = route.id
    await session.commit()
    steps = await _route_steps(session, route.id)
    target_step = steps[2]

    response = await client.post(
        f"/api/production-planning/rows/{position.id}/manual-pass",
        json={
            "target_route_step_id": target_step.id,
            "idempotency_key": "manual-mid",
            "comment": "Пропущено по факту",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tasks_created"] == 6
    assert body["movements_created"] == 8
    assert body["transfers_created"] == 2
    assert body["skipped_stages"] == 2

    tasks = await _tasks_for_position(session, position.id)
    assert [task.status for task in tasks[:4]] == [
        WorkTaskStatus.completed,
        WorkTaskStatus.completed,
        WorkTaskStatus.ready,
        WorkTaskStatus.waiting_previous,
    ]
    assert tasks[2].cached_received_quantity == Decimal("40.000")

    movements = (
        await session.execute(
            select(Movement)
            .join(SectionPlanLine, SectionPlanLine.id == Movement.section_plan_line_id)
            .where(SectionPlanLine.plan_position_id == position.id)
            .order_by(Movement.id)
        )
    ).scalars().all()
    assert len(movements) == 8
    assert {movement.source_ref for movement in movements} == {"manual_route_pass:manual-mid"}
    assert all(movement.executor_user_id == 1 for movement in movements)
    assert all(movement.performed_at is not None and movement.accounted_at is not None for movement in movements)
    assert all(movement.comment == "Пропущено по факту" for movement in movements)

    transfers = (
        await session.execute(
            select(Transfer)
            .join(WorkTask, WorkTask.id == Transfer.from_task_id)
            .join(SectionPlanLine, SectionPlanLine.id == WorkTask.section_plan_line_id)
            .where(SectionPlanLine.plan_position_id == position.id)
            .order_by(Transfer.id)
        )
    ).scalars().all()
    assert len(transfers) == 2
    assert all((transfer.idempotency_key or "").startswith("manual_route_pass:manual-mid:") for transfer in transfers)

    detail_response = await client.get(f"/api/production-planning/rows/{position.id}")
    assert detail_response.status_code == 200
    first_stage_events = detail_response.json()["stages"][0]["flow_events"]
    assert any(event["label"] == "Ручной пропуск: выполнено" for event in first_stage_events)
    assert all(event["manual_route_pass"] is True for event in first_stage_events)


@pytest.mark.asyncio
async def test_manual_pass_replay_with_same_idempotency_key_does_not_duplicate(client, session) -> None:
    await _ensure_system_user(session)
    product, route = await _make_product_with_route(session, "FG-MAN-IDEM")
    plan = await _make_plan(session, "MAN-IDEM")
    position = await _make_position(
        session,
        plan_id=plan.id,
        sku=product.sku,
        name=product.name,
        quantity=Decimal("15"),
        product_id=product.id,
    )
    position.route_id = route.id
    await session.commit()
    target_step = (await _route_steps(session, route.id))[1]
    payload = {"target_route_step_id": target_step.id, "idempotency_key": "manual-idem"}

    first = await client.post(f"/api/production-planning/rows/{position.id}/manual-pass", json=payload)
    assert first.status_code == 200
    second = await client.post(f"/api/production-planning/rows/{position.id}/manual-pass", json=payload)
    assert second.status_code == 200

    movement_count = await session.scalar(
        select(func.count(Movement.id))
        .join(SectionPlanLine, SectionPlanLine.id == Movement.section_plan_line_id)
        .where(SectionPlanLine.plan_position_id == position.id)
    )
    transfer_count = await session.scalar(
        select(func.count(Transfer.id))
        .join(WorkTask, WorkTask.id == Transfer.from_task_id)
        .join(SectionPlanLine, SectionPlanLine.id == WorkTask.section_plan_line_id)
        .where(SectionPlanLine.plan_position_id == position.id)
    )
    assert movement_count == 4
    assert transfer_count == 1


@pytest.mark.asyncio
async def test_manual_pass_complete_route_finishes_all_tasks(client, session) -> None:
    await _ensure_system_user(session)
    product, route = await _make_product_with_route(session, "FG-MAN-FULL")
    plan = await _make_plan(session, "MAN-FULL")
    position = await _make_position(
        session,
        plan_id=plan.id,
        sku=product.sku,
        name=product.name,
        quantity=Decimal("12"),
        product_id=product.id,
    )
    position.route_id = route.id
    await session.commit()

    response = await client.post(
        f"/api/production-planning/rows/{position.id}/manual-pass",
        json={"complete_route": True, "idempotency_key": "manual-full"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["complete_route"] is True
    assert body["tasks_created"] == 6
    assert body["movements_created"] == 22
    assert body["transfers_created"] == 5
    assert body["skipped_stages"] == 6

    tasks = await _tasks_for_position(session, position.id)
    assert len(tasks) == 6
    assert all(task.status == WorkTaskStatus.completed for task in tasks)
    assert all(task.cached_completed_quantity == Decimal("12.000") for task in tasks)

    detail_response = await client.get(f"/api/production-planning/rows/{position.id}")
    assert detail_response.status_code == 200
    stages = detail_response.json()["stages"]
    assert all(stage["task_status"] == "completed" for stage in stages)
    assert all(stage["execution_percent"] == 100.0 for stage in stages)
    assert any(event["label"] == "Ручной пропуск: выполнено" for event in stages[-1]["flow_events"])


@pytest.mark.asyncio
async def test_manual_pass_rejects_position_with_existing_nonmanual_facts(client, session) -> None:
    await _ensure_system_user(session)
    product, route = await _make_product_with_route(session, "FG-MAN-BLOCK")
    plan = await _make_plan(session, "MAN-BLOCK")
    position = await _make_position(
        session,
        plan_id=plan.id,
        sku=product.sku,
        name=product.name,
        quantity=Decimal("10"),
        product_id=product.id,
    )
    position.route_id = route.id
    await session.commit()
    first_step, second_step = (await _route_steps(session, route.id))[:2]

    launch = await client.post("/api/production-planning/rows/take-to-work", json={"position_ids": [position.id]})
    assert launch.status_code == 200
    first_task = (await _tasks_for_position(session, position.id))[0]

    issue = await client.post(f"/api/shopfloor/tasks/{first_task.id}/issue", json={"quantity": "5"})
    assert issue.status_code == 200

    response = await client.post(
        f"/api/production-planning/rows/{position.id}/manual-pass",
        json={"target_route_step_id": second_step.id, "idempotency_key": "manual-block"},
    )
    assert response.status_code == 400
    assert "already has execution facts" in response.json()["detail"]
    assert first_step.id != second_step.id


@pytest.mark.asyncio
async def test_manual_pass_rejects_target_step_from_another_route(client, session) -> None:
    product, route = await _make_product_with_route(session, "FG-MAN-WRONG")
    _other_product, other_route = await _make_product_with_route(session, "FG-MAN-OTHER")
    plan = await _make_plan(session, "MAN-WRONG")
    position = await _make_position(
        session,
        plan_id=plan.id,
        sku=product.sku,
        name=product.name,
        quantity=Decimal("10"),
        product_id=product.id,
    )
    position.route_id = route.id
    await session.commit()
    wrong_step = (await _route_steps(session, other_route.id))[0]

    response = await client.post(
        f"/api/production-planning/rows/{position.id}/manual-pass",
        json={"target_route_step_id": wrong_step.id, "idempotency_key": "manual-wrong"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "target_route_step_id not found in this position route"


@pytest.mark.asyncio
async def test_rows_detail_for_position_without_route(client, session) -> None:
    plan = await _make_plan(session, "NOROUTE")
    position = await _make_position(
        session,
        plan_id=plan.id,
        sku="FG-NOROUTE",
        name="No Route",
        quantity=Decimal("10"),
        product_id=None,
        status=PlanPositionStatus.draft,
        operation_family=None,
        output_kind=None,
        has_pack_ops=None,
    )
    await session.commit()

    response = await client.get(f"/api/production-planning/rows/{position.id}")
    assert response.status_code == 200
    data = response.json()

    assert data["route_id"] is None
    assert data["route_snapshot"] is None
    assert data["stages"] == []
    assert data["route_error"] == "no_route_candidate"


@pytest.mark.asyncio
async def test_rows_list_includes_mixed_position_statuses(client, session) -> None:
    product, _ = await _make_product_with_route(session, "FG-MIX")
    plan = await _make_plan(session, "MIX")

    draft = await _make_position(
        session,
        plan_id=plan.id,
        sku="FG-MIX-DRAFT",
        name="Draft",
        quantity=Decimal("10"),
        product_id=product.id,
        status=PlanPositionStatus.draft,
        row_num=1,
    )
    approved = await _make_position(
        session,
        plan_id=plan.id,
        sku="FG-MIX-APPROVED",
        name="Approved",
        quantity=Decimal("20"),
        product_id=product.id,
        status=PlanPositionStatus.approved,
        row_num=2,
    )
    released = await _make_position(
        session,
        plan_id=plan.id,
        sku="FG-MIX-RELEASED",
        name="Released",
        quantity=Decimal("30"),
        product_id=product.id,
        status=PlanPositionStatus.released,
        row_num=3,
    )
    await session.commit()

    response = await client.get("/api/production-planning/rows")
    assert response.status_code == 200
    rows = response.json()
    rows_by_id = {row["plan_position_id"]: row for row in rows}

    # Only approved and released positions are returned by the endpoint
    assert draft.id not in rows_by_id
    assert approved.id in rows_by_id
    assert released.id in rows_by_id

    assert rows_by_id[approved.id]["position_status"] == "approved"
    assert rows_by_id[released.id]["position_status"] == "released"


@pytest.mark.asyncio
async def test_rows_list_marks_completed_if_shipment_task_completed(client, session) -> None:
    product = Product(sku="FG-SHIP-DONE", name="Shipment Done", type=ProductType.finished_good, unit="pcs")
    shipment = Section(code="SHIPMENT", name="К отгрузке", kind="finished_stock", is_active=True)
    sent = Section(code="SENT", name="Отправлено", kind="finished_stock", is_active=True)
    session.add_all([product, shipment, sent])
    await session.flush()

    route = ProductionRoute(name="Route-SHIP-DONE", is_active=True)
    session.add(route)
    await session.flush()

    session.add_all(
        [
            RouteStep(
                route_id=route.id,
                sequence=1,
                section_id=shipment.id,
                operation_code="SHIPMENT",
                operation_name="К отгрузке",
                is_final=False,
            ),
            RouteStep(
                route_id=route.id,
                sequence=2,
                section_id=sent.id,
                operation_code="SENT",
                operation_name="Отправлено",
                is_final=True,
            ),
        ]
    )
    await session.flush()

    plan = await _make_plan(session, "SHIP-DONE")
    position = await _make_position(
        session,
        plan_id=plan.id,
        sku=product.sku,
        name=product.name,
        quantity=Decimal("150"),
        product_id=product.id,
        status=PlanPositionStatus.released,
        row_num=77,
    )
    position.route_id = route.id
    await session.flush()

    internal_plan = InternalPlan(production_plan_id=plan.id)
    session.add(internal_plan)
    await session.flush()

    line_1 = SectionPlanLine(
        internal_plan_id=internal_plan.id,
        plan_position_id=position.id,
        route_id=route.id,
        route_step_id=1,
        section_id=shipment.id,
        product_id=product.id,
        sequence=1,
        planned_quantity=Decimal("150.000"),
    )
    line_2 = SectionPlanLine(
        internal_plan_id=internal_plan.id,
        plan_position_id=position.id,
        route_id=route.id,
        route_step_id=2,
        section_id=sent.id,
        product_id=product.id,
        sequence=2,
        planned_quantity=Decimal("150.000"),
    )
    session.add_all([line_1, line_2])
    await session.flush()

    task_1 = WorkTask(
        section_plan_line_id=line_1.id,
        section_id=shipment.id,
        product_id=product.id,
        route_step_id=1,
        planned_quantity=Decimal("150.000"),
        status=WorkTaskStatus.completed,
        cached_completed_quantity=Decimal("150.000"),
    )
    task_2 = WorkTask(
        section_plan_line_id=line_2.id,
        section_id=sent.id,
        product_id=product.id,
        route_step_id=2,
        planned_quantity=Decimal("150.000"),
        status=WorkTaskStatus.waiting_previous,
    )
    session.add_all([task_1, task_2])
    await session.commit()

    response = await client.get("/api/production-planning/rows")
    assert response.status_code == 200
    rows = response.json()
    row = next((item for item in rows if item["plan_position_id"] == position.id), None)
    assert row is not None
    assert row["is_completed"] is True


@pytest.mark.asyncio
async def test_rows_list_marks_completed_if_final_task_completed(client, session) -> None:
    product = Product(sku="FG-FINAL-DONE", name="Final Done", type=ProductType.finished_good, unit="pcs")
    shipment = Section(code="SHIPMENT", name="К отгрузке", kind="finished_stock", is_active=True)
    sent = Section(code="SENT", name="Отправлено", kind="finished_stock", is_active=True)
    session.add_all([product, shipment, sent])
    await session.flush()

    route = ProductionRoute(name="Route-FINAL-DONE", is_active=True)
    session.add(route)
    await session.flush()

    session.add_all(
        [
            RouteStep(
                route_id=route.id,
                sequence=1,
                section_id=shipment.id,
                operation_code="SHIPMENT",
                operation_name="К отгрузке",
                is_final=False,
            ),
            RouteStep(
                route_id=route.id,
                sequence=2,
                section_id=sent.id,
                operation_code="SENT",
                operation_name="Отправлено",
                is_final=True,
            ),
        ]
    )
    await session.flush()

    plan = await _make_plan(session, "FINAL-DONE")
    position = await _make_position(
        session,
        plan_id=plan.id,
        sku=product.sku,
        name=product.name,
        quantity=Decimal("100"),
        product_id=product.id,
        status=PlanPositionStatus.released,
        row_num=88,
    )
    position.route_id = route.id
    await session.flush()

    internal_plan = InternalPlan(production_plan_id=plan.id)
    session.add(internal_plan)
    await session.flush()

    line_1 = SectionPlanLine(
        internal_plan_id=internal_plan.id,
        plan_position_id=position.id,
        route_id=route.id,
        route_step_id=1,
        section_id=shipment.id,
        product_id=product.id,
        sequence=1,
        planned_quantity=Decimal("100.000"),
    )
    line_2 = SectionPlanLine(
        internal_plan_id=internal_plan.id,
        plan_position_id=position.id,
        route_id=route.id,
        route_step_id=2,
        section_id=sent.id,
        product_id=product.id,
        sequence=2,
        planned_quantity=Decimal("100.000"),
    )
    session.add_all([line_1, line_2])
    await session.flush()

    task_1 = WorkTask(
        section_plan_line_id=line_1.id,
        section_id=shipment.id,
        product_id=product.id,
        route_step_id=1,
        planned_quantity=Decimal("100.000"),
        status=WorkTaskStatus.partially_completed,
        cached_completed_quantity=Decimal("80.000"),
    )
    task_2 = WorkTask(
        section_plan_line_id=line_2.id,
        section_id=sent.id,
        product_id=product.id,
        route_step_id=2,
        planned_quantity=Decimal("100.000"),
        status=WorkTaskStatus.completed,
        cached_completed_quantity=Decimal("100.000"),
    )
    session.add_all([task_1, task_2])
    await session.commit()

    response = await client.get("/api/production-planning/rows")
    assert response.status_code == 200
    rows = response.json()
    row = next((item for item in rows if item["plan_position_id"] == position.id), None)
    assert row is not None
    assert row["is_completed"] is True
