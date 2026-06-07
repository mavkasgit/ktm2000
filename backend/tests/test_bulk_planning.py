"""Integration tests for bulk plan-position endpoints.

Covers savepoint-isolated bulk approve and bulk delete on production plans.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
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
from app.models.user import User, UserRole


async def _make_user(session, email: str = "bulk-planner@test.local") -> User:
    user = User(
        email=email,
        password_hash="x",
        full_name="Bulk Planner",
        role=UserRole.admin,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_route(session, sku: str) -> tuple[Product, ProductionRoute]:
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


async def _make_plan_with_positions(
    session,
    sku: str,
    n_positions: int,
    *,
    status: PlanPositionStatus = PlanPositionStatus.draft,
    cancelled_count: int = 0,
) -> tuple[ProductionPlan, list[PlanPosition], ProductionRoute]:
    product, route = await _make_route(session, sku)
    plan = ProductionPlan(
        plan_no=f"PLAN-{sku}",
        name=f"Plan {sku}",
        status=ProductionPlanStatus.draft,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()

    positions: list[PlanPosition] = []
    for i in range(n_positions):
        target_status = status
        if i < cancelled_count:
            target_status = PlanPositionStatus.cancelled
        pos = PlanPosition(
            production_plan_id=plan.id,
            product_id=product.id,
            source_type=PlanSourceType.manual,
            source_sku=product.sku,
            source_name=product.name,
            quantity=Decimal("10"),
            source_payload={},
            status=target_status,
            validation_status=PlanPositionValidationStatus.valid,
            validation_errors=[],
            period_start=plan.period_start,
            period_end=plan.period_end,
            has_pack_ops=False,
        )
        pos.route_id = route.id
        session.add(pos)
        positions.append(pos)
    await session.commit()
    return plan, positions, route


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.email)
    return {"Authorization": f"Bearer {token}"}


# --- bulk-approve ----------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_approve_positions_succeeds_for_eligible(client, session) -> None:
    user = await _make_user(session, "bulk-approve-eligible@test.local")
    plan, positions, _ = await _make_plan_with_positions(session, "FG-APPROVE-OK", 3)
    headers = _auth_headers(user)

    response = await client.post(
        f"/api/production-plans/{plan.id}/positions/bulk-approve",
        json={"ids": [p.id for p in positions], "force": False},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["results"]) == 3
    statuses = {r["status"] for r in payload["results"]}
    assert statuses == {"success"}

    refreshed = (
        await session.execute(
            select(PlanPosition).where(PlanPosition.id.in_([p.id for p in positions]))
        )
    ).scalars().all()
    assert all(p.status == PlanPositionStatus.approved for p in refreshed)


@pytest.mark.asyncio
async def test_bulk_approve_positions_partial_failure(client, session) -> None:
    user = await _make_user(session, "bulk-approve-partial@test.local")
    plan, positions, _ = await _make_plan_with_positions(session, "FG-APPROVE-PART", 3)
    # Mark the first position as already approved to make it ineligible
    positions[0].status = PlanPositionStatus.approved
    await session.commit()
    headers = _auth_headers(user)

    response = await client.post(
        f"/api/production-plans/{plan.id}/positions/bulk-approve",
        json={"ids": [p.id for p in positions], "force": False},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    by_id = {r["id"]: r for r in payload["results"]}
    assert by_id[positions[0].id]["status"] == "failed"
    assert by_id[positions[1].id]["status"] == "success"
    assert by_id[positions[2].id]["status"] == "success"


@pytest.mark.asyncio
async def test_bulk_approve_positions_does_not_block_on_invalid_id(client, session) -> None:
    user = await _make_user(session, "bulk-approve-badid@test.local")
    plan, positions, _ = await _make_plan_with_positions(session, "FG-APPROVE-BAD", 2)
    headers = _auth_headers(user)

    response = await client.post(
        f"/api/production-plans/{plan.id}/positions/bulk-approve",
        json={"ids": [positions[0].id, 99_999], "force": False},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    by_id = {r["id"]: r for r in payload["results"]}
    assert by_id[positions[0].id]["status"] == "success"
    assert by_id[99_999]["status"] == "failed"

    # The valid position must have been approved even though the other failed.
    refreshed = await session.get(PlanPosition, positions[0].id)
    assert refreshed is not None
    assert refreshed.status == PlanPositionStatus.approved


# --- bulk-delete -----------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_delete_positions_drafts_removed(client, session) -> None:
    user = await _make_user(session, "bulk-delete-draft@test.local")
    plan, positions, _ = await _make_plan_with_positions(session, "FG-DELETE-DRAFT", 3)
    headers = _auth_headers(user)

    response = await client.post(
        f"/api/production-plans/{plan.id}/positions/bulk-delete",
        json={"ids": [p.id for p in positions]},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["results"]) == 3
    assert all(r["status"] == "success" for r in payload["results"])

    remaining = (
        await session.execute(
            select(PlanPosition).where(PlanPosition.id.in_([p.id for p in positions]))
        )
    ).scalars().all()
    assert remaining == []


@pytest.mark.asyncio
async def test_bulk_delete_cancelled_positions_soft_delete(client, session) -> None:
    user = await _make_user(session, "bulk-delete-cancelled@test.local")
    plan, positions, _ = await _make_plan_with_positions(
        session, "FG-DELETE-CANCEL", 3, cancelled_count=2
    )
    headers = _auth_headers(user)

    response = await client.post(
        f"/api/production-plans/{plan.id}/positions/bulk-delete",
        json={"ids": [positions[0].id, positions[1].id], "reason": "bulk test"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert all(r["status"] == "success" for r in payload["results"])

    refreshed = (
        await session.execute(
            select(PlanPosition).where(PlanPosition.id.in_([positions[0].id, positions[1].id]))
        )
    ).scalars().all()
    assert all(p.deleted_at is not None for p in refreshed)


@pytest.mark.asyncio
async def test_bulk_delete_rejects_approved_position(client, session) -> None:
    user = await _make_user(session, "bulk-delete-approved@test.local")
    plan, positions, _ = await _make_plan_with_positions(
        session, "FG-DELETE-APPR", 2, status=PlanPositionStatus.approved
    )
    headers = _auth_headers(user)

    response = await client.post(
        f"/api/production-plans/{plan.id}/positions/bulk-delete",
        json={"ids": [p.id for p in positions]},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert all(r["status"] == "failed" for r in payload["results"])
    assert all("утверждённую" in (r["reason"] or "") for r in payload["results"])

    refreshed = (
        await session.execute(
            select(PlanPosition).where(PlanPosition.id.in_([p.id for p in positions]))
        )
    ).scalars().all()
    assert all(p.deleted_at is None for p in refreshed)


@pytest.mark.asyncio
async def test_bulk_delete_with_mixed_targets_isolated(client, session) -> None:
    user = await _make_user(session, "bulk-delete-mixed@test.local")
    plan, positions, _ = await _make_plan_with_positions(
        session,
        "FG-DELETE-MIX",
        3,
        cancelled_count=1,
    )
    # Make the second position approved so it cannot be deleted.
    positions[1].status = PlanPositionStatus.approved
    await session.commit()
    headers = _auth_headers(user)

    response = await client.post(
        f"/api/production-plans/{plan.id}/positions/bulk-delete",
        json={"ids": [p.id for p in positions]},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    by_id = {r["id"]: r for r in payload["results"]}
    assert by_id[positions[0].id]["status"] == "success"
    assert by_id[positions[1].id]["status"] == "failed"
    assert by_id[positions[2].id]["status"] == "success"

    # The approved position must remain in the database.
    approved_still_there = await session.get(PlanPosition, positions[1].id)
    assert approved_still_there is not None
    assert approved_still_there.deleted_at is None

    # The hard-deleted position must be gone.
    assert await session.get(PlanPosition, positions[2].id) is None
