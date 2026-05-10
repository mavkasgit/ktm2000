from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

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
from app.models.techcard import Techcard, TechcardLine
from app.models.work_task import WorkTask


async def _make_product_with_route(session, sku: str = "FG-EXEC") -> tuple[Product, ProductionRoute]:
    product = Product(sku=sku, name=f"Finished {sku}", type=ProductType.finished_good, unit="pcs")
    sections = [
        Section(code=f"{sku}-CUT", name="Cut", kind="production"),
        Section(code=f"{sku}-ANOD", name="Anod", kind="production"),
        Section(code=f"{sku}-PACK", name="Pack", kind="production"),
    ]
    session.add_all([product, *sections])
    await session.flush()

    route = ProductionRoute(name=f"Route-{sku}", is_active=True)
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

    for idx, section in enumerate(sections, start=1):
        session.add(
            RouteStep(
                route_id=route.id,
                sequence=idx,
                section_id=section.id,
                operation_code=section.code,
                operation_name=section.name,
                is_final=idx == len(sections),
            )
        )
    await session.flush()
    return product, route


async def _make_plan(session, code: str = "EXEC") -> ProductionPlan:
    plan = ProductionPlan(
        plan_no=f"PLAN-{code}",
        name=f"Plan {code}",
        status=ProductionPlanStatus.approved,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()
    return plan


async def _make_position(
    session,
    *,
    plan_id: int,
    sku: str,
    name: str,
    quantity: Decimal = Decimal("100"),
    product_id: int | None = None,
    status: PlanPositionStatus = PlanPositionStatus.approved,
    row_num: int | None = None,
) -> PlanPosition:
    position = PlanPosition(
        production_plan_id=plan_id,
        product_id=product_id,
        source_type=PlanSourceType.manual,
        source_sku=sku,
        source_name=name,
        quantity=quantity,
        source_payload={},
        source_row_number=row_num,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        status=status,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
    )
    session.add(position)
    await session.flush()
    return position


@pytest.mark.asyncio
async def test_rows_detail_for_released_position_with_tasks(client, session) -> None:
    product, route = await _make_product_with_route(session, "FG-REL")
    plan = await _make_plan(session, "REL")
    position = await _make_position(
        session,
        plan_id=plan.id,
        sku=product.sku,
        name=product.name,
        quantity=Decimal("100"),
        product_id=product.id,
    )
    await session.commit()

    create_batch_response = await client.post(
        f"/api/production-plans/{plan.id}/release-batches",
        json={"positions": [{"plan_position_id": position.id, "release_quantity": "100"}]},
    )
    assert create_batch_response.status_code == 201
    batch_id = create_batch_response.json()["id"]

    release_response = await client.post(f"/api/release-batches/{batch_id}/release")
    assert release_response.status_code == 200

    tasks = (await session.execute(select(WorkTask).order_by(WorkTask.id))).scalars().all()
    assert tasks
    tasks[0].cached_completed_quantity = Decimal("30")
    tasks[0].cached_transferred_quantity = Decimal("20")
    tasks[0].cached_rejected_quantity = Decimal("5")
    await session.commit()

    response = await client.get(f"/api/production-planning/rows/{position.id}")
    assert response.status_code == 200
    data = response.json()

    assert data["plan_position_id"] == position.id
    assert data["route_id"] == route.id
    assert data["has_tasks"] is True
    assert data["not_started"] is False
    assert len(data["stages"]) == 3

    first_stage = data["stages"][0]
    assert first_stage["planned_quantity"] == 100.0
    assert first_stage["completed_quantity"] == 30.0
    assert first_stage["transferred_quantity"] == 20.0
    assert first_stage["rejected_quantity"] == 5.0
    assert first_stage["execution_percent"] == 30.0
    assert first_stage["transfer_percent"] == 20.0
    assert first_stage["reject_percent"] == 5.0


@pytest.mark.asyncio
async def test_rows_detail_for_not_started_position(client, session) -> None:
    product, route = await _make_product_with_route(session, "FG-NOSTART")
    plan = await _make_plan(session, "NOSTART")
    position = await _make_position(
        session,
        plan_id=plan.id,
        sku=product.sku,
        name=product.name,
        quantity=Decimal("50"),
        product_id=product.id,
    )
    await session.commit()

    response = await client.get(f"/api/production-planning/rows/{position.id}")
    assert response.status_code == 200
    data = response.json()

    assert data["route_id"] == route.id
    assert data["has_tasks"] is False
    assert data["not_started"] is True
    assert len(data["stages"]) == 3
    assert all(stage["not_started"] is True for stage in data["stages"])
    assert all(stage["planned_quantity"] == 50.0 for stage in data["stages"])
    assert all(stage["completed_quantity"] == 0.0 for stage in data["stages"])
    assert all(stage["execution_percent"] == 0.0 for stage in data["stages"])


@pytest.mark.asyncio
async def test_rows_detail_for_position_without_route(client, session) -> None:
    plan = await _make_plan(session, "NOROUTE")
    position = await _make_position(
        session,
        plan_id=plan.id,
        sku="FG-NOROUTE",
        name="No Route",
        quantity=Decimal("10"),
        product_id=None,
        status=PlanPositionStatus.draft,
    )
    await session.commit()

    response = await client.get(f"/api/production-planning/rows/{position.id}")
    assert response.status_code == 200
    data = response.json()

    assert data["route_id"] is None
    assert data["route_snapshot"] is None
    assert data["stages"] == []
    assert data["route_error"] == "route not found"


@pytest.mark.asyncio
async def test_rows_list_includes_mixed_position_statuses(client, session) -> None:
    product, _ = await _make_product_with_route(session, "FG-MIX")
    plan = await _make_plan(session, "MIX")

    draft = await _make_position(
        session,
        plan_id=plan.id,
        sku="FG-MIX-DRAFT",
        name="Draft",
        quantity=Decimal("10"),
        product_id=product.id,
        status=PlanPositionStatus.draft,
        row_num=1,
    )
    approved = await _make_position(
        session,
        plan_id=plan.id,
        sku="FG-MIX-APPROVED",
        name="Approved",
        quantity=Decimal("20"),
        product_id=product.id,
        status=PlanPositionStatus.approved,
        row_num=2,
    )
    released = await _make_position(
        session,
        plan_id=plan.id,
        sku="FG-MIX-RELEASED",
        name="Released",
        quantity=Decimal("30"),
        product_id=product.id,
        status=PlanPositionStatus.released,
        row_num=3,
    )
    await session.commit()

    response = await client.get("/api/production-planning/rows")
    assert response.status_code == 200
    rows = response.json()
    rows_by_id = {row["plan_position_id"]: row for row in rows}

    assert draft.id in rows_by_id
    assert approved.id in rows_by_id
    assert released.id in rows_by_id

    assert rows_by_id[draft.id]["position_status"] == "draft"
    assert rows_by_id[approved.id]["position_status"] == "approved"
    assert rows_by_id[released.id]["position_status"] == "released"
