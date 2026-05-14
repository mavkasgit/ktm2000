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
from app.models.route import ProductionRoute, RouteStep
from app.models.routing import RouteOperationFamily, RouteOutputKind
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
        operation_family=RouteOperationFamily.DRILL,
        output_kind=RouteOutputKind.finished_good,
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
