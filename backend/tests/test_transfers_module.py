"""Tests for the dedicated transfer module.

Covers the new ``/api/transfers`` endpoints, ``list_ready_to_transfer``
query, and the new "SectionTask becomes completed by its own work
alone" semantic — i.e. a WorkTask can be ``completed`` while still
holding transferable quantity.

Old ``/api/shopfloor/transfers`` endpoints are still tested for
backward compatibility (proxy to the new module).
"""
from __future__ import annotations

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
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.techcard import Techcard, TechcardLine
from app.models.transfer import Transfer, TransferStatus
from app.models.user import User, UserRole
from app.models.work_task import WorkTask, WorkTaskStatus


# ─── helpers ─────────────────────────────────────────────────────────────────


async def _make_user(session, email: str = "xfer@test.local") -> User:
    user = User(
        email=email,
        password_hash="x",
        full_name="Transfer Tester",
        role=UserRole.operator,
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
    """Create a minimal 6-section / 6-step route + plan position."""
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
        session.add(
            RouteStep(
                route_id=route.id,
                sequence=idx,
                section_id=section.id,
                operation_code=op_code,
                operation_name=op_code,
                is_final=(idx == len(sections)),
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


# ─── list_ready_to_transfer ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_ready_to_transfer_empty_for_fresh_task(client, session) -> None:
    """A freshly released (not-yet-completed) task is not ready to transfer."""
    user = await _make_user(session, "xfer-empty@test.local")
    headers = _auth_headers(user)
    ctx = await _make_six_section_fixture(session, sku="FG-XF-EMPTY", planned_qty=Decimal("100"))
    await _release_via_take_to_work(client, ctx["position"].id)

    tasks = await _tasks_by_sequence(session, ctx["position"].id)
    first_section = ctx["sections"][0]
    first_task = next(t for t in tasks if t.section_id == first_section.id)

    resp = await client.get(
        f"/api/transfers/ready?section_id={first_section.id}",
        headers=headers,
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(item["task_id"] != first_task.id for item in items)


@pytest.mark.asyncio
async def test_list_ready_to_transfer_after_completion_only(client, session) -> None:
    """Completing the task puts it into the 'ready to transfer' list."""
    user = await _make_user(session, "xfer-ready@test.local")
    headers = _auth_headers(user)
    ctx = await _make_six_section_fixture(session, sku="FG-XF-READY", planned_qty=Decimal("100"))
    await _release_via_take_to_work(client, ctx["position"].id)

    tasks = await _tasks_by_sequence(session, ctx["position"].id)
    first_section = ctx["sections"][0]
    first_task = next(t for t in tasks if t.section_id == first_section.id)

    # Issue and complete the full plan quantity
    issue = await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/issue",
        json={"quantity": "100", "idempotency_key": "xf-ready:issue"},
        headers=headers,
    )
    assert issue.status_code == 200
    complete = await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/complete",
        json={"good_quantity": "100", "defect_quantity": "0", "idempotency_key": "xf-ready:complete"},
        headers=headers,
    )
    assert complete.status_code == 200

    resp = await client.get(
        f"/api/transfers/ready?section_id={first_section.id}",
        headers=headers,
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    ours = [i for i in items if i["task_id"] == first_task.id]
    assert len(ours) == 1
    assert ours[0]["completed_quantity"] == "100"
    assert ours[0]["transferable_quantity"] == "100"
    assert ours[0]["has_next_step"] is True
    assert ours[0]["next_section_id"] == ctx["sections"][1].id


@pytest.mark.asyncio
async def test_list_ready_to_transfer_spg_filter(client, session) -> None:
    """When SPG is provided, all sections of the SPG are aggregated."""
    user = await _make_user(session, "xfer-spg@test.local")
    headers = _auth_headers(user)
    ctx = await _make_six_section_fixture(
        session, sku="FG-XF-SPG", planned_qty=Decimal("100"), with_spg=True
    )
    spg = ctx["spg"]
    await _release_via_take_to_work(client, ctx["position"].id)

    resp = await client.get(f"/api/transfers/ready?spg_id={spg.id}", headers=headers)
    assert resp.status_code == 200
    # Empty list initially — no completed tasks.
    assert resp.json()["items"] == []


# ─── new /transfers endpoints: send / accept / ready ────────────────────────


@pytest.mark.asyncio
async def test_new_transfers_send_and_accept_via_new_endpoints(client, session) -> None:
    """End-to-end happy path through the new /transfers endpoints."""
    user = await _make_user(session, "xfer-new@test.local")
    headers = _auth_headers(user)
    ctx = await _make_six_section_fixture(session, sku="FG-XF-NEW", planned_qty=Decimal("100"))
    await _release_via_take_to_work(client, ctx["position"].id)
    tasks = await _tasks_by_sequence(session, ctx["position"].id)
    first_task = tasks[0]
    second_task = tasks[1]

    await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/issue",
        json={"quantity": "100", "idempotency_key": "xf-new:issue"},
        headers=headers,
    )
    await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/complete",
        json={"good_quantity": "100", "defect_quantity": "0", "idempotency_key": "xf-new:complete"},
        headers=headers,
    )

    # SEND via the new /transfers endpoint
    send = await client.post(
        "/api/transfers",
        json={"from_task_id": first_task.id, "to_task_id": second_task.id, "quantity": "100", "idempotency_key": "xf-new:send"},
        headers=headers,
    )
    assert send.status_code == 200, send.text
    send_body = send.json()
    assert send_body["status"] == "sent"
    transfer_id = send_body["transfer_id"]

    # ACCEPT via the new /transfers endpoint
    accept = await client.post(
        f"/api/transfers/{transfer_id}/accept",
        json={"accepted_quantity": "100", "rejected_quantity": "0", "idempotency_key": "xf-new:accept"},
        headers=headers,
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["status"] == "accepted"

    # Verify GET /transfers/{id} returns the new shape
    details = await client.get(f"/api/transfers/{transfer_id}", headers=headers)
    assert details.status_code == 200
    body = details.json()
    assert body["id"] == transfer_id
    assert body["sent_quantity"] == "100"
    assert body["accepted_quantity"] == "100"
    assert body["discrepancies"] == []


@pytest.mark.asyncio
async def test_new_transfers_partial_accept_creates_discrepancy(client, session) -> None:
    user = await _make_user(session, "xfer-partial@test.local")
    headers = _auth_headers(user)
    ctx = await _make_six_section_fixture(session, sku="FG-XF-PART", planned_qty=Decimal("100"))
    await _release_via_take_to_work(client, ctx["position"].id)
    tasks = await _tasks_by_sequence(session, ctx["position"].id)
    first_task = tasks[0]
    second_task = tasks[1]

    await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/issue",
        json={"quantity": "100", "idempotency_key": "xf-partial:issue"},
        headers=headers,
    )
    await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/complete",
        json={"good_quantity": "100", "defect_quantity": "0", "idempotency_key": "xf-partial:complete"},
        headers=headers,
    )

    send = await client.post(
        "/api/transfers",
        json={"from_task_id": first_task.id, "to_task_id": second_task.id, "quantity": "100", "idempotency_key": "xf-partial:send"},
        headers=headers,
    )
    assert send.status_code == 200
    transfer_id = send.json()["transfer_id"]

    accept = await client.post(
        f"/api/transfers/{transfer_id}/accept",
        json={"accepted_quantity": "90", "rejected_quantity": "10", "reason": "short", "idempotency_key": "xf-partial:accept"},
        headers=headers,
    )
    assert accept.status_code == 200
    body = accept.json()
    assert body["status"] == "partially_accepted"
    assert body["discrepancy_id"] is not None


# ─── Decoupled "completed" status ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_work_task_becomes_completed_before_transfer(client, session) -> None:
    """A SectionTask becomes `completed` once the section has worked off
    everything that was available to it — the transfer to the next SPG
    is a SEPARATE process and does NOT gate this status anymore.
    """
    user = await _make_user(session, "xfer-status@test.local")
    headers = _auth_headers(user)
    ctx = await _make_six_section_fixture(session, sku="FG-XF-STAT", planned_qty=Decimal("100"))
    await _release_via_take_to_work(client, ctx["position"].id)
    tasks = await _tasks_by_sequence(session, ctx["position"].id)
    first_task = tasks[0]

    # Issue and complete the full plan quantity — NO transfer yet
    issue = await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/issue",
        json={"quantity": "100", "idempotency_key": "xf-stat:issue"},
        headers=headers,
    )
    assert issue.status_code == 200
    complete = await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/complete",
        json={"good_quantity": "100", "defect_quantity": "0", "idempotency_key": "xf-stat:complete"},
        headers=headers,
    )
    assert complete.status_code == 200

    # Refresh from DB and verify status is already `completed` even though
    # no transfer has been sent.
    refreshed = (
        await session.execute(
            select(WorkTask).where(WorkTask.id == first_task.id)
        )
    ).scalar_one()
    assert refreshed.status == WorkTaskStatus.completed
    assert refreshed.cached_completed_quantity == Decimal("100")
    # The transferable quantity is still 100 — that's the whole point of
    # decoupling: the task is closed, but the operator can still
    # transfer the remainder to the next SPG.
    assert refreshed.cached_transferred_quantity == Decimal("0")
    assert (
        refreshed.cached_completed_quantity - refreshed.cached_transferred_quantity
        == Decimal("100")
    )


# ─── Backward-compat: old /shopfloor/transfers still works ───────────────────


@pytest.mark.asyncio
async def test_legacy_shopfloor_transfers_endpoint_still_works(client, session) -> None:
    """The old `/api/shopfloor/transfers` endpoints are kept as proxies
    to the new module — they must continue to function for existing
    integrations.
    """
    user = await _make_user(session, "xfer-legacy@test.local")
    headers = _auth_headers(user)
    ctx = await _make_six_section_fixture(session, sku="FG-XF-LEG", planned_qty=Decimal("100"))
    await _release_via_take_to_work(client, ctx["position"].id)
    tasks = await _tasks_by_sequence(session, ctx["position"].id)
    first_task = tasks[0]
    second_task = tasks[1]

    await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/issue",
        json={"quantity": "100", "idempotency_key": "xf-leg:issue"},
        headers=headers,
    )
    await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/complete",
        json={"good_quantity": "100", "defect_quantity": "0", "idempotency_key": "xf-leg:complete"},
        headers=headers,
    )

    # Use the LEGACY endpoint
    send = await client.post(
        "/api/shopfloor/transfers",
        json={"from_task_id": first_task.id, "to_task_id": second_task.id, "quantity": "100", "idempotency_key": "xf-leg:send"},
        headers=headers,
    )
    assert send.status_code == 200
    transfer_id = send.json()["transfer_id"]

    accept = await client.post(
        f"/api/shopfloor/transfers/{transfer_id}/accept",
        json={"accepted_quantity": "100", "rejected_quantity": "0", "idempotency_key": "xf-leg:accept"},
        headers=headers,
    )
    assert accept.status_code == 200
    assert accept.json()["status"] == "accepted"

    # The legacy "incoming-transfers" endpoint still works.
    incoming = await client.get(
        f"/api/shopfloor/sections/{ctx['sections'][1].id}/incoming-transfers",
        headers=headers,
    )
    assert incoming.status_code == 200
    # The transfer was already accepted, so it should NOT appear in
    # the open-incoming list.
    assert incoming.json()["incoming_transfers"] == []
