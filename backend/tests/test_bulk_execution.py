"""Integration tests for bulk execution endpoints.

Covers savepoint-isolated:
- soft-delete-batch (cancelled positions)
- manual-pass-batch (full through-pass)
- cancel-batch and restore-batch (refactored to use savepoints)
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models.internal_plan import SectionPlanLine
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


async def _make_user(session, email: str = "bulk-exec@test.local") -> User:
    user = User(
        email=email,
        password_hash="x",
        full_name="Bulk Operator",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_route(session, sku: str) -> tuple[Product, ProductionRoute, list[RouteStage]]:
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
    return product, route, stages


async def _make_plan_with_positions(
    session,
    sku: str,
    n_positions: int,
    *,
    status: PlanPositionStatus = PlanPositionStatus.approved,
) -> tuple[ProductionPlan, list[PlanPosition], ProductionRoute, list[RouteStage]]:
    product, route, stages = await _make_route(session, sku)
    plan = ProductionPlan(
        plan_no=f"PLAN-{sku}",
        name=f"Plan {sku}",
        status=ProductionPlanStatus.approved,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()

    positions: list[PlanPosition] = []
    for _ in range(n_positions):
        pos = PlanPosition(
            production_plan_id=plan.id,
            product_id=product.id,
            source_type=PlanSourceType.manual,
            source_sku=product.sku,
            source_name=product.name,
            quantity=Decimal("10"),
            source_payload={},
            status=status,
            validation_status=PlanPositionValidationStatus.valid,
            validation_errors=[],
            period_start=plan.period_start,
            period_end=plan.period_end,
            has_pack_ops=False,
            route_id=route.id,
        )
        session.add(pos)
        positions.append(pos)
    await session.commit()
    return plan, positions, route, stages


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.email)
    return {"Authorization": f"Bearer {token}"}


# --- soft-delete-batch -----------------------------------------------------


@pytest.mark.asyncio
async def test_soft_delete_batch_removes_only_cancelled(client, session) -> None:
    user = await _make_user(session, "soft-del-mixed@test.local")
    plan, positions, _, _ = await _make_plan_with_positions(
        session, "FG-SDEL-MIXED", 3, status=PlanPositionStatus.cancelled
    )
    # Promote the second position to approved so the bulk endpoint must skip it.
    positions[1].status = PlanPositionStatus.approved
    await session.commit()
    headers = _auth_headers(user)

    response = await client.post(
        "/api/production-planning/rows/soft-delete-batch",
        json={"position_ids": [p.id for p in positions], "reason": "bulk soft delete"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    by_id = {r["position_id"]: r for r in payload["results"]}
    assert by_id[positions[0].id]["status"] == "success"
    assert by_id[positions[1].id]["status"] == "skipped"
    assert by_id[positions[2].id]["status"] == "success"

    refreshed = (
        await session.execute(
            select(PlanPosition).where(PlanPosition.id.in_([p.id for p in positions]))
        )
    ).scalars().all()
    soft_deleted = {p.id for p in refreshed if p.deleted_at is not None}
    assert soft_deleted == {positions[0].id, positions[2].id}
    # Approved position must remain intact.
    approved_row = next(p for p in refreshed if p.id == positions[1].id)
    assert approved_row.deleted_at is None


@pytest.mark.asyncio
async def test_soft_delete_batch_isolates_failures(client, session) -> None:
    user = await _make_user(session, "soft-del-isolate@test.local")
    plan, positions, _, _ = await _make_plan_with_positions(
        session, "FG-SDEL-ISOLATE", 2, status=PlanPositionStatus.cancelled
    )
    headers = _auth_headers(user)

    response = await client.post(
        "/api/production-planning/rows/soft-delete-batch",
        json={"position_ids": [positions[0].id, 99_999]},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    by_id = {r["position_id"]: r for r in payload["results"]}
    assert by_id[positions[0].id]["status"] == "success"
    assert by_id[99_999]["status"] == "failed"


# --- cancel-batch / restore-batch (savepoint refactor) ---------------------


@pytest.mark.asyncio
async def test_cancel_batch_with_mixed_states(client, session) -> None:
    user = await _make_user(session, "cancel-mixed@test.local")
    plan, positions, _, _ = await _make_plan_with_positions(
        session, "FG-CANCEL-MIX", 3, status=PlanPositionStatus.approved
    )
    # Cancel the second one beforehand to trigger a "skipped" outcome.
    positions[1].status = PlanPositionStatus.cancelled
    await session.commit()
    headers = _auth_headers(user)

    response = await client.post(
        "/api/production-planning/rows/cancel-batch",
        json={"position_ids": [p.id for p in positions]},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    by_id = {r["position_id"]: r for r in payload["results"]}
    assert by_id[positions[0].id]["status"] == "success"
    assert by_id[positions[1].id]["status"] == "skipped"
    assert by_id[positions[2].id]["status"] == "success"

    refreshed = (
        await session.execute(
            select(PlanPosition).where(PlanPosition.id.in_([p.id for p in positions]))
        )
    ).scalars().all()
    cancelled = {p.id for p in refreshed if p.status == PlanPositionStatus.cancelled}
    assert cancelled == {positions[0].id, positions[1].id, positions[2].id}


@pytest.mark.asyncio
async def test_restore_batch_after_cancel(client, session) -> None:
    user = await _make_user(session, "restore-after@test.local")
    plan, positions, _, _ = await _make_plan_with_positions(
        session, "FG-RESTORE", 2, status=PlanPositionStatus.approved
    )
    headers = _auth_headers(user)

    cancel_res = await client.post(
        "/api/production-planning/rows/cancel-batch",
        json={"position_ids": [p.id for p in positions]},
        headers=headers,
    )
    assert cancel_res.status_code == 200
    assert all(r["status"] == "success" for r in cancel_res.json()["results"])

    restore_res = await client.post(
        "/api/production-planning/rows/restore-batch",
        json={"position_ids": [p.id for p in positions]},
        headers=headers,
    )
    assert restore_res.status_code == 200
    assert all(r["status"] == "success" for r in restore_res.json()["results"])

    refreshed = (
        await session.execute(
            select(PlanPosition).where(PlanPosition.id.in_([p.id for p in positions]))
        )
    ).scalars().all()
    assert all(p.status == PlanPositionStatus.approved for p in refreshed)


# --- manual-pass-batch ----------------------------------------------------


@pytest.mark.asyncio
async def test_manual_pass_batch_full_route(client, session) -> None:
    user = await _make_user(session, "manual-pass@test.local")
    plan, positions, _, _ = await _make_plan_with_positions(
        session, "FG-MANUAL-PASS", 2, status=PlanPositionStatus.approved
    )
    headers = _auth_headers(user)

    response = await client.post(
        "/api/production-planning/rows/manual-pass-batch",
        json={
            "position_ids": [p.id for p in positions],
            "complete_route": True,
            "comment": "bulk test pass",
        },
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["results"]) == 2
    for result in payload["results"]:
        assert result["status"] == "success"
        assert result["position_completed"] is True
        assert (result["movements_created"] or 0) >= 1

    # Verify movements and transfers were created for the through-pass.
    movement_count = (
        await session.execute(
            select(Movement)
            .join(SectionPlanLine, SectionPlanLine.id == Movement.section_plan_line_id)
            .where(SectionPlanLine.plan_position_id.in_([p.id for p in positions]))
        )
    ).scalars().all()
    assert len(movement_count) >= 4  # at least 2 movements per position (issue + complete)

    transfer_count = await session.execute(select(Transfer))
    assert len(transfer_count.scalars().all()) >= 2  # one transfer per position

    # Verify all tasks are completed.
    tasks = await session.execute(
        select(WorkTask)
        .join(SectionPlanLine, SectionPlanLine.id == WorkTask.section_plan_line_id)
        .where(SectionPlanLine.plan_position_id.in_([p.id for p in positions]))
    )
    task_list = tasks.scalars().all()
    assert all(t.status == WorkTaskStatus.completed for t in task_list)


@pytest.mark.asyncio
async def test_manual_pass_batch_isolates_failure(client, session) -> None:
    user = await _make_user(session, "manual-pass-isolate@test.local")
    plan, positions, _, _ = await _make_plan_with_positions(
        session, "FG-MANUAL-ISO", 2, status=PlanPositionStatus.approved
    )
    headers = _auth_headers(user)

    response = await client.post(
        "/api/production-planning/rows/manual-pass-batch",
        json={
            "position_ids": [positions[0].id, 99_999],
            "complete_route": True,
        },
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    by_id = {r["position_id"]: r for r in payload["results"]}
    assert by_id[positions[0].id]["status"] == "success"
    assert by_id[99_999]["status"] == "failed"
