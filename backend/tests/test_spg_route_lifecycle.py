"""E2E: SPG-aware route lifecycle with mixed remainder sources.

Verifies that the new SPG/remainder machinery plays nicely with the rest of
the execution flow:

  1. Manual operations (in) seed remainders in SPG-RAW and SPG-WIP.
  2. Position is approved and taken to work → 6 WorkTasks created.
  3. Each step issues a mix of consume_remainder (from a SPG remainder)
     + direct issue_to_work.
  4. After complete, any surplus is returned to the current task's section
     (and therefore its SPG) via return_remainder_to_stock — EXCEPT on
     the first warehouse section (RAW), which is treated as a "raw only"
     staging area: no return_remainder_to_stock, no new remainders.
  5. Final step final-releases the planned quantity.
  6. SPG snapshots, remainders, and the per-remainder history endpoint
     reflect the journey end-to-end.

Two smaller, focused tests sit alongside it:

  * consume_remainder is allowed to push a remainder negative
    (post-factum over-issue scenario).
  * manual-operation in is the canonical way to bring a negative
    remainder back to non-negative.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
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
from app.models.route import ProductionRoute, RouteStage, RouteOperation
from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.techcard import Techcard, TechcardLine
from app.models.user import User, UserRole
from app.models.spg_remainder import SpgRemainder
from app.models.work_task import WorkTask, WorkTaskStatus


# ─── helpers ─────────────────────────────────────────────────────────────────


async def _make_user(session, email: str = "spg-e2e@test.local") -> User:
    user = User(
        email=email,
        password_hash="x",
        full_name="SPG E2E Operator",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.email)
    return {"Authorization": f"Bearer {token}"}


async def _make_product_with_route_and_spgs(
    session,
    *,
    sku: str,
    planned_qty: Decimal,
) -> dict:
    """Create the full fixture: product, 6 sections, 2 SPGs, 1 route, plan, position.

    Sections (all in ``SPG_<sku>_<CODE>`` codename scheme):
        RAW, DRILL, SHOT, ANOD, WIP, PACK
    SPGs:
        SPG-RAW → [RAW]
        SPG-WIP → [DRILL, SHOT, ANOD, WIP]
        PACK     → not in any SPG (final, no surplus expected)
    Route:
        6 steps matching the sections, last one is final.
    """
    section_specs: list[tuple[str, str]] = [
        ("RAW", "raw_stock"),
        ("DRILL", "production"),
        ("SHOT", "production"),
        ("ANOD", "production"),
        ("WIP", "wip_stock"),
        ("PACK", "production"),
    ]
    sections: list[Section] = []
    for code, kind in section_specs:
        sec = Section(code=f"{sku}-{code}", name=code, kind=kind, sort_order=len(sections) * 10, is_active=True)
        session.add(sec)
        sections.append(sec)
    await session.flush()

    spg_raw = StorageProductionGroup(code=f"{sku}-SPG-RAW", name="Raw warehouse", is_active=True, sort_order=0)
    spg_wip = StorageProductionGroup(code=f"{sku}-SPG-WIP", name="WIP storage", is_active=True, sort_order=10)
    session.add_all([spg_raw, spg_wip])
    await session.flush()

    # SPG-RAW holds only RAW (idx 0)
    session.add(SpgSection(spg_id=spg_raw.id, section_id=sections[0].id, sort_order=0))
    # SPG-WIP holds DRILL, SHOT, ANOD, WIP (idx 1..4)
    for i in range(1, 5):
        session.add(SpgSection(spg_id=spg_wip.id, section_id=sections[i].id, sort_order=(i - 1) * 10))
    # PACK (idx 5) is deliberately left out of any SPG

    product = Product(
        sku=sku,
        name=f"Product {sku}",
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
    )
    session.add(product)
    await session.flush()

    route = ProductionRoute(name=f"Route {sku}", description="SPG E2E route", is_active=True)
    session.add(route)
    await session.flush()

    step_ops = ["ISSUE_RAW", "DRILL", "SHOT", "ANOD", "MOVE_TO_WIP", "PACK"]
    for idx, (section, op_code) in enumerate(zip(sections, step_ops, strict=True), start=1):
        stage = RouteStage(
            route_id=route.id,
            sequence=idx,
            section_id=section.id,
            is_final=(idx == len(sections)),
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

    position = PlanPosition(
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
        route_assigned_at=datetime.now(UTC),
    )
    session.add(position)
    await session.commit()

    return {
        "product": product,
        "plan": plan,
        "position": position,
        "sections": sections,
        "spg_raw": spg_raw,
        "spg_wip": spg_wip,
        "route": route,
        "techcard": techcard,
    }


async def _get_tasks_by_sequence(session, position_id: int) -> list[WorkTask]:
    """Return WorkTasks for the position ordered by their route step sequence."""
    return (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == position_id)
            .order_by(SectionPlanLine.sequence, WorkTask.id)
        )
    ).scalars().all()


async def _issue_mixed(
    client,
    headers: dict[str, str],
    task_id: int,
    *,
    from_remainder_id: int | None = None,
    from_qty: Decimal = Decimal("0"),
    direct_qty: Decimal = Decimal("0"),
    run_id: str = "spg-e2e",
    stage: str = "1",
) -> None:
    """Issue: optionally consume a remainder and/or do a direct issue_to_work."""
    if from_qty > 0 and from_remainder_id is not None:
        resp = await client.post(
            "/api/shopfloor/remainders/consume",
            json={
                "remainder_id": int(from_remainder_id),
                "task_id": task_id,
                "quantity": str(from_qty),
                "idempotency_key": f"{run_id}:stage{stage}:consume",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

    if direct_qty > 0:
        resp = await client.post(
            f"/api/shopfloor/tasks/{task_id}/issue",
            json={
                "quantity": str(direct_qty),
                "idempotency_key": f"{run_id}:stage{stage}:issue",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text


async def _complete_with_return(
    client,
    headers: dict[str, str],
    task_id: int,
    *,
    good: Decimal,
    defect: Decimal,
    return_qty: Decimal = Decimal("0"),
    run_id: str = "spg-e2e",
    stage: str = "1",
) -> int | None:
    """Complete the task and (optionally) return the surplus to stock.

    Returns the new remainder_id when return_qty > 0.
    """
    resp = await client.post(
        f"/api/shopfloor/tasks/{task_id}/complete",
        json={
            "good_quantity": str(good),
            "defect_quantity": str(defect),
            "idempotency_key": f"{run_id}:stage{stage}:complete",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    if return_qty > 0:
        resp = await client.post(
            "/api/shopfloor/remainders/return",
            json={
                "task_id": task_id,
                "quantity": str(return_qty),
                "comment": "over-issue surplus",
                "idempotency_key": f"{run_id}:stage{stage}:return",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        return int(resp.json()["remainder_id"])
    return None


async def _transfer_to_next(
    client,
    headers: dict[str, str],
    from_task_id: int,
    *,
    quantity: Decimal,
    run_id: str = "spg-e2e",
    stage: str = "1",
) -> None:
    """Send `quantity` from the current task to the next route step and accept it."""
    resp = await client.post(
        "/api/shopfloor/transfers",
        json={
            "from_task_id": from_task_id,
            "to_task_id": None,  # auto-create target task on the next step
            "quantity": str(quantity),
            "idempotency_key": f"{run_id}:stage{stage}:send",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    transfer_id = int(resp.json()["transfer_id"])

    resp = await client.post(
        f"/api/shopfloor/transfers/{transfer_id}/accept",
        json={
            "accepted_quantity": str(quantity),
            "rejected_quantity": "0",
            "idempotency_key": f"{run_id}:stage{stage}:receive",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


def _newest_remainder(items: list[dict]) -> dict:
    """Pick the most recently created remainder (max id) from a list response."""
    return max(items, key=lambda r: r["id"])


# ─── main scenario ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_spg_route_full_lifecycle_with_mixed_remainders(client, session) -> None:
    """Full route run with mixed SPG + direct-issue sources, returns to SPG, final-release."""
    user = await _make_user(session, "lifecycle@test.local")
    headers = _auth_headers(user)

    ctx = await _make_product_with_route_and_spgs(
        session, sku="FG-SPG-E2E", planned_qty=Decimal("100")
    )
    spg_raw = ctx["spg_raw"]
    spg_wip = ctx["spg_wip"]
    sections = ctx["sections"]

    # ── 1. Pre-populate SPGs via manual-operation in ──────────────────────
    # SPG-RAW: +50 of raw material in the RAW section (the only source for step 1)
    in_resp = await client.post(
        f"/api/spg/{spg_raw.id}/manual-operation",
        json={
            "product_id": ctx["product"].id,
            "section_id": sections[0].id,
            "operation_type": "in",
            "quantity": 50,
            "reason": "входной контроль",
        },
        headers=headers,
    )
    assert in_resp.status_code == 200, in_resp.text
    initial_raw_remainder_id = int(in_resp.json()["remainder_id"])
    assert in_resp.json()["new_remainder_quantity"] == 50

    # SPG-WIP: +20 in the DRILL section (a non-zero starting stock for step 2
    # so we exercise consume_remainder from the second SPG too).
    in_resp2 = await client.post(
        f"/api/spg/{spg_wip.id}/manual-operation",
        json={
            "product_id": ctx["product"].id,
            "section_id": sections[1].id,
            "operation_type": "in",
            "quantity": 20,
            "reason": "межцеховой запас",
        },
        headers=headers,
    )
    assert in_resp2.status_code == 200, in_resp2.text
    initial_drill_remainder_id = int(in_resp2.json()["remainder_id"])
    assert in_resp2.json()["new_remainder_quantity"] == 20

    # ── 2. Verify pre-populate (remainders + snapshot) ─────────────────────
    list_resp = await client.get(f"/api/spg/{spg_raw.id}/remainders")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1
    assert items[0]["remainder_quantity"] == 50
    assert items[0]["source"] == "manual"

    snap = (await client.get(f"/api/spg/{spg_raw.id}/snapshot")).json()
    assert snap["totals"]["spg_available"] == 50
    assert snap["totals"]["planned"] == 0  # no tasks yet
    assert snap["totals"]["completed"] == 0

    # SPG-WIP carries the 20-unit DRILL seed from step 1
    snap_wip_seed = (await client.get(f"/api/spg/{spg_wip.id}/snapshot")).json()
    assert snap_wip_seed["totals"]["spg_available"] == 20
    assert snap_wip_seed["totals"]["planned"] == 0  # no tasks yet
    assert snap_wip_seed["totals"]["completed"] == 0

    # ── 3. Take to work (creates 6 tasks) ─────────────────────────────────
    take_resp = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [ctx["position"].id]},
        headers=headers,
    )
    assert take_resp.status_code == 200, take_resp.text
    result = take_resp.json()["results"][0]
    assert result["status"] == "success"
    assert result["tasks_created"] == 6

    tasks = await _get_tasks_by_sequence(session, ctx["position"].id)
    assert len(tasks) == 6
    assert tasks[0].status == WorkTaskStatus.ready
    assert tasks[1].status == WorkTaskStatus.waiting_previous

    # Per-section lookup for cross-checking
    task_by_section = {t.section_id: t for t in tasks}
    raw_task = task_by_section[sections[0].id]
    drill_task = task_by_section[sections[1].id]
    shot_task = task_by_section[sections[2].id]
    anod_task = task_by_section[sections[3].id]
    wip_task = task_by_section[sections[4].id]
    pack_task = task_by_section[sections[5].id]

    # ── 4. Step 1 (RAW) — 30 from SPG + 70 direct, complete 80+5 ─────────
    # RAW is the "raw input" section: no return_remainder_to_stock is ever
    # called here, so SPG-RAW never accumulates its own remainders beyond
    # the manual-op-in seed. The 15 units of in_work (100 issued - 80 good
    # - 5 defect) stay on the task as in_work and are *not* returned to the
    # SPG.
    await _issue_mixed(
        client, headers, raw_task.id,
        from_remainder_id=initial_raw_remainder_id, from_qty=Decimal("30"),
        direct_qty=Decimal("70"), run_id="spg-e2e", stage="1",
    )
    await _complete_with_return(
        client, headers, raw_task.id,
        good=Decimal("80"), defect=Decimal("5"),
        return_qty=Decimal("0"),  # never return to RAW
        run_id="spg-e2e", stage="1",
    )

    # SPG-RAW: only the original 50 → 20. No new return-remainder was created.
    raw_items = (await client.get(f"/api/spg/{spg_raw.id}/remainders")).json()
    assert len(raw_items) == 1
    assert raw_items[0]["remainder_quantity"] == 20
    assert raw_items[0]["source"] == "manual"

    # Transfer the 80 good units from RAW to DRILL → unlocks step 2
    await _transfer_to_next(
        client, headers, raw_task.id,
        quantity=Decimal("80"), run_id="spg-e2e", stage="1",
    )

    # ── 5. Step 2 (DRILL) — 20 from SPG-WIP's DRILL seed + 60 direct, complete 70+5, return 5 ─
    await _issue_mixed(
        client, headers, drill_task.id,
        from_remainder_id=initial_drill_remainder_id, from_qty=Decimal("20"),
        direct_qty=Decimal("60"), run_id="spg-e2e", stage="2",
    )
    drill_return_id = await _complete_with_return(
        client, headers, drill_task.id,
        good=Decimal("70"), defect=Decimal("5"),
        return_qty=Decimal("5"), run_id="spg-e2e", stage="2",
    )
    assert drill_return_id is not None

    # SPG-RAW: still just the original 20 (consume path stayed the same).
    raw_items = (await client.get(f"/api/spg/{spg_raw.id}/remainders")).json()
    assert len(raw_items) == 1
    assert raw_items[0]["remainder_quantity"] == 20

    # SPG-WIP: 1 remainder, qty 5.
    wip_items = (await client.get(f"/api/spg/{spg_wip.id}/remainders")).json()
    assert len(wip_items) == 1
    assert wip_items[0]["remainder_quantity"] == 5
    assert wip_items[0]["spg_code"] == spg_wip.code

    # Transfer 70 from DRILL to SHOT
    await _transfer_to_next(
        client, headers, drill_task.id,
        quantity=Decimal("70"), run_id="spg-e2e", stage="2",
    )

    # ── 6. Step 3 (SHOT) — 5 from DRILL remainder + 65 direct, complete 60+5, return 5 ─
    await _issue_mixed(
        client, headers, shot_task.id,
        from_remainder_id=drill_return_id, from_qty=Decimal("5"),
        direct_qty=Decimal("65"), run_id="spg-e2e", stage="3",
    )
    shot_return_id = await _complete_with_return(
        client, headers, shot_task.id,
        good=Decimal("60"), defect=Decimal("5"),
        return_qty=Decimal("5"), run_id="spg-e2e", stage="3",
    )
    assert shot_return_id is not None

    # SPG-WIP: SHOT remainder 5 (DRILL was fully consumed)
    wip_items = (await client.get(f"/api/spg/{spg_wip.id}/remainders")).json()
    assert len(wip_items) == 1
    assert wip_items[0]["remainder_quantity"] == 5
    assert wip_items[0]["spg_code"] == spg_wip.code

    # Transfer 60 from SHOT to ANOD
    await _transfer_to_next(
        client, headers, shot_task.id,
        quantity=Decimal("60"), run_id="spg-e2e", stage="3",
    )

    # ── 7. Step 4 (ANOD) — direct 60, complete 60, no return ──────────────
    await _issue_mixed(
        client, headers, anod_task.id,
        direct_qty=Decimal("60"), run_id="spg-e2e", stage="4",
    )
    await _complete_with_return(
        client, headers, anod_task.id,
        good=Decimal("60"), defect=Decimal("0"),
        return_qty=Decimal("0"), run_id="spg-e2e", stage="4",
    )

    # Transfer 60 from ANOD to WIP
    await _transfer_to_next(
        client, headers, anod_task.id,
        quantity=Decimal("60"), run_id="spg-e2e", stage="4",
    )

    # ── 8. Step 5 (WIP) — direct 60, complete 50+5, return 5 ──────────────
    await _issue_mixed(
        client, headers, wip_task.id,
        direct_qty=Decimal("60"), run_id="spg-e2e", stage="5",
    )
    wip_return_id = await _complete_with_return(
        client, headers, wip_task.id,
        good=Decimal("50"), defect=Decimal("5"),
        return_qty=Decimal("5"), run_id="spg-e2e", stage="5",
    )
    assert wip_return_id is not None

    # SPG-WIP: SHOT 5 + WIP 5 = 10, 2 remainders
    wip_items = (await client.get(f"/api/spg/{spg_wip.id}/remainders")).json()
    assert len(wip_items) == 2
    assert sum(r["remainder_quantity"] for r in wip_items) == 10

    # Transfer 50 from WIP to PACK
    await _transfer_to_next(
        client, headers, wip_task.id,
        quantity=Decimal("50"), run_id="spg-e2e", stage="5",
    )

    # ── 9. Step 6 (PACK, final) — direct 50, complete 50, final-release 50 ─
    await _issue_mixed(
        client, headers, pack_task.id,
        direct_qty=Decimal("50"), run_id="spg-e2e", stage="6",
    )
    resp = await client.post(
        f"/api/shopfloor/tasks/{pack_task.id}/complete",
        json={
            "good_quantity": "50",
            "defect_quantity": "0",
            "idempotency_key": "spg-e2e:stage6:complete",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    resp = await client.post(
        f"/api/shopfloor/tasks/{pack_task.id}/final-release",
        json={"quantity": "50", "idempotency_key": "spg-e2e:stage6:final-release"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    # ── 10. Final assertions on SPGs ──────────────────────────────────────
    # SPG-RAW: only the original 50-seed remainder (now 20 after step 1 consumed 30).
    # No new return-remainders ever landed here.
    final_raw_items = (await client.get(f"/api/spg/{spg_raw.id}/remainders")).json()
    assert len(final_raw_items) == 1
    assert final_raw_items[0]["remainder_quantity"] == 20
    assert final_raw_items[0]["source"] == "manual"

    # SPG-WIP: two task-source remainders (SHOT 5 + WIP 5).
    final_wip_items = (await client.get(f"/api/spg/{spg_wip.id}/remainders")).json()
    assert len(final_wip_items) == 2
    assert sum(r["remainder_quantity"] for r in final_wip_items) == 10
    assert all(r["source"] == "task" for r in final_wip_items)

    # Snapshots
    snap_raw = (await client.get(f"/api/spg/{spg_raw.id}/snapshot")).json()
    assert snap_raw["totals"]["spg_available"] == 20
    # SPG-RAW only contains the RAW section, so totals are scoped to that section:
    # planned 100, completed 80 (5 defect + 15 in_work, but only "complete" movement counts).
    assert snap_raw["totals"]["planned"] == 100
    assert snap_raw["totals"]["completed"] == 80

    snap_wip = (await client.get(f"/api/spg/{spg_wip.id}/snapshot")).json()
    assert snap_wip["totals"]["spg_available"] == 10

    # ── 11. Remainder history drill-down on a WIP return ──────────────────
    history = (
        await client.get(f"/api/spg/{spg_wip.id}/remainders/{shot_return_id}/history")
    ).json()

    assert history["remainder"]["id"] == shot_return_id
    assert history["remainder"]["source"] == "task"
    assert history["remainder"]["remainder_quantity"] == 5

    # Origin task must be our SHOT task
    assert history["origin"] is not None
    assert history["origin"]["task_id"] == shot_task.id
    assert history["origin"]["sequence"] == 3

    # Route snapshot is complete (all 6 steps)
    assert history["route"] is not None
    assert history["route"]["route_id"] == ctx["route"].id
    assert len(history["route"]["steps"]) == 6
    assert [s["sequence"] for s in history["route"]["steps"]] == [1, 2, 3, 4, 5, 6]

    # Completed stages on this return include the SHOT task's own step (3)
    # plus all earlier ones (1, 2) — `completed_stages` is built from steps
    # up to *and including* the source task's line.sequence.
    completed_seqs = sorted(s["sequence"] for s in history["completed_stages"])
    assert completed_seqs == [1, 2, 3]

    # Movement history contains our issue, complete, return for this product
    movement_types = {m["movement_type"] for m in history["movements"]}
    assert "return_to_stock" in movement_types
    assert "issue_to_work" in movement_types
    assert "complete" in movement_types

    return_movements = [m for m in history["movements"] if m["movement_type"] == "return_to_stock"]
    assert any(m["task_id"] == shot_task.id for m in return_movements)


# ─── additional small tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_spg_consume_remainder_allows_going_negative(client, session) -> None:
    """consume_remainder is allowed to push remainder_quantity below zero.

    A user can over-issue against a remainder (e.g. when fixing shortages
    post-factum) — the remainder should not block this, and `consumed_at`
    must NOT be set when the result is non-zero.
    """
    user = await _make_user(session, "consume-neg@test.local")
    headers = _auth_headers(user)

    ctx = await _make_product_with_route_and_spgs(
        session, sku="FG-SPG-CONSUME-NEG", planned_qty=Decimal("20")
    )
    spg_raw = ctx["spg_raw"]
    sections = ctx["sections"]

    # Seed 50 into SPG-RAW
    in_resp = await client.post(
        f"/api/spg/{spg_raw.id}/manual-operation",
        json={
            "product_id": ctx["product"].id,
            "section_id": sections[0].id,
            "operation_type": "in",
            "quantity": 50,
        },
        headers=headers,
    )
    assert in_resp.status_code == 200
    remainder_id = int(in_resp.json()["remainder_id"])

    # Take to work → first task (RAW) is `ready`
    take_resp = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [ctx["position"].id]},
        headers=headers,
    )
    assert take_resp.status_code == 200
    tasks = await _get_tasks_by_sequence(session, ctx["position"].id)
    raw_task = tasks[0]

    # Consume 70 from a 50-quantity remainder → should succeed with qty = -20
    resp = await client.post(
        "/api/shopfloor/remainders/consume",
        json={
            "remainder_id": remainder_id,
            "task_id": raw_task.id,
            "quantity": "70",
            "idempotency_key": "consume-neg:1",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["remainder_id"] == remainder_id
    assert body["task_id"] == raw_task.id

    # Verify in DB
    remainder = await session.get(SpgRemainder, remainder_id)
    assert remainder.remainder_quantity == Decimal("-20")
    # The endpoint must NOT mark the remainder consumed when it's negative
    assert remainder.consumed_at is None
    assert remainder.consumed_by_task_id is None

    # SPG snapshot reflects the negative total
    snap = (await client.get(f"/api/spg/{spg_raw.id}/snapshot")).json()
    # The snapshot's totals.sum sums the raw remainder_quantity values,
    # so a single -20 remainder shows up as -20 (no sign clamp here).
    assert snap["totals"]["spg_available"] == -20


@pytest.mark.asyncio
async def test_spg_manual_operation_balances_negative_remainders(client, session) -> None:
    """A manual 'in' operation brings a negative remainder back up.

    The same remainder row is reused (FIFO) when adding positive quantity,
    so the user sees a single, growing row rather than fragmented records.
    """
    user = await _make_user(session, "manual-fix@test.local")
    headers = _auth_headers(user)

    ctx = await _make_product_with_route_and_spgs(
        session, sku="FG-SPG-MANUAL-FIX", planned_qty=Decimal("20")
    )
    spg_raw = ctx["spg_raw"]
    sections = ctx["sections"]

    # 1) Seed 50, take to work, over-consume to drive remainder to -20
    in_resp = await client.post(
        f"/api/spg/{spg_raw.id}/manual-operation",
        json={
            "product_id": ctx["product"].id,
            "section_id": sections[0].id,
            "operation_type": "in",
            "quantity": 50,
        },
        headers=headers,
    )
    assert in_resp.status_code == 200
    remainder_id = int(in_resp.json()["remainder_id"])

    take_resp = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [ctx["position"].id]},
        headers=headers,
    )
    assert take_resp.status_code == 200
    tasks = await _get_tasks_by_sequence(session, ctx["position"].id)
    raw_task = tasks[0]

    consume_resp = await client.post(
        "/api/shopfloor/remainders/consume",
        json={
            "remainder_id": remainder_id,
            "task_id": raw_task.id,
            "quantity": "70",
            "idempotency_key": "manual-fix:consume",
        },
        headers=headers,
    )
    assert consume_resp.status_code == 200

    # Sanity: remainder is -20
    neg_rem = await session.get(SpgRemainder, remainder_id)
    assert neg_rem.remainder_quantity == Decimal("-20")

    # 2) Apply manual in 30 → remainder should be -20 + 30 = 10
    fix_resp = await client.post(
        f"/api/spg/{spg_raw.id}/manual-operation",
        json={
            "product_id": ctx["product"].id,
            "section_id": sections[0].id,
            "operation_type": "in",
            "quantity": 30,
            "reason": "выравнивание остатков",
        },
        headers=headers,
    )
    assert fix_resp.status_code == 200, fix_resp.text
    assert fix_resp.json()["remainder_id"] == remainder_id  # same row reused
    assert fix_resp.json()["new_remainder_quantity"] == 10

    # DB row reflects the balance
    final_rem = await session.get(SpgRemainder, remainder_id)
    assert final_rem.remainder_quantity == Decimal("10")
    assert final_rem.consumed_at is None

    # List endpoint shows the same single row
    list_resp = await client.get(f"/api/spg/{spg_raw.id}/remainders")
    assert list_resp.status_code == 200
    items = list_resp.json()
    matched = [r for r in items if r["id"] == remainder_id]
    assert len(matched) == 1
    assert matched[0]["remainder_quantity"] == 10
