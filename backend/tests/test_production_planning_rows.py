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
from app.models.route import ProductionRoute, RouteStage, RouteOperation, SectionOperation

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
    await session.flush()
    return product, route


async def _make_product_with_combined_anod_route(session, sku: str = "FG-COMBO-STAGE") -> tuple[Product, ProductionRoute]:
    product = Product(sku=sku, name=f"Finished {sku}", type=ProductType.finished_good, unit="pcs")
    sections = [
        Section(code=f"{sku}-ISSUE", name="Issue", kind="raw_stock"),
        Section(code=f"{sku}-SHOT", name="Shot", kind="production"),
        Section(code=f"{sku}-ANOD", name="Анодирование", kind="production"),
        Section(code=f"{sku}-WIP", name="WIP", kind="wip_stock"),
        Section(code=f"{sku}-FINAL", name="Final", kind="finished_stock"),
    ]
    session.add_all([product, *sections])
    await session.flush()
    session.add_all([
        SectionOperation(section_id=sections[2].id, operation_code="ANOD_05", operation_name="Чёрный"),
        SectionOperation(section_id=sections[2].id, operation_code="PACK_STRETCH", operation_name="Стрейч"),
    ])

    route = ProductionRoute(name=f"Combined Route-{sku}", is_active=True)
    session.add(route)
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(TechcardLine(techcard_id=techcard.id, component_product_id=product.id, quantity=Decimal("1"), unit="pcs"))

    stages_data = [
        (sections[0], [("ISSUE_RAW", "Issue")], False),
        (sections[1], [("SHOT", "Shot")], False),
        (sections[2], [("ANOD_05", "Чёрный"), ("PACK_STRETCH", "Стрейч")], False),
        (sections[3], [("MOVE_TO_WIP", "WIP")], False),
        (sections[4], [("ACCEPT_FINISHED", "Final")], True),
    ]
    for idx, (section, ops, is_final) in enumerate(stages_data, start=1):
        stage = RouteStage(
            route_id=route.id,
            sequence=idx,
            section_id=section.id,
            is_final=is_final,
        )
        session.add(stage)
        await session.flush()
        for op_idx, (op_code, op_name) in enumerate(ops, start=1):
            session.add(
                RouteOperation(
                    route_stage_id=stage.id,
                    sequence=op_idx,
                    operation_code=op_code,
                    operation_name=op_name,
                )
            )
    await session.flush()
    return product, route


async def _make_product_with_multi_combined_route(session, sku: str = "FG-MULTI-COMBO") -> tuple[Product, ProductionRoute]:
    """Create a route with TWO separate combined_op_group values on different sections."""
    product = Product(sku=sku, name=f"Finished {sku}", type=ProductType.finished_good, unit="pcs")
    sections = [
        Section(code=f"{sku}-ISSUE", name="Склад сырья", kind="raw_stock"),
        Section(code=f"{sku}-DRILL", name="Дробеструй", kind="production"),
        Section(code=f"{sku}-ANOD", name="Анодирование", kind="production"),
        Section(code=f"{sku}-PACK", name="Упаковка", kind="production"),
        Section(code=f"{sku}-WIP", name="Склад п/ф", kind="wip_stock"),
        Section(code=f"{sku}-FINAL", name="Склад ГП", kind="finished_stock"),
    ]
    session.add_all([product, *sections])
    await session.flush()

    # Operations for ANOD section
    session.add_all([
        SectionOperation(section_id=sections[2].id, operation_code="ANOD_BLACK", operation_name="Чёрный"),
        SectionOperation(section_id=sections[2].id, operation_code="ANOD_MATTE", operation_name="Матовый"),
    ])
    # Operations for PACK section
    session.add_all([
        SectionOperation(section_id=sections[3].id, operation_code="PACK_LABEL", operation_name="Этикетка"),
        SectionOperation(section_id=sections[3].id, operation_code="PACK_BOX", operation_name="Коробка"),
    ])

    route = ProductionRoute(name=f"Multi-Combined Route-{sku}", is_active=True)
    session.add(route)
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(TechcardLine(techcard_id=techcard.id, component_product_id=product.id, quantity=Decimal("1"), unit="pcs"))

    stages_data = [
        (sections[0], [("ISSUE_RAW", "Выдача")], False),
        (sections[1], [("DRILL", "Дробеструй")], False),
        (sections[2], [("ANOD_BLACK", "Чёрный"), ("ANOD_MATTE", "Матовый")], False),
        (sections[3], [("PACK_LABEL", "Этикетка"), ("PACK_BOX", "Коробка")], False),
        (sections[4], [("MOVE_TO_WIP", "Склад п/ф")], False),
        (sections[5], [("ACCEPT_FINISHED", "Склад ГП")], True),
    ]
    for idx, (section, ops, is_final) in enumerate(stages_data, start=1):
        stage = RouteStage(
            route_id=route.id,
            sequence=idx,
            section_id=section.id,
            is_final=is_final,
        )
        session.add(stage)
        await session.flush()
        for op_idx, (op_code, op_name) in enumerate(ops, start=1):
            session.add(
                RouteOperation(
                    route_stage_id=stage.id,
                    sequence=op_idx,
                    operation_code=op_code,
                    operation_name=op_name,
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
    from sqlalchemy import select
    existing = await session.scalar(select(User).where(User.email == "system@local"))
    if existing:
        return existing
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
        has_pack_ops=has_pack_ops,
    )
    session.add(position)
    await session.flush()
    return position


@pytest.mark.asyncio
async def test_rows_detail_merges_combined_anod_stages_before_release(client, session) -> None:
    product, route = await _make_product_with_combined_anod_route(session)
    plan = await _make_plan(session, "COMBO-STAGE")
    position = await _make_position(
        session,
        plan_id=plan.id,
        sku=product.sku,
        name=product.name,
        quantity=Decimal("1020"),
        product_id=product.id,
    )
    position.route_id = route.id
    position.source_payload = {"color": "черный"}
    await session.commit()

    response = await client.get(f"/api/production-planning/rows/{position.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["not_started"] is True
    assert len(data["route_snapshot"]["steps"]) == 5
    assert len(data["stages"]) == 5
    assert [stage["section_name"] for stage in data["stages"]].count("Анодирование") == 1
    anod_stage = next(stage for stage in data["stages"] if stage["section_name"] == "Анодирование")
    assert anod_stage["sequence"] == 3
    assert anod_stage["planned_quantity"] == 1020.0
    assert anod_stage["operation_code"] == "ANOD_05"
    assert anod_stage["operation_name"] == "Чёрный / Стрейч"


@pytest.mark.asyncio
async def test_rows_list_merges_combined_anod_route_steps(client, session) -> None:
    product, route = await _make_product_with_combined_anod_route(session, "FG-COMBO-LIST")
    plan = await _make_plan(session, "COMBO-LIST")
    position = await _make_position(
        session,
        plan_id=plan.id,
        sku=product.sku,
        name=product.name,
        quantity=Decimal("1020"),
        product_id=product.id,
        row_num=6,
    )
    position.route_id = route.id
    await session.commit()

    response = await client.get("/api/production-planning/rows")

    assert response.status_code == 200
    row = next(item for item in response.json() if item["plan_position_id"] == position.id)
    route_steps = row["route_steps"]
    assert len(route_steps) == 5
    stages = await _route_stages(session, route.id)
    anod_section_id = next(stage.section_id for stage in stages if len(stage.operations) > 1)
    assert [step["section_id"] for step in route_steps].count(anod_section_id) == 1
    assert [step["sequence"] for step in route_steps] == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_rows_list_and_detail_merge_multiple_combined_groups(client, session) -> None:
    """Route has TWO separate combined_op_group values — both must be merged independently."""
    product, route = await _make_product_with_multi_combined_route(session, "FG-MULTI-COMBO")
    plan = await _make_plan(session, "MULTI-COMBO")
    position = await _make_position(
        session,
        plan_id=plan.id,
        sku=product.sku,
        name=product.name,
        quantity=Decimal("500"),
        product_id=product.id,
        row_num=10,
    )
    position.route_id = route.id
    position.source_payload = {"color": "черный матовый"}
    await session.commit()

    # Check list endpoint
    response = await client.get("/api/production-planning/rows")
    assert response.status_code == 200
    row = next(item for item in response.json() if item["plan_position_id"] == position.id)
    route_steps = row["route_steps"]

    # Route has 8 raw steps, but after grouping should be 6:
    # 1. Выдача, 2. Дробеструй, 3. Анодирование(merged 2), 4. Упаковка(merged 2), 5. Склад п/ф, 6. Склад ГП
    assert len(route_steps) == 6, f"Expected 6 grouped route_steps, got {len(route_steps)}: {[s['sequence'] for s in route_steps]}"

    # Check sequences are preserved (merged steps keep first sequence of group)
    assert [step["sequence"] for step in route_steps] == [1, 2, 3, 4, 5, 6]

    # Check detail endpoint
    response = await client.get(f"/api/production-planning/rows/{position.id}")
    assert response.status_code == 200
    data = response.json()

    assert len(data["stages"]) == 6, f"Expected 6 stages, got {len(data['stages'])}"
    assert len(data["route_snapshot"]["steps"]) == 6

    # Each combined section appears exactly once
    stage_names = [stage["section_name"] for stage in data["stages"]]
    assert stage_names.count("Анодирование") == 1, f"Анодирование appears {stage_names.count('Анодирование')} times"
    assert stage_names.count("Упаковка") == 1, f"Упаковка appears {stage_names.count('Упаковка')} times"

    # Check merged operation names
    # First step has explicit operation_code="ANOD_BLACK" → "Чёрный"
    # Second step has operation_code="ANOD_MATTE" → "Матовый"
    anod_stage = next(s for s in data["stages"] if s["section_name"] == "Анодирование")
    assert anod_stage["sequence"] == 3
    assert anod_stage["operation_name"] == "Чёрный / Матовый"
    assert anod_stage["planned_quantity"] == 500.0

    pack_stage = next(s for s in data["stages"] if s["section_name"] == "Упаковка")
    assert pack_stage["sequence"] == 4
    assert pack_stage["operation_name"] == "Этикетка / Коробка"
    assert pack_stage["planned_quantity"] == 500.0


@pytest.mark.asyncio
async def test_rows_detail_has_press_operation_from_route_step(client, session) -> None:
    """PRESS route step has explicit operation_code from route_select rules."""
    product = Product(sku="FG-PRESS-TEST", name="Press Test", type=ProductType.finished_good, unit="pcs")
    sections = [
        Section(code="PRESS-RAW", name="Склад сырья", kind="raw_stock"),
        Section(code="PRESS", name="Пресс", kind="production"),
        Section(code="PRESS-FG", name="Склад ГП", kind="finished_stock"),
    ]
    session.add_all([product, *sections])
    await session.flush()

    session.add_all([
        SectionOperation(section_id=sections[1].id, operation_code="PRESS_WINDOW", operation_name="Пресс окно"),
        SectionOperation(section_id=sections[1].id, operation_code="PRESS_COMB", operation_name="Пресс комб"),
    ])

    route = ProductionRoute(name="Press Route", is_active=True)
    session.add(route)
    await session.flush()

    stages_data = [
        (sections[0], [("ISSUE_RAW", "Выдача сырья")], False),
        (sections[1], [("PRESS_WINDOW", "Пресс окно")], False),
        (sections[2], [("ACCEPT_FINISHED", "Склад ГП")], True),
    ]
    for idx, (section, ops, is_final) in enumerate(stages_data, start=1):
        stage = RouteStage(
            route_id=route.id,
            sequence=idx,
            section_id=section.id,
            is_final=is_final,
        )
        session.add(stage)
        await session.flush()
        for op_idx, (op_code, op_name) in enumerate(ops, start=1):
            session.add(
                RouteOperation(
                    route_stage_id=stage.id,
                    sequence=op_idx,
                    operation_code=op_code,
                    operation_name=op_name,
                )
            )
    await session.flush()

    plan = await _make_plan(session, "PRESS-TEST")
    position = await _make_position(
        session,
        plan_id=plan.id,
        sku=product.sku,
        name=product.name,
        quantity=Decimal("200"),
        product_id=product.id,
    )
    position.route_id = route.id

    # source_payload contains PRESS_WINDOW from Excel normalization
    position.source_payload = {"operation_code": "PRESS_WINDOW", "operation_name": "Пресс окно"}
    await session.commit()

    response = await client.get(f"/api/production-planning/rows/{position.id}")
    assert response.status_code == 200
    data = response.json()

    # Check that PRESS operation_code is PRESS_WINDOW (from route_select rules)
    press_stage = next(s for s in data["stages"] if s["section_name"] == "Пресс")
    assert press_stage["operation_code"] == "PRESS_WINDOW"
    assert press_stage["planned_quantity"] == 200.0


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


async def _route_stages(session, route_id: int) -> list[RouteStage]:
    return (
        await session.execute(
            select(RouteStage)
            .where(RouteStage.route_id == route_id)
            .order_by(RouteStage.sequence)
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
    first_stage = (await _route_stages(session, route.id))[0]

    response = await client.post(
        f"/api/production-planning/rows/{position.id}/manual-pass",
        json={"target_route_stage_id": first_stage.id, "idempotency_key": "manual-first"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["target_route_stage_id"] == first_stage.id
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
    stages = await _route_stages(session, route.id)
    target_stage = stages[2]

    response = await client.post(
        f"/api/production-planning/rows/{position.id}/manual-pass",
        json={
            "target_route_stage_id": target_stage.id,
            "idempotency_key": "manual-mid",
            "comment": "Пропущено по факту",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tasks_created"] == 6
    assert body["movements_created"] == 10
    assert body["transfers_created"] == 2
    assert body["skipped_stages"] == 2

    tasks = await _tasks_for_position(session, position.id)
    assert [task.status for task in tasks[:4]] == [
        WorkTaskStatus.completed,
        WorkTaskStatus.completed,
        WorkTaskStatus.in_progress,
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
    assert len(movements) == 10
    assert {movement.source_ref for movement in movements} == {"manual_route_pass:manual-mid"}
    assert all(movement.executor_user_id == 1 for movement in movements)
    assert all(movement.performed_at is not None and movement.accounted_at is not None for movement in movements)
    manual_movements = [m for m in movements if not (m.comment and m.comment.startswith("Auto-issued on transfer receive"))]
    assert len(manual_movements) == 8
    assert all(m.comment == "Пропущено по факту" for m in manual_movements)

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
    target_stage = (await _route_stages(session, route.id))[1]
    payload = {"target_route_stage_id": target_stage.id, "idempotency_key": "manual-idem"}

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
    assert movement_count == 5
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
    assert body["movements_created"] == 27
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
    first_stage, second_stage = (await _route_stages(session, route.id))[:2]

    launch = await client.post("/api/production-planning/rows/take-to-work", json={"position_ids": [position.id]})
    assert launch.status_code == 200
    first_task = (await _tasks_for_position(session, position.id))[0]

    issue = await client.post(f"/api/shopfloor/tasks/{first_task.id}/issue", json={"quantity": "5"})
    assert issue.status_code == 200

    response = await client.post(
        f"/api/production-planning/rows/{position.id}/manual-pass",
        json={"target_route_stage_id": second_stage.id, "idempotency_key": "manual-block"},
    )
    assert response.status_code == 400
    assert "already has execution facts" in response.json()["detail"]
    assert first_stage.id != second_stage.id


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
    wrong_stage = (await _route_stages(session, other_route.id))[0]

    response = await client.post(
        f"/api/production-planning/rows/{position.id}/manual-pass",
        json={"target_route_stage_id": wrong_stage.id, "idempotency_key": "manual-wrong"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "target_route_stage_id not found in this position route"


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

    stage_ship = RouteStage(
        route_id=route.id,
        sequence=1,
        section_id=shipment.id,
        is_final=False,
    )
    session.add(stage_ship)
    await session.flush()
    session.add(
        RouteOperation(
            route_stage_id=stage_ship.id,
            sequence=1,
            operation_code="SHIPMENT",
            operation_name="К отгрузке",
        )
    )

    stage_sent = RouteStage(
        route_id=route.id,
        sequence=2,
        section_id=sent.id,
        is_final=True,
    )
    session.add(stage_sent)
    await session.flush()
    session.add(
        RouteOperation(
            route_stage_id=stage_sent.id,
            sequence=1,
            operation_code="SENT",
            operation_name="Отправлено",
        )
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
        route_stage_id=stage_ship.id,
        section_id=shipment.id,
        product_id=product.id,
        sequence=1,
        planned_quantity=Decimal("150.000"),
    )
    line_2 = SectionPlanLine(
        internal_plan_id=internal_plan.id,
        plan_position_id=position.id,
        route_id=route.id,
        route_stage_id=stage_sent.id,
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
        route_stage_id=stage_ship.id,
        planned_quantity=Decimal("150.000"),
        status=WorkTaskStatus.completed,
        cached_completed_quantity=Decimal("150.000"),
    )
    task_2 = WorkTask(
        section_plan_line_id=line_2.id,
        section_id=sent.id,
        product_id=product.id,
        route_stage_id=stage_sent.id,
        planned_quantity=Decimal("150.000"),
        status=WorkTaskStatus.completed,
        cached_completed_quantity=Decimal("150.000"),
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

    stage_ship = RouteStage(
        route_id=route.id,
        sequence=1,
        section_id=shipment.id,
        is_final=False,
    )
    stage_sent = RouteStage(
        route_id=route.id,
        sequence=2,
        section_id=sent.id,
        is_final=True,
    )
    session.add_all([stage_ship, stage_sent])
    await session.flush()

    session.add_all(
        [
            RouteOperation(
                route_stage_id=stage_ship.id,
                sequence=1,
                operation_code="SHIPMENT",
                operation_name="К отгрузке",
            ),
            RouteOperation(
                route_stage_id=stage_sent.id,
                sequence=1,
                operation_code="SENT",
                operation_name="Отправлено",
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
        route_stage_id=stage_ship.id,
        section_id=shipment.id,
        product_id=product.id,
        sequence=1,
        planned_quantity=Decimal("100.000"),
    )
    line_2 = SectionPlanLine(
        internal_plan_id=internal_plan.id,
        plan_position_id=position.id,
        route_id=route.id,
        route_stage_id=stage_sent.id,
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
        route_stage_id=stage_ship.id,
        planned_quantity=Decimal("100.000"),
        status=WorkTaskStatus.partially_completed,
        cached_completed_quantity=Decimal("80.000"),
    )
    task_2 = WorkTask(
        section_plan_line_id=line_2.id,
        section_id=sent.id,
        product_id=product.id,
        route_stage_id=stage_sent.id,
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


async def test_get_product_wip_stats(client, session):
    from app.models.spg import StorageProductionGroup
    from app.models.spg_remainder import SpgRemainder

    # 1. Создаем продукт с маршрутом
    sku = "TEST-WIP-SKU-1"
    product, route = await _make_product_with_route(session, sku=sku)

    # Получаем этапы и секции
    stages = (
        await session.execute(
            select(RouteStage).where(RouteStage.route_id == route.id).order_by(RouteStage.sequence)
        )
    ).scalars().all()
    stage = stages[1]  # Второй этап (DRILL)
    section_id = stage.section_id

    # 2. Создаем СПГ и остаток
    spg = StorageProductionGroup(code="TEST-SPG-1", name="Test SPG Warehouse", is_active=True)
    session.add(spg)
    await session.flush()

    remainder = SpgRemainder(
        spg_id=spg.id,
        product_id=product.id,
        remainder_quantity=Decimal("15.5"),
        original_issued=Decimal("15.5"),
    )
    session.add(remainder)
    await session.flush()

    # 3. Создаем план, позицию плана, внутренний план, строку плана и активную задачу
    plan = ProductionPlan(plan_no="PLAN-TEST-WIP", name="Plan Test WIP", status=ProductionPlanStatus.draft, period_start=date(2026, 6, 1))
    session.add(plan)
    await session.flush()

    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_sku=sku,
        source_name=product.name,
        quantity=Decimal("100"),
        status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid,
        source_type=PlanSourceType.manual,
    )
    session.add(position)
    await session.flush()

    internal_plan = InternalPlan(production_plan_id=plan.id)
    session.add(internal_plan)
    await session.flush()

    line = SectionPlanLine(
        internal_plan_id=internal_plan.id,
        plan_position_id=position.id,
        section_id=section_id,
        product_id=product.id,
        route_id=route.id,
        route_stage_id=stage.id,
        sequence=1,
        planned_quantity=Decimal("100"),
    )
    session.add(line)
    await session.flush()

    task = WorkTask(
        section_plan_line_id=line.id,
        section_id=section_id,
        product_id=product.id,
        route_stage_id=stage.id,
        planned_quantity=Decimal("100"),
        status=WorkTaskStatus.in_progress,
        cached_completed_quantity=Decimal("20"),
        cached_in_work_quantity=Decimal("80"),
    )
    session.add(task)
    await session.commit()

    # 4. Запрос к эндпоинту статистики
    response = await client.get(f"/api/production-planning/product-wip-stats/{sku}")
    assert response.status_code == 200
    data = response.json()

    assert data["sku"] == sku
    assert data["product_name"] == product.name
    assert data["product_id"] == product.id

    # Проверяем остатки
    assert len(data["remainders"]) == 1
    rem = data["remainders"][0]
    assert rem["spg_id"] == spg.id
    assert rem["spg_code"] == "TEST-SPG-1"
    assert rem["spg_name"] == "Test SPG Warehouse"
    assert rem["quantity"] == 15.5

    # Проверяем задачи в работе
    assert len(data["in_work"]) == 1
    work = data["in_work"][0]
    assert work["section_id"] == section_id
    assert work["planned_qty"] == 100.0
    assert work["completed_qty"] == 20.0
    assert work["in_work_qty"] == 80.0
    assert work["active_tasks_count"] == 1

    # 5. Запрос по несуществующему SKU
    response_404 = await client.get("/api/production-planning/product-wip-stats/NON-EXISTENT-SKU")
    assert response_404.status_code == 404
