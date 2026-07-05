"""Tests for GET /api/transfers/ready pagination (offset, limit, total, search)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
)
from app.models.techcard import Techcard, TechcardLine
from app.models.section import Section
from app.models.work_task import WorkTask
from app.stock import Reason, StockCommand, StockCommandService
from tests.stock.test_transfer_stage2 import _make_two_ghp_setup
from tests.test_integrity_invariants import _release_via_take_to_work


async def _complete_source_tasks(session, setup: dict) -> list[int]:
    """Complete all source-section tasks (must be released beforehand)."""
    sec1 = setup["sections"][0]

    stock = (
        await session.execute(select(Section).where(Section.code == "RDY-STK"))
    ).scalar_one_or_none()
    if stock is None:
        stock = Section(code="RDY-STK", name="Stock", type="raw_stock", is_active=True, sort_order=0)
        session.add(stock)
        await session.flush()

    tasks = (
        await session.execute(
            select(WorkTask)
            .where(WorkTask.section_id == sec1.id)
            .order_by(WorkTask.id)
        )
    ).scalars().all()

    svc = StockCommandService()
    for task in tasks:
        await svc.record(
            session,
            StockCommand(
                product_id=task.product_id,
                from_location_id=None,
                to_location_id=stock.id,
                quantity=task.planned_quantity,
                reason=Reason.MANUAL_IN,
                created_by=setup["user"].id,
            ),
        )
        await svc.record(
            session,
            StockCommand(
                product_id=task.product_id,
                from_location_id=stock.id,
                to_location_id=task.section_id,
                quantity=task.planned_quantity,
                reason=Reason.TRANSFER_RECEIVE,
                task_id=task.id,
                created_by=setup["user"].id,
            ),
        )
        await svc.record(
            session,
            StockCommand(
                product_id=task.product_id,
                from_location_id=task.section_id,
                to_location_id=task.section_id,
                quantity=task.planned_quantity,
                reason=Reason.COMPLETE,
                task_id=task.id,
                source_ref="test_seed",
                created_by=setup["user"].id,
            ),
        )
    await session.commit()
    return [task.id for task in tasks]


async def _seed_many_ready_tasks(session, client, count: int) -> dict:
    """Create *count* plan positions and complete their source tasks."""
    setup = await _make_two_ghp_setup(session, sku="RDY-PG", qty=Decimal("1"))
    plan = setup["plan"]
    route = setup["route"]

    for i in range(1, count):
        sku = f"RDY-PG-{i:03d}"
        product = Product(
            sku=sku,
            name=sku,
            type=ProductType.finished_good,
            unit="pcs",
            is_active=True,
        )
        session.add(product)
        await session.flush()
        tech = Techcard(product_id=product.id, version="v1", is_active=True)
        session.add(tech)
        await session.flush()
        session.add(
            TechcardLine(
                techcard_id=tech.id,
                component_product_id=product.id,
                quantity=Decimal("1"),
                unit="pcs",
            )
        )
        session.add(
            PlanPosition(
                production_plan_id=plan.id,
                product_id=product.id,
                source_type=PlanSourceType.manual,
                source_sku=product.sku,
                source_name=product.name,
                quantity=Decimal("1"),
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
        )
    await session.commit()

    positions = (
        await session.execute(
            select(PlanPosition)
            .where(PlanPosition.production_plan_id == plan.id)
            .order_by(PlanPosition.id)
        )
    ).scalars().all()

    for position in positions:
        await _release_via_take_to_work(client, position.id)

    task_ids = await _complete_source_tasks(session, setup)
    return {"setup": setup, "task_ids": task_ids}


@pytest.mark.asyncio
async def test_ready_empty_total_zero(client, session) -> None:
    response = await client.get("/api/transfers/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.asyncio
async def test_ready_offset_limit_pagination(client, session) -> None:
    seeded = await _seed_many_ready_tasks(session, client, count=3)
    sec1 = seeded["setup"]["sections"][0]

    first_page = await client.get(f"/api/transfers/ready?section_id={sec1.id}&limit=2&offset=0")
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert len(first_body["items"]) == 2
    assert first_body["total"] == 3
    assert first_body["limit"] == 2
    assert first_body["offset"] == 0

    second_page = await client.get(f"/api/transfers/ready?section_id={sec1.id}&limit=2&offset=2")
    assert second_page.status_code == 200
    second_body = second_page.json()
    assert len(second_body["items"]) == 1
    assert second_body["total"] == 3
    assert second_body["limit"] == 2
    assert second_body["offset"] == 2

    first_ids = {item["task_id"] for item in first_body["items"]}
    second_ids = {item["task_id"] for item in second_body["items"]}
    assert first_ids.isdisjoint(second_ids)


@pytest.mark.asyncio
async def test_ready_limit_max_validation(client, session) -> None:
    response = await client.get("/api/transfers/ready?limit=1000")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ready_search_by_sku(client, session) -> None:
    seeded = await _seed_many_ready_tasks(session, client, count=3)
    sec1 = seeded["setup"]["sections"][0]
    marker_sku = "RDY-PG-002"

    all_response = await client.get(f"/api/transfers/ready?section_id={sec1.id}")
    assert all_response.status_code == 200
    assert all_response.json()["total"] == 3

    search_response = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&search={marker_sku}"
    )
    assert search_response.status_code == 200
    search_body = search_response.json()
    assert search_body["total"] == 1
    assert len(search_body["items"]) == 1
    assert search_body["items"][0]["product_sku"] == marker_sku


@pytest.mark.asyncio
async def test_ready_search_finds_not_on_first_page(client, session) -> None:
    """Search must find a SKU that would not appear on page 1 with limit=2."""
    seeded = await _seed_many_ready_tasks(session, client, count=3)
    sec1 = seeded["setup"]["sections"][0]
    marker_sku = "RDY-PG-002"

    first_page = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&limit=2&offset=0"
    )
    assert first_page.status_code == 200
    first_skus = {item["product_sku"] for item in first_page.json()["items"]}
    assert marker_sku not in first_skus

    search_response = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&search={marker_sku}&limit=2&offset=0"
    )
    assert search_response.status_code == 200
    search_body = search_response.json()
    assert search_body["total"] == 1
    assert len(search_body["items"]) == 1
    assert search_body["items"][0]["product_sku"] == marker_sku


@pytest.mark.asyncio
async def test_ready_search_by_task_id(client, session) -> None:
    seeded = await _seed_many_ready_tasks(session, client, count=3)
    sec1 = seeded["setup"]["sections"][0]
    # Use the last task id to avoid accidental SKU substring matches (e.g. "1" in RDY-PG-001).
    task_id = seeded["task_ids"][-1]

    search_response = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&search={task_id}"
    )
    assert search_response.status_code == 200
    search_body = search_response.json()
    assert search_body["total"] == 1
    assert search_body["items"][0]["task_id"] == task_id


@pytest.mark.asyncio
async def test_ready_filter_product_sku_param(client, session) -> None:
    seeded = await _seed_many_ready_tasks(session, client, count=3)
    sec1 = seeded["setup"]["sections"][0]
    marker_sku = "RDY-PG-002"

    all_response = await client.get(f"/api/transfers/ready?section_id={sec1.id}")
    assert all_response.status_code == 200
    assert all_response.json()["total"] == 3

    filter_response = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&product_sku={marker_sku}"
    )
    assert filter_response.status_code == 200
    filter_body = filter_response.json()
    assert filter_body["total"] == 1
    assert len(filter_body["items"]) == 1
    assert filter_body["items"][0]["product_sku"] == marker_sku


@pytest.mark.asyncio
async def test_ready_sort_by_task_id(client, session) -> None:
    seeded = await _seed_many_ready_tasks(session, client, count=3)
    sec1 = seeded["setup"]["sections"][0]
    task_ids = sorted(seeded["task_ids"])

    asc_response = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&sort_by=task_id&sort_order=asc&limit=50"
    )
    assert asc_response.status_code == 200
    asc_body = asc_response.json()
    assert asc_body["total"] == 3
    asc_ids = [item["task_id"] for item in asc_body["items"]]
    assert asc_ids == task_ids

    desc_response = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&sort_by=task_id&sort_order=desc&limit=50"
    )
    assert desc_response.status_code == 200
    desc_body = desc_response.json()
    desc_ids = [item["task_id"] for item in desc_body["items"]]
    assert desc_ids == list(reversed(task_ids))