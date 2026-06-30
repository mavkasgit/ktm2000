"""Tests for the take-to-work endpoint."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

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
from app.models.internal_plan import SectionPlanLine


async def _make_user(session, email: str = "operator@test.local") -> User:
    user = User(email=email, password_hash="x", full_name="Operator", role=UserRole.operator, is_active=True)
    session.add(user)
    await session.flush()
    return user


async def _make_product_route_plan(session, sku: str = "FG-TTW") -> tuple[Product, ProductionPlan, PlanPosition]:
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
    # Assign route to position so take-to-work resolves it
    pos.route_id = route.id
    await session.commit()
    return product, plan, pos


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.email)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_take_to_work_single_success(client, session) -> None:
    """Single approved position with valid route → tasks created for all stages."""
    user = await _make_user(session, "ttw-single@test.local")
    _, plan, pos = await _make_product_route_plan(session, "FG-TTW-SINGLE")
    headers = _auth_headers(user)

    res = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [pos.id]},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data["results"]) == 1
    result = data["results"][0]
    assert result["position_id"] == pos.id
    assert result["status"] == "success"
    assert result["release_batch_id"] is not None
    assert result["internal_plan_id"] is not None
    assert result["tasks_created"] == 6  # 6 sections

    # Verify tasks were created with correct statuses
    tasks = (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == pos.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()
    assert len(tasks) == 6
    assert tasks[0].status == WorkTaskStatus.ready
    assert tasks[1].status == WorkTaskStatus.waiting_previous
    assert tasks[2].status == WorkTaskStatus.waiting_previous


@pytest.mark.asyncio
async def test_take_to_work_already_started(client, session) -> None:
    """Re-running take-to-work on already released position → already_started."""
    user = await _make_user(session, "ttw-already@test.local")
    _, plan, pos = await _make_product_route_plan(session, "FG-TTW-ALREADY")
    headers = _auth_headers(user)

    # First call — success
    res1 = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [pos.id]},
        headers=headers,
    )
    assert res1.status_code == 200
    assert res1.json()["results"][0]["status"] == "success"

    # Second call — already_started
    res2 = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [pos.id]},
        headers=headers,
    )
    assert res2.status_code == 200
    result = res2.json()["results"][0]
    assert result["status"] == "already_started"
    assert "already has tasks" in result["reason"]

    # Verify no duplicate tasks
    task_count = await session.scalar(
        select(func.count(WorkTask.id))
        .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
        .where(SectionPlanLine.plan_position_id == pos.id)
    )
    assert task_count == 6  # Still only 6, not 12


@pytest.mark.asyncio
async def test_take_to_work_bulk_partial(client, session) -> None:
    """Mixed set of positions: some valid, some already started, some with no route."""
    user = await _make_user(session, "ttw-bulk@test.local")
    headers = _auth_headers(user)

    # Valid position
    _, plan1, pos1 = await _make_product_route_plan(session, "FG-TTW-BULK1")

    # Position with no route (no product-route setup)
    product2 = Product(sku="FG-TTW-NOROUTE", name="No Route Product", type=ProductType.finished_good, unit="pcs")
    plan2 = ProductionPlan(
        plan_no="PLAN-TTW-NOROUTE",
        name="No Route Plan",
        status=ProductionPlanStatus.approved,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add_all([product2, plan2])
    await session.flush()
    pos2 = PlanPosition(
        production_plan_id=plan2.id,
        product_id=product2.id,
        source_type=PlanSourceType.manual,
        source_sku=product2.sku,
        source_name=product2.name,
        quantity=Decimal("50"),
        source_payload={},
        status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        period_start=plan2.period_start,
        period_end=plan2.period_end,
    )
    session.add(pos2)
    await session.commit()

    # Bulk call
    res = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [pos1.id, pos2.id]},
        headers=headers,
    )
    assert res.status_code == 200
    results = res.json()["results"]
    assert len(results) == 2

    # pos1 should succeed
    assert results[0]["position_id"] == pos1.id
    assert results[0]["status"] == "success"

    # pos2 should fail (invalid launch prerequisites)
    assert results[1]["position_id"] == pos2.id
    assert results[1]["status"] == "failed"
    assert results[1]["reason"]


@pytest.mark.asyncio
async def test_take_to_work_forbidden_statuses(client, session) -> None:
    """Positions with draft/invalid/released status should fail."""
    user = await _make_user(session, "ttw-status@test.local")
    headers = _auth_headers(user)

    # Create a position with draft status
    product = Product(sku="FG-TTW-DRAFT", name="Draft Product", type=ProductType.finished_good, unit="pcs")
    plan = ProductionPlan(
        plan_no="PLAN-TTW-DRAFT",
        name="Draft Plan",
        status=ProductionPlanStatus.approved,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add_all([product, plan])
    await session.flush()
    pos_draft = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("10"),
        source_payload={},
        status=PlanPositionStatus.draft,  # Not approved
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        period_start=plan.period_start,
        period_end=plan.period_end,
    )
    session.add(pos_draft)
    await session.commit()

    res = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [pos_draft.id]},
        headers=headers,
    )
    assert res.status_code == 200
    result = res.json()["results"][0]
    assert result["status"] == "failed"
    assert "approved" in result["reason"].lower()


@pytest.mark.asyncio
async def test_take_to_work_nonexistent_position(client, session) -> None:
    """Non-existent position ID should return failed."""
    user = await _make_user(session, "ttw-nofile@test.local")
    headers = _auth_headers(user)

    res = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [999999]},
        headers=headers,
    )
    assert res.status_code == 200
    result = res.json()["results"][0]
    assert result["status"] == "failed"
    assert "not found" in result["reason"].lower()


@pytest.mark.asyncio
async def test_take_to_work_empty_request(client, session) -> None:
    """Empty position_ids list should return empty results."""
    user = await _make_user(session, "ttw-empty@test.local")
    headers = _auth_headers(user)

    res = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": []},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["results"] == []


@pytest.mark.asyncio
async def test_take_to_work_rejects_extra_fields(client, session) -> None:
    """Contract: endpoint accepts only position_ids."""
    user = await _make_user(session, "ttw-contract@test.local")
    headers = _auth_headers(user)

    res = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [], "idempotency_key": "legacy-field"},
        headers=headers,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_cancel_batch_success_and_repeat_skips(client, session) -> None:
    user = await _make_user(session, "cancel-batch@test.local")
    _, _, pos = await _make_product_route_plan(session, "FG-CANCEL-BATCH")
    headers = _auth_headers(user)

    res = await client.post(
        "/api/production-planning/rows/cancel-batch",
        json={"position_ids": [pos.id], "reason": "batch stop"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["results"] == [{"position_id": pos.id, "status": "success", "reason": None}]
    await session.refresh(pos)
    assert pos.status == PlanPositionStatus.cancelled

    repeat = await client.post(
        "/api/production-planning/rows/cancel-batch",
        json={"position_ids": [pos.id]},
        headers=headers,
    )
    assert repeat.status_code == 200
    assert repeat.json()["results"][0]["status"] == "skipped"
    assert "already cancelled" in repeat.json()["results"][0]["reason"]


@pytest.mark.asyncio
async def test_cancel_batch_mixed_invalid_and_not_found(client, session) -> None:
    user = await _make_user(session, "cancel-batch-mixed@test.local")
    _, _, approved_pos = await _make_product_route_plan(session, "FG-CANCEL-MIXED")

    product = Product(sku="FG-CANCEL-DRAFT", name="Draft Product", type=ProductType.finished_good, unit="pcs")
    plan = ProductionPlan(
        plan_no="PLAN-CANCEL-DRAFT",
        name="Draft Plan",
        status=ProductionPlanStatus.approved,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add_all([product, plan])
    await session.flush()
    draft_pos = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("5"),
        source_payload={},
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        period_start=plan.period_start,
        period_end=plan.period_end,
    )
    session.add(draft_pos)
    await session.commit()

    res = await client.post(
        "/api/production-planning/rows/cancel-batch",
        json={"position_ids": [approved_pos.id, draft_pos.id, 999999]},
        headers=_auth_headers(user),
    )
    assert res.status_code == 200
    results = res.json()["results"]
    assert [item["status"] for item in results] == ["success", "failed", "failed"]
    assert "draft" in results[1]["reason"]
    assert "not found" in results[2]["reason"].lower()


@pytest.mark.asyncio
async def test_restore_batch_success_and_repeat_skips(client, session) -> None:
    user = await _make_user(session, "restore-batch@test.local")
    _, _, pos = await _make_product_route_plan(session, "FG-RESTORE-BATCH")
    headers = _auth_headers(user)

    cancel = await client.post(
        "/api/production-planning/rows/cancel-batch",
        json={"position_ids": [pos.id], "reason": "pause"},
        headers=headers,
    )
    assert cancel.status_code == 200
    assert cancel.json()["results"][0]["status"] == "success"

    restore = await client.post(
        "/api/production-planning/rows/restore-batch",
        json={"position_ids": [pos.id], "reason": "resume"},
        headers=headers,
    )
    assert restore.status_code == 200
    assert restore.json()["results"] == [{"position_id": pos.id, "status": "success", "reason": None}]
    await session.refresh(pos)
    assert pos.status == PlanPositionStatus.approved

    repeat = await client.post(
        "/api/production-planning/rows/restore-batch",
        json={"position_ids": [pos.id]},
        headers=headers,
    )
    assert repeat.status_code == 200
    assert repeat.json()["results"][0]["status"] == "skipped"
    assert "already active" in repeat.json()["results"][0]["reason"]


@pytest.mark.asyncio
async def test_restore_batch_invalid_status_and_not_found(client, session) -> None:
    user = await _make_user(session, "restore-batch-invalid@test.local")
    _, _, approved_pos = await _make_product_route_plan(session, "FG-RESTORE-INVALID")
    product = Product(sku="FG-RESTORE-DRAFT", name="Draft Product", type=ProductType.finished_good, unit="pcs")
    plan = ProductionPlan(
        plan_no="PLAN-RESTORE-DRAFT",
        name="Draft Plan",
        status=ProductionPlanStatus.approved,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add_all([product, plan])
    await session.flush()
    draft_pos = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("5"),
        source_payload={},
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        period_start=plan.period_start,
        period_end=plan.period_end,
    )
    session.add(draft_pos)
    await session.commit()

    res = await client.post(
        "/api/production-planning/rows/restore-batch",
        json={"position_ids": [approved_pos.id, draft_pos.id, 999999]},
        headers=_auth_headers(user),
    )
    assert res.status_code == 200
    results = res.json()["results"]
    assert [item["status"] for item in results] == ["skipped", "failed", "failed"]
    assert "already active" in results[0]["reason"]
    assert "draft" in results[1]["reason"]
    assert "not found" in results[2]["reason"].lower()


@pytest.mark.asyncio
async def test_take_to_work_auto_transfer_remainders(client, session) -> None:
    """Take to work with compatible remainder on a different SPG.
    
    Checks that the task covered by remainder is completed,
    the next task is waiting_previous, and an automatic transfer is sent.
    """
    from app.models.spg import StorageProductionGroup, SpgSection
    from app.models.spg_remainder import SpgRemainder
    from app.models.transfer import Transfer, TransferStatus
    
    user = await _make_user(session, "ttw-remainder@test.local")
    product, plan, pos = await _make_product_route_plan(session, "FG-TTW-REM")
    
    # Resolve sections from route
    stages = (await session.execute(
        select(RouteStage).where(RouteStage.route_id == pos.route_id).order_by(RouteStage.sequence)
    )).scalars().all()
    assert len(stages) == 6
    
    # Let's bind stage 0 (Issue) to SPG_STOCK, stage 1 (Drill) to SPG_PREP, stage 3 (Anod) to SPG_ANOD
    spg_stock = StorageProductionGroup(code="SPG-STOCK", name="Stock GHP", is_active=True)
    spg_prep = StorageProductionGroup(code="SPG-PREP", name="Prep GHP", is_active=True)
    spg_anod = StorageProductionGroup(code="SPG-ANOD", name="Anod GHP", is_active=True)
    session.add_all([spg_stock, spg_prep, spg_anod])
    await session.flush()
    
    session.add(SpgSection(spg_id=spg_stock.id, section_id=stages[0].section_id, sort_order=0))
    session.add(SpgSection(spg_id=spg_prep.id, section_id=stages[1].section_id, sort_order=0))
    session.add(SpgSection(spg_id=spg_prep.id, section_id=stages[2].section_id, sort_order=10))
    session.add(SpgSection(spg_id=spg_anod.id, section_id=stages[3].section_id, sort_order=0))
    await session.flush()
    
    # Create a compatible remainder that has completed stages up to sequence 3 (Shot)
    completed_stages_1 = [
        {
            "sequence": stages[0].sequence,
            "section_id": stages[0].section_id,
            "operation_code": "ISSUE_RAW",
            "operation_name": "ISSUE_RAW",
        },
        {
            "sequence": stages[1].sequence,
            "section_id": stages[1].section_id,
            "operation_code": "DRILL",
            "operation_name": "DRILL",
        },
        {
            "sequence": stages[2].sequence,
            "section_id": stages[2].section_id,
            "operation_code": "SHOT",
            "operation_name": "SHOT",
        }
    ]
    
    rem1 = SpgRemainder(
        product_id=product.id,
        spg_id=spg_prep.id,
        route_stage_id=stages[2].id,
        remainder_quantity=Decimal("150"), # covers the whole pos.quantity (100)
        original_issued=Decimal("150"),
        completed_stages_json=completed_stages_1,
        created_by=user.id,
        created_by_user_name=user.full_name,
    )

    # Create another compatible remainder that has completed stages up to sequence 1 (Issue)
    completed_stages_2 = [
        {
            "sequence": stages[0].sequence,
            "section_id": stages[0].section_id,
            "operation_code": "ISSUE_RAW",
            "operation_name": "ISSUE_RAW",
        }
    ]
    rem2 = SpgRemainder(
        product_id=product.id,
        spg_id=spg_stock.id,
        route_stage_id=stages[0].id,
        remainder_quantity=Decimal("200"),
        original_issued=Decimal("200"),
        completed_stages_json=completed_stages_2,
        created_by=user.id,
        created_by_user_name=user.full_name,
    )
    session.add_all([rem1, rem2])
    await session.commit()
    
    headers = _auth_headers(user)
    res = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [pos.id]},
        headers=headers,
    )
    assert res.status_code == 200
    
    # Verify tasks and statuses
    tasks = (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == pos.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()
    
    # 6 stages, first 3 covered by remainders (planned_qty = 0)
    assert len(tasks) == 6
    assert tasks[0].status == WorkTaskStatus.completed  # Issue
    assert tasks[1].status == WorkTaskStatus.completed  # Drill
    assert tasks[2].status == WorkTaskStatus.completed  # Shot
    assert tasks[3].status == WorkTaskStatus.waiting_previous  # Anod (waiting transfer from Shot!)
    assert tasks[4].status == WorkTaskStatus.waiting_previous  # WIP
    assert tasks[5].status == WorkTaskStatus.waiting_previous  # Final
    
    # Check that transfer 1 (Shot -> Anod) was automatically sent
    transfer1 = await session.scalar(
        select(Transfer).where(
            Transfer.from_task_id == tasks[2].id,
            Transfer.to_task_id == tasks[3].id
        )
    )
    assert transfer1 is not None
    assert transfer1.status == TransferStatus.sent
    assert transfer1.sent_quantity == Decimal("100")

    # Check that transfer 2 (Issue -> Drill) was automatically sent
    transfer2 = await session.scalar(
        select(Transfer).where(
            Transfer.from_task_id == tasks[0].id,
            Transfer.to_task_id == tasks[1].id
        )
    )
    assert transfer2 is not None
    assert transfer2.status == TransferStatus.sent
    assert transfer2.sent_quantity == Decimal("100")


@pytest.mark.asyncio
async def test_take_to_work_restore_remainders_on_cancel_and_delete(client, session) -> None:
    """Take to work, accept transfer (consuming remainder), then delete plan batch.
    
    Checks that the remainder quantity is restored and reservation is cleared.
    """
    from app.models.spg import StorageProductionGroup, SpgSection
    from app.models.spg_remainder import SpgRemainder
    from app.models.transfer import Transfer, TransferStatus
    from app.models.imports import ImportBatch, ImportBatchMode, ImportFile
    from app.transfers.services import transfer_receive
    
    user = await _make_user(session, "ttw-del-rem@test.local")
    product, plan, pos = await _make_product_route_plan(session, "FG-TTW-DEL-REM")
    
    # Create ImportFile and ImportBatch
    file = ImportFile(
        original_filename="test.xlsx",
        file_extension="xlsx",
        detected_format="excel",
        file_sha256="some-sha256-hash",
        size_bytes=1024,
    )
    session.add(file)
    await session.flush()

    batch = ImportBatch(
        source_file_id=file.id,
        production_plan_id=plan.id,
        mode=ImportBatchMode.create_plan,
        sheet_name="Sheet1",
        header_row_number=1,
        total_rows=1,
        parsed_rows=1,
        summary={},
    )
    session.add(batch)
    await session.flush()
    pos.import_batch_id = batch.id
    await session.flush()
    
    # Resolve sections from route
    stages = (await session.execute(
        select(RouteStage).where(RouteStage.route_id == pos.route_id).order_by(RouteStage.sequence)
    )).scalars().all()
    assert len(stages) == 6
    
    spg_prep = StorageProductionGroup(code="SPG-DEL-PREP", name="Prep GHP", is_active=True)
    spg_anod = StorageProductionGroup(code="SPG-DEL-ANOD", name="Anod GHP", is_active=True)
    session.add_all([spg_prep, spg_anod])
    await session.flush()
    
    session.add(SpgSection(spg_id=spg_prep.id, section_id=stages[1].section_id, sort_order=0))
    session.add(SpgSection(spg_id=spg_prep.id, section_id=stages[2].section_id, sort_order=10))
    session.add(SpgSection(spg_id=spg_anod.id, section_id=stages[3].section_id, sort_order=0))
    await session.flush()
    
    completed_stages = [
        {
            "sequence": stages[0].sequence,
            "section_id": stages[0].section_id,
            "operation_code": "ISSUE_RAW",
            "operation_name": "ISSUE_RAW",
        },
        {
            "sequence": stages[1].sequence,
            "section_id": stages[1].section_id,
            "operation_code": "DRILL",
            "operation_name": "DRILL",
        },
        {
            "sequence": stages[2].sequence,
            "section_id": stages[2].section_id,
            "operation_code": "SHOT",
            "operation_name": "SHOT",
        }
    ]
    
    rem = SpgRemainder(
        product_id=product.id,
        spg_id=spg_prep.id,
        route_stage_id=stages[2].id,
        remainder_quantity=Decimal("150"),
        original_issued=Decimal("150"),
        completed_stages_json=completed_stages,
        created_by=user.id,
        created_by_user_name=user.full_name,
    )
    session.add(rem)
    await session.commit()
    
    headers = _auth_headers(user)
    res = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [pos.id]},
        headers=headers,
    )
    assert res.status_code == 200
    
    # Get tasks
    tasks = (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == pos.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()
    
    # Check that transfer was automatically sent
    transfer = await session.scalar(
        select(Transfer).where(
            Transfer.from_task_id == tasks[2].id,
            Transfer.to_task_id == tasks[3].id
        )
    )
    assert transfer is not None
    
    # First accept the transfer -> this flips tasks[3] status from waiting_previous to ready
    await transfer_receive(
        session,
        transfer_id=transfer.id,
        accepted_quantity=Decimal("100"),
        rejected_quantity=Decimal("0"),
        actor_id=user.id,
    )
    await session.commit()

    # Now that the task status is 'ready', consume the remainder under tasks[3] (Anod)
    from app.services.shopfloor.operations_tasks import consume_remainder
    await consume_remainder(
        session,
        task_id=tasks[3].id,
        remainder_id=rem.id,
        quantity=Decimal("150"),
        actor_id=user.id,
    )
    await session.commit()
    
    # Verify remainder was consumed
    await session.refresh(rem)
    assert rem.remainder_quantity == Decimal("0")
    assert rem.consumed_at is not None
    assert rem.consumed_by_task_id == tasks[3].id
    
    # Now let's delete the import batch
    res_del = await client.delete(
        f"/api/production-plans/{plan.id}/batches/{batch.id}",
        headers=headers,
    )
    assert res_del.status_code == 200
    
    # Verify remainder was restored back to 150 and consumed_at cleared
    await session.refresh(rem)
    assert rem.remainder_quantity == Decimal("150")
    assert rem.consumed_at is None
    assert rem.consumed_by_task_id is None
    assert rem.reserved_for_plan_position_id is None


@pytest.mark.asyncio
async def test_take_to_work_partial_auto_transfer(client, session) -> None:
    """Take to work a position with partial remainder coverage.
    
    Checks that the task is active (planned_qty > 0) but still has a complete movement
    created for the covered quantity, and an automatic transfer is sent for that quantity.
    """
    from app.models.spg import StorageProductionGroup, SpgSection
    from app.models.spg_remainder import SpgRemainder
    from app.models.transfer import Transfer, TransferStatus
    
    user = await _make_user(session, "ttw-part-rem@test.local")
    product, plan, pos = await _make_product_route_plan(session, "FG-TTW-PART-REM")
    
    # Resolve sections from route
    stages = (await session.execute(
        select(RouteStage).where(RouteStage.route_id == pos.route_id).order_by(RouteStage.sequence)
    )).scalars().all()
    assert len(stages) == 6
    
    spg_prep = StorageProductionGroup(code="SPG-PART-PREP", name="Prep GHP", is_active=True)
    spg_anod = StorageProductionGroup(code="SPG-PART-ANOD", name="Anod GHP", is_active=True)
    session.add_all([spg_prep, spg_anod])
    await session.flush()
    
    session.add(SpgSection(spg_id=spg_prep.id, section_id=stages[1].section_id, sort_order=0))
    session.add(SpgSection(spg_id=spg_prep.id, section_id=stages[2].section_id, sort_order=10))
    session.add(SpgSection(spg_id=spg_anod.id, section_id=stages[3].section_id, sort_order=0))
    await session.flush()
    
    completed_stages = [
        {
            "sequence": stages[0].sequence,
            "section_id": stages[0].section_id,
            "operation_code": "ISSUE_RAW",
            "operation_name": "ISSUE_RAW",
        },
        {
            "sequence": stages[1].sequence,
            "section_id": stages[1].section_id,
            "operation_code": "DRILL",
            "operation_name": "DRILL",
        },
        {
            "sequence": stages[2].sequence,
            "section_id": stages[2].section_id,
            "operation_code": "SHOT",
            "operation_name": "SHOT",
        }
    ]
    
    # Create remainder covering 60 pcs of 100 pcs total quantity
    rem = SpgRemainder(
        product_id=product.id,
        spg_id=spg_prep.id,
        route_stage_id=stages[2].id,
        remainder_quantity=Decimal("60"),
        original_issued=Decimal("60"),
        completed_stages_json=completed_stages,
        created_by=user.id,
        created_by_user_name=user.full_name,
    )
    session.add(rem)
    await session.commit()
    
    headers = _auth_headers(user)
    res = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [pos.id]},
        headers=headers,
    )
    assert res.status_code == 200
    
    # Verify tasks and statuses
    tasks = (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == pos.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()
    
    assert len(tasks) == 6
    # First 3 stages are partially covered (planned_qty = 100 - 60 = 40)
    assert tasks[0].planned_quantity == Decimal("40")
    assert tasks[1].planned_quantity == Decimal("40")
    assert tasks[2].planned_quantity == Decimal("40")
    
    # Task 1 (Issue) should be ready (it is the first stage that needs work)
    assert tasks[0].status == WorkTaskStatus.ready
    # Task 3 (Shot) should be waiting_previous (it waits for Drill)
    assert tasks[2].status == WorkTaskStatus.waiting_previous
    # Task 4 (Anod) should be waiting_previous (it waits for transfer of 60 pcs remainder)
    assert tasks[3].status == WorkTaskStatus.waiting_previous
    
    # Check that transfer was automatically sent for 60 pcs
    transfer = await session.scalar(
        select(Transfer).where(
            Transfer.from_task_id == tasks[2].id,
            Transfer.to_task_id == tasks[3].id
        )
    )
    assert transfer is not None
    assert transfer.status == TransferStatus.sent
    assert transfer.sent_quantity == Decimal("60")


async def test_take_to_work_remainders_preview(client, session):
    """Test get_remainders_preview endpoint."""
    from app.models.spg import StorageProductionGroup, SpgSection
    from app.models.spg_remainder import SpgRemainder
    
    user = await _make_user(session, "preview-rem@test.local")
    product, plan, pos = await _make_product_route_plan(session, "FG-PREVIEW-REM")
    
    stages = (await session.execute(
        select(RouteStage).where(RouteStage.route_id == pos.route_id).order_by(RouteStage.sequence)
    )).scalars().all()
    
    spg_prep = StorageProductionGroup(code="SPG-PREV-PREP", name="Prev Prep GHP", is_active=True)
    session.add(spg_prep)
    await session.flush()
    
    session.add(SpgSection(spg_id=spg_prep.id, section_id=stages[0].section_id, sort_order=0))
    session.add(SpgSection(spg_id=spg_prep.id, section_id=stages[1].section_id, sort_order=10))
    await session.flush()
    
    completed_stages = [
        {
            "sequence": stages[0].sequence,
            "section_id": stages[0].section_id,
            "operation_code": "ISSUE_RAW",
            "operation_name": "ISSUE_RAW",
        }
    ]
    
    rem = SpgRemainder(
        product_id=product.id,
        spg_id=spg_prep.id,
        route_stage_id=stages[0].id,
        remainder_quantity=Decimal("30"),
        original_issued=Decimal("30"),
        completed_stages_json=completed_stages,
        created_by=user.id,
        created_by_user_name=user.full_name,
    )
    session.add(rem)
    await session.commit()
    
    headers = _auth_headers(user)
    res = await client.get(
        f"/api/production-planning/rows/{pos.id}/remainders-preview",
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["position_id"] == pos.id
    assert data["release_quantity"] == 100.0
    assert len(data["available_remainders"]) == 1
    assert data["available_remainders"][0]["id"] == rem.id
    assert data["available_remainders"][0]["remainder_quantity"] == 30.0
    assert len(data["default_allocation"]) == 1
    assert data["default_allocation"][0]["remainder_id"] == rem.id
    assert data["default_allocation"][0]["allocated_quantity"] == 30.0


async def test_take_to_work_manual_remainder_allocation(client, session):
    """Test take-to-work with manual remainder allocation."""
    from app.models.spg import StorageProductionGroup, SpgSection
    from app.models.spg_remainder import SpgRemainder
    
    user = await _make_user(session, "manual-rem@test.local")
    product, plan, pos = await _make_product_route_plan(session, "FG-MANUAL-REM")
    
    stages = (await session.execute(
        select(RouteStage).where(RouteStage.route_id == pos.route_id).order_by(RouteStage.sequence)
    )).scalars().all()
    
    spg_prep = StorageProductionGroup(code="SPG-MAN-PREP", name="Man Prep GHP", is_active=True)
    session.add(spg_prep)
    await session.flush()
    
    session.add(SpgSection(spg_id=spg_prep.id, section_id=stages[0].section_id, sort_order=0))
    session.add(SpgSection(spg_id=spg_prep.id, section_id=stages[1].section_id, sort_order=10))
    await session.flush()
    
    completed_stages = [
        {
            "sequence": stages[0].sequence,
            "section_id": stages[0].section_id,
            "operation_code": "ISSUE_RAW",
            "operation_name": "ISSUE_RAW",
        }
    ]
    
    rem1 = SpgRemainder(
        product_id=product.id,
        spg_id=spg_prep.id,
        route_stage_id=stages[0].id,
        remainder_quantity=Decimal("50"),
        original_issued=Decimal("50"),
        completed_stages_json=completed_stages,
        created_by=user.id,
        created_by_user_name=user.full_name,
    )
    rem2 = SpgRemainder(
        product_id=product.id,
        spg_id=spg_prep.id,
        route_stage_id=stages[0].id,
        remainder_quantity=Decimal("60"),
        original_issued=Decimal("60"),
        completed_stages_json=completed_stages,
        created_by=user.id,
        created_by_user_name=user.full_name,
    )
    session.add_all([rem1, rem2])
    await session.commit()
    
    # We allocate 40 from rem1 and 60 from rem2 (total 100) manually.
    # This covers the first stage (quantity 100) completely.
    # First stage becomes 'completed', second stage becomes 'ready'.
    # The allocated quantities are consumed immediately.
    headers = _auth_headers(user)
    res = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={
            "position_ids": [pos.id],
            "remainder_allocation": [
                {"remainder_id": rem1.id, "quantity": 40},
                {"remainder_id": rem2.id, "quantity": 60},
            ]
        },
        headers=headers,
    )
    assert res.status_code == 200
    
    # Reload remainders and check remaining quantities
    r1 = await session.get(SpgRemainder, rem1.id)
    r2 = await session.get(SpgRemainder, rem2.id)
    assert r1.remainder_quantity == Decimal("10") # 50 - 40
    assert r2.remainder_quantity == Decimal("0") # 60 - 60
    assert r2.consumed_at is not None
    
    # Reload created tasks and check planned quantities
    tasks = (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == pos.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()
    assert len(tasks) == 6
    assert tasks[0].planned_quantity == Decimal("0")
    assert tasks[0].status == WorkTaskStatus.completed
    assert tasks[1].planned_quantity == Decimal("100")
    assert tasks[1].status == WorkTaskStatus.in_progress


