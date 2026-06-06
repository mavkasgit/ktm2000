"""Integration tests for bulk shopfloor endpoints.

Covers savepoint-isolated bulk issue, complete, and transfer-send
operations, including the X-Shopfloor-Single-Section-Id lock check.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models.internal_plan import InternalPlan, SectionPlanLine
from app.models.movement import Movement
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.product import Product, ProductType
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section
from app.models.techcard import Techcard, TechcardLine
from app.models.transfer import Transfer
from app.models.user import User, UserRole
from app.models.work_task import WorkTask, WorkTaskStatus


async def _make_user(session, email: str = "bulk-shop@test.local") -> User:
    user = User(
        email=email,
        password_hash="x",
        full_name="Bulk Shopfloor",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_two_section_route(
    session, sku: str
) -> tuple[Product, ProductionRoute, list[Section], list[RouteStage]]:
    product = Product(
        sku=sku,
        name=f"Finished {sku}",
        type=ProductType.finished_good,
        unit="pcs",
    )
    sections = [
        Section(code=f"{sku}-ISSUE", name="Issue", kind="raw_stock"),
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

    step_ops = ["ISSUE_RAW", "ACCEPT_FINISHED"]
    stages: list[RouteStage] = []
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
        stages.append(stage)
    await session.flush()
    return product, route, sections, stages


async def _make_released_position_with_tasks(
    session, sku: str
) -> tuple[ProductionPlan, PlanPosition, list[WorkTask]]:
    product, route, sections, stages = await _make_two_section_route(session, sku)
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
        quantity=Decimal("10"),
        source_payload={},
        status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        period_start=plan.period_start,
        period_end=plan.period_end,
        has_pack_ops=False,
        route_id=route.id,
    )
    session.add(pos)
    await session.flush()

    internal_plan = InternalPlan(production_plan_id=plan.id)
    session.add(internal_plan)
    await session.flush()

    tasks: list[WorkTask] = []
    for idx, (section, stage) in enumerate(zip(sections, stages, strict=True), start=1):
        line = SectionPlanLine(
            internal_plan_id=internal_plan.id,
            plan_position_id=pos.id,
            section_id=section.id,
            product_id=product.id,
            route_id=route.id,
            route_stage_id=stage.id,
            sequence=idx,
            planned_quantity=Decimal("10"),
            cached_available_quantity=Decimal("10"),
            cached_remaining_quantity=Decimal("10"),
        )
        session.add(line)
        await session.flush()
        task = WorkTask(
            section_plan_line_id=line.id,
            section_id=section.id,
            product_id=pos.product_id,
            route_stage_id=stage.id,
            planned_quantity=Decimal("10"),
            status=WorkTaskStatus.ready if idx == 1 else WorkTaskStatus.waiting_previous,
        )
        session.add(task)
        tasks.append(task)
    await session.flush()
    await session.commit()
    return plan, pos, tasks


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.email)
    return {"Authorization": f"Bearer {token}"}


# --- bulk-issue ------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_issue_creates_movements_for_each_task(client, session) -> None:
    user = await _make_user(session, "bulk-issue-ok@test.local")
    plan, pos, tasks = await _make_released_position_with_tasks(session, "FG-BULK-ISSUE-OK")
    # Create a second position with its own task chain.
    plan2, pos2, tasks2 = await _make_released_position_with_tasks(
        session, "FG-BULK-ISSUE-OK-2"
    )
    # Only the first task in each chain is in `ready` state and can be issued.
    issueable = [tasks[0], tasks2[0]]
    await session.commit()
    headers = _auth_headers(user)

    response = await client.post(
        "/api/shopfloor/tasks/bulk-issue",
        json={
            "entries": [
                {
                    "task_id": t.id,
                    "quantity": "5",
                    "idempotency_key": f"bulk-issue-{t.id}",
                }
                for t in issueable
            ]
        },
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["results"]) == len(issueable)
    assert all(r["status"] == "success" for r in payload["results"])

    # Verify movements were created — one per entry.
    movements = (
        await session.execute(
            select(Movement).where(Movement.task_id.in_([t.id for t in issueable]))
        )
    ).scalars().all()
    assert len(movements) == len(issueable)


@pytest.mark.asyncio
async def test_bulk_issue_isolates_unknown_task(client, session) -> None:
    user = await _make_user(session, "bulk-issue-bad@test.local")
    plan, pos, tasks = await _make_released_position_with_tasks(session, "FG-BULK-ISSUE-BAD")
    headers = _auth_headers(user)

    response = await client.post(
        "/api/shopfloor/tasks/bulk-issue",
        json={
            "entries": [
                {"task_id": tasks[0].id, "quantity": "1"},
                {"task_id": 99_999, "quantity": "1"},
            ]
        },
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    by_id = {r["id"]: r for r in payload["results"]}
    assert by_id[tasks[0].id]["status"] == "success"
    assert by_id[99_999]["status"] == "failed"


# --- bulk-complete ---------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_complete_marks_tasks_done(client, session) -> None:
    user = await _make_user(session, "bulk-complete@test.local")
    plan, pos, tasks = await _make_released_position_with_tasks(
        session, "FG-BULK-COMPLETE"
    )
    headers = _auth_headers(user)

    # Issue first so complete has data to work with.
    issue_res = await client.post(
        "/api/shopfloor/tasks/bulk-issue",
        json={
            "entries": [
                {
                    "task_id": tasks[0].id,
                    "quantity": "10",
                    "idempotency_key": f"bulk-issue-pre-{tasks[0].id}",
                }
            ]
        },
        headers=headers,
    )
    assert issue_res.status_code == 200
    assert issue_res.json()["results"][0]["status"] == "success"

    complete_res = await client.post(
        "/api/shopfloor/tasks/bulk-complete",
        json={
            "entries": [
                {
                    "task_id": tasks[0].id,
                    "good_quantity": "10",
                    "defect_quantity": "0",
                    "idempotency_key": f"bulk-complete-{tasks[0].id}",
                }
            ]
        },
        headers=headers,
    )
    assert complete_res.status_code == 200
    payload = complete_res.json()
    assert payload["results"][0]["status"] == "success"

    refreshed = await session.get(WorkTask, tasks[0].id)
    assert refreshed is not None
    assert refreshed.status == WorkTaskStatus.completed


# --- bulk-send -------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_send_creates_transfers(client, session) -> None:
    user = await _make_user(session, "bulk-send@test.local")
    plan, pos, tasks = await _make_released_position_with_tasks(session, "FG-BULK-SEND")
    headers = _auth_headers(user)

    # Issue + complete the first task to unlock the transfer.
    await client.post(
        "/api/shopfloor/tasks/bulk-issue",
        json={
            "entries": [
                {
                    "task_id": tasks[0].id,
                    "quantity": "10",
                    "idempotency_key": f"bulk-send-pre-{tasks[0].id}",
                }
            ]
        },
        headers=headers,
    )
    await client.post(
        "/api/shopfloor/tasks/bulk-complete",
        json={
            "entries": [
                {
                    "task_id": tasks[0].id,
                    "good_quantity": "10",
                    "idempotency_key": f"bulk-send-pre-c-{tasks[0].id}",
                }
            ]
        },
        headers=headers,
    )

    send_res = await client.post(
        "/api/shopfloor/tasks/bulk-send",
        json={
            "entries": [
                {
                    "from_task_id": tasks[0].id,
                    "to_task_id": tasks[1].id,
                    "quantity": "10",
                    "idempotency_key": f"bulk-send-{tasks[0].id}",
                }
            ]
        },
        headers=headers,
    )
    assert send_res.status_code == 200
    payload = send_res.json()
    assert payload["results"][0]["status"] == "success"

    transfers = (
        await session.execute(select(Transfer).where(Transfer.from_task_id == tasks[0].id))
    ).scalars().all()
    assert len(transfers) == 1


# --- section-lock enforcement ---------------------------------------------


@pytest.mark.asyncio
async def test_bulk_issue_respects_section_lock(client, session) -> None:
    user = await _make_user(session, "bulk-lock@test.local")
    plan, pos, tasks = await _make_released_position_with_tasks(
        session, "FG-BULK-LOCK"
    )
    other_plan, other_pos, other_tasks = await _make_released_position_with_tasks(
        session, "FG-BULK-LOCK-OTHER"
    )
    locked_section_id = tasks[0].section_id
    headers = {
        **_auth_headers(user),
        "X-Shopfloor-Single-Section-Id": str(locked_section_id),
    }

    response = await client.post(
        "/api/shopfloor/tasks/bulk-issue",
        json={
            "entries": [
                {"task_id": tasks[0].id, "quantity": "1"},
                {"task_id": other_tasks[0].id, "quantity": "1"},
            ]
        },
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    by_id = {r["id"]: r for r in payload["results"]}
    assert by_id[tasks[0].id]["status"] == "success"
    assert by_id[other_tasks[0].id]["status"] == "failed"
    assert "locked" in (by_id[other_tasks[0].id]["reason"] or "").lower()
