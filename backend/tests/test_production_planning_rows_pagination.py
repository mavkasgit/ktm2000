"""Pagination, total, search and sort for GET /api/production-planning/rows."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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


async def _make_route(session: AsyncSession, sku: str) -> tuple[Product, ProductionRoute]:
    product = Product(
        sku=sku,
        name=f"Finished {sku}",
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
    )
    sections = [
        Section(code=f"{sku}-ISSUE", name="Issue", type="raw_stock", is_active=True, sort_order=0),
        Section(code=f"{sku}-FINAL", name="Final", type="finished_stock", is_active=True, sort_order=1),
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


async def _seed_positions(
    session: AsyncSession,
    *,
    count: int,
    sku_prefix: str = "EXEC-PAGE",
    marker_sku: str | None = None,
    marker_at_index: int | None = None,
) -> tuple[ProductionPlan, list[PlanPosition]]:
    product, route = await _make_route(session, sku_prefix)
    plan = ProductionPlan(
        plan_no=f"PLAN-{sku_prefix}",
        name=f"Plan {sku_prefix}",
        status=ProductionPlanStatus.approved,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()

    positions: list[PlanPosition] = []
    for index in range(count):
        sku = marker_sku if marker_at_index == index and marker_sku else f"{sku_prefix}-{index:04d}"
        pos = PlanPosition(
            production_plan_id=plan.id,
            product_id=product.id,
            source_type=PlanSourceType.manual,
            source_sku=sku,
            source_name=f"Product {sku}",
            quantity=Decimal("10"),
            source_payload={},
            status=PlanPositionStatus.approved,
            validation_status=PlanPositionValidationStatus.valid,
            validation_errors=[],
            period_start=plan.period_start,
            period_end=plan.period_end,
            has_pack_ops=False,
            route_id=route.id,
            source_row_number=index + 1,
        )
        session.add(pos)
        positions.append(pos)
    await session.commit()
    return plan, positions


@pytest.mark.asyncio
async def test_rows_default_limit_returns_total(client, session: AsyncSession):
    await _seed_positions(session, count=65, sku_prefix="EXEC-DEF")

    resp = await client.get("/api/production-planning/rows")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["rows"]) == 50
    assert body["total"] == 65
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.asyncio
async def test_rows_offset_pagination(client, session: AsyncSession):
    await _seed_positions(session, count=75, sku_prefix="EXEC-OFF")

    first = await client.get("/api/production-planning/rows?limit=50&offset=0")
    second = await client.get("/api/production-planning/rows?limit=50&offset=50")
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    first_ids = {row["plan_position_id"] for row in first.json()["rows"]}
    second_ids = {row["plan_position_id"] for row in second.json()["rows"]}
    assert len(first_ids) == 50
    assert len(second_ids) == 25
    assert first_ids.isdisjoint(second_ids)
    assert first.json()["total"] == 75
    assert second.json()["total"] == 75


@pytest.mark.asyncio
async def test_rows_search_finds_record_across_pages(client, session: AsyncSession):
    await _seed_positions(
        session,
        count=60,
        sku_prefix="EXEC-SEARCH",
        marker_sku="UNIQUE-EXEC-MARKER-42",
        marker_at_index=55,
    )

    resp = await client.get(
        "/api/production-planning/rows"
        "?search=UNIQUE-EXEC-MARKER-42&limit=50&offset=0"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["rows"]) == 1
    assert body["rows"][0]["source_sku"] == "UNIQUE-EXEC-MARKER-42"


@pytest.mark.asyncio
async def test_rows_sort_by_product_sku(client, session: AsyncSession):
    product_a, route_a = await _make_route(session, "EXEC-SORT-A")
    product_b, route_b = await _make_route(session, "EXEC-SORT-B")
    product_c, route_c = await _make_route(session, "EXEC-SORT-C")

    plan = ProductionPlan(
        plan_no="PLAN-EXEC-SORT",
        name="Plan EXEC SORT",
        status=ProductionPlanStatus.approved,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()

    for row_no, (product, route, sku) in enumerate(
        (
            (product_c, route_c, "CCC-SORT-SKU"),
            (product_a, route_a, "AAA-SORT-SKU"),
            (product_b, route_b, "BBB-SORT-SKU"),
        ),
        start=1,
    ):
        session.add(
            PlanPosition(
                production_plan_id=plan.id,
                product_id=product.id,
                source_type=PlanSourceType.manual,
                source_sku=sku,
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
                source_row_number=row_no,
            )
        )
    await session.commit()

    resp = await client.get(
        "/api/production-planning/rows"
        "?sort_by=product_sku&sort_order=asc&limit=50"
    )
    assert resp.status_code == 200, resp.text
    skus = [row["source_sku"] for row in resp.json()["rows"] if row["source_sku"].endswith("-SORT-SKU")]
    assert skus == ["AAA-SORT-SKU", "BBB-SORT-SKU", "CCC-SORT-SKU"]


@pytest.mark.asyncio
async def test_rows_limit_max_validation(client):
    resp = await client.get("/api/production-planning/rows?limit=1000")
    assert resp.status_code == 422