"""Pagination, total, search and sort for GET /api/production-plans/all-positions."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)


async def _make_plan(session: AsyncSession, *, plan_no: str = "PLAN-PAGE") -> ProductionPlan:
    plan = ProductionPlan(
        plan_no=plan_no,
        name=f"Plan {plan_no}",
        status=ProductionPlanStatus.draft,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()
    return plan


async def _make_product(session: AsyncSession, sku: str, *, name: str | None = None) -> Product:
    product = Product(
        sku=sku,
        name=name or sku,
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
    )
    session.add(product)
    await session.flush()
    return product


async def _seed_planning_positions(
    session: AsyncSession,
    *,
    count: int,
    sku_prefix: str = "PLAN-SKU",
    name_prefix: str = "Plan item",
    status: PlanPositionStatus = PlanPositionStatus.draft,
    validation_status: PlanPositionValidationStatus = PlanPositionValidationStatus.valid,
    start_row: int = 1,
) -> tuple[ProductionPlan, list[PlanPosition]]:
    plan = await _make_plan(session, plan_no=f"PLAN-{sku_prefix}")
    positions: list[PlanPosition] = []
    for i in range(count):
        sku = f"{sku_prefix}-{i:03d}"
        product = await _make_product(session, sku, name=f"Product {sku}")
        pos = PlanPosition(
            production_plan_id=plan.id,
            product_id=product.id,
            source_type=PlanSourceType.manual,
            source_sku=sku,
            source_name=f"{name_prefix} {i:03d}",
            quantity=Decimal(str(10 + i)),
            source_payload={},
            status=status,
            validation_status=validation_status,
            validation_errors=[],
            source_row_number=start_row + i,
            period_start=plan.period_start,
            period_end=plan.period_end,
            has_pack_ops=False,
        )
        session.add(pos)
        positions.append(pos)
    await session.commit()
    return plan, positions


@pytest.mark.asyncio
async def test_all_positions_default_limit_returns_total(client, session: AsyncSession):
    await _seed_planning_positions(session, count=65, sku_prefix="PAGE-DEF")

    resp = await client.get("/api/production-plans/all-positions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["positions"]) == 50
    assert body["total"] == 65
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.asyncio
async def test_all_positions_offset_pagination(client, session: AsyncSession):
    await _seed_planning_positions(session, count=75, sku_prefix="PAGE-OFF")

    first = await client.get("/api/production-plans/all-positions?limit=50&offset=0")
    second = await client.get("/api/production-plans/all-positions?limit=50&offset=50")
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    first_ids = {pos["id"] for pos in first.json()["positions"]}
    second_ids = {pos["id"] for pos in second.json()["positions"]}
    assert len(first_ids) == 50
    assert len(second_ids) == 25
    assert first_ids.isdisjoint(second_ids)
    assert first.json()["total"] == 75
    assert second.json()["total"] == 75


@pytest.mark.asyncio
async def test_all_positions_search_finds_record_on_second_page(client, session: AsyncSession):
    await _seed_planning_positions(session, count=60, sku_prefix="PAGE-SRCH")
    plan = await _make_plan(session, plan_no="PLAN-MARKER")
    product = await _make_product(session, "UNIQUE-PLAN-MARKER-42", name="Marker product")
    marker = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku="UNIQUE-PLAN-MARKER-42",
        source_name="Special marker position",
        quantity=Decimal("1"),
        source_payload={},
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        source_row_number=9999,
        period_start=plan.period_start,
        period_end=plan.period_end,
        has_pack_ops=False,
    )
    session.add(marker)
    await session.commit()

    resp = await client.get(
        "/api/production-plans/all-positions"
        "?search=UNIQUE-PLAN-MARKER-42&limit=50&offset=0"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["positions"]) == 1
    assert body["positions"][0]["source_sku"] == "UNIQUE-PLAN-MARKER-42"


@pytest.mark.asyncio
async def test_all_positions_sort_by_source_sku(client, session: AsyncSession):
    plan = await _make_plan(session, plan_no="PLAN-SORT")
    skus = ["PLAN-SORT-Z", "PLAN-SORT-A", "PLAN-SORT-M"]
    for idx, sku in enumerate(skus):
        product = await _make_product(session, sku)
        session.add(
            PlanPosition(
                production_plan_id=plan.id,
                product_id=product.id,
                source_type=PlanSourceType.manual,
                source_sku=sku,
                source_name=sku,
                quantity=Decimal("1"),
                source_payload={},
                status=PlanPositionStatus.draft,
                validation_status=PlanPositionValidationStatus.valid,
                validation_errors=[],
                source_row_number=idx + 1,
                period_start=plan.period_start,
                period_end=plan.period_end,
                has_pack_ops=False,
            )
        )
    await session.commit()

    resp = await client.get(
        "/api/production-plans/all-positions?sort_by=source_sku&sort_order=asc&limit=50"
    )
    assert resp.status_code == 200, resp.text
    returned_skus = [pos["source_sku"] for pos in resp.json()["positions"]]
    assert returned_skus == sorted(skus)


@pytest.mark.asyncio
async def test_all_positions_filter_validation_status(client, session: AsyncSession):
    await _seed_planning_positions(
        session,
        count=5,
        sku_prefix="PAGE-VAL-OK",
        validation_status=PlanPositionValidationStatus.valid,
    )
    await _seed_planning_positions(
        session,
        count=3,
        sku_prefix="PAGE-VAL-BAD",
        validation_status=PlanPositionValidationStatus.invalid,
    )

    resp = await client.get(
        "/api/production-plans/all-positions?validation_status=invalid&limit=50&offset=0"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert len(body["positions"]) == 3
    assert all(pos["validation_status"] == "invalid" for pos in body["positions"])


@pytest.mark.asyncio
async def test_all_positions_limit_max_validation(client, session: AsyncSession):
    resp = await client.get("/api/production-plans/all-positions?limit=1000")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_all_positions_excludes_non_planning_statuses(client, session: AsyncSession):
    plan = await _make_plan(session, plan_no="PLAN-STATUS")
    product = await _make_product(session, "PLAN-STATUS-ITEM")
    for pos_status in (
        PlanPositionStatus.draft,
        PlanPositionStatus.approved,
        PlanPositionStatus.released,
        PlanPositionStatus.cancelled,
    ):
        session.add(
            PlanPosition(
                production_plan_id=plan.id,
                product_id=product.id,
                source_type=PlanSourceType.manual,
                source_sku=f"SKU-{pos_status.value}",
                source_name=pos_status.value,
                quantity=Decimal("1"),
                source_payload={},
                status=pos_status,
                validation_status=PlanPositionValidationStatus.valid,
                validation_errors=[],
                source_row_number=1,
                period_start=plan.period_start,
                period_end=plan.period_end,
                has_pack_ops=False,
            )
        )
    await session.commit()

    resp = await client.get("/api/production-plans/all-positions?limit=50")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["positions"][0]["status"] == "draft"