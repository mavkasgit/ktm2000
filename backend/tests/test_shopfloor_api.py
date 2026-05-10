from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

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
from app.models.section import Section
from app.models.techcard import Techcard, TechcardLine
from app.models.user import User, UserRole
from app.models.work_task import WorkTask
from app.models.internal_plan import SectionPlanLine


async def _make_user(session, email: str = "operator@test.local") -> User:
    user = User(email=email, password_hash="x", full_name="Operator", role=UserRole.operator, is_active=True)
    session.add(user)
    await session.flush()
    return user


async def _make_product_route_plan(session, sku: str = "FG-SHOP") -> tuple[Product, ProductionPlan, PlanPosition]:
    product = Product(sku=sku, name=f"Finished {sku}", type=ProductType.finished_good, unit="pcs")
    sections = [
        Section(code=f"{sku}-A", name="Step A", kind="production"),
        Section(code=f"{sku}-B", name="Step B", kind="production"),
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
    )
    session.add(pos)
    await session.commit()
    return product, plan, pos


async def _release_plan_position(client, plan_id: int, position_id: int) -> None:
    create_response = await client.post(
        f"/api/production-plans/{plan_id}/release-batches",
        json={"positions": [{"plan_position_id": position_id, "release_quantity": "100"}]},
    )
    assert create_response.status_code == 201
    batch_id = create_response.json()["id"]
    release_response = await client.post(f"/api/release-batches/{batch_id}/release")
    assert release_response.status_code == 200


@pytest.mark.asyncio
async def test_shopfloor_happy_path_with_discrepancy_link(client, session) -> None:
    user = await _make_user(session, "shopfloor1@test.local")
    _, plan, pos = await _make_product_route_plan(session, "FG-SF-1")
    token = create_access_token(subject=user.email)
    headers = {"Authorization": f"Bearer {token}"}

    await _release_plan_position(client, plan.id, pos.id)

    tasks = (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == pos.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()
    assert len(tasks) == 2
    first_task, second_task = tasks[0], tasks[1]

    issue_res = await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/issue",
        json={"quantity": "100"},
        headers=headers,
    )
    assert issue_res.status_code == 200

    complete_res = await client.post(
        f"/api/shopfloor/tasks/{first_task.id}/complete",
        json={"good_quantity": "80", "defect_quantity": "20", "defect_reason": "production_defect"},
        headers=headers,
    )
    assert complete_res.status_code == 200
    defect_id = complete_res.json()["defect_id"]
    assert defect_id is not None

    transfer_res = await client.post(
        "/api/shopfloor/transfers",
        json={"from_task_id": first_task.id, "to_task_id": second_task.id, "quantity": "80"},
        headers=headers,
    )
    assert transfer_res.status_code == 200
    transfer_id = transfer_res.json()["transfer_id"]

    accept_res = await client.post(
        f"/api/shopfloor/transfers/{transfer_id}/accept",
        json={"accepted_quantity": "70", "rejected_quantity": "10", "reason": "transfer_shortage"},
        headers=headers,
    )
    assert accept_res.status_code == 200
    discrepancy_id = accept_res.json()["discrepancy_id"]
    assert discrepancy_id is not None

    defect_details = await client.get(f"/api/shopfloor/defects/{defect_id}")
    assert defect_details.status_code == 200
    defect_item_id = defect_details.json()["items"][0]["id"]

    resolve_res = await client.post(
        f"/api/shopfloor/transfers/{transfer_id}/discrepancies/{discrepancy_id}/resolve-link",
        json={"defect_item_id": defect_item_id, "quantity": "10"},
        headers=headers,
    )
    assert resolve_res.status_code == 200
    assert resolve_res.json()["status"] == "resolved"

    transfer_details = await client.get(f"/api/shopfloor/transfers/{transfer_id}")
    assert transfer_details.status_code == 200
    assert transfer_details.json()["discrepancies"][0]["status"] == "resolved"

    stage_aggregates = await client.get(f"/api/shopfloor/plan-positions/{pos.id}/route-stage-aggregates")
    assert stage_aggregates.status_code == 200
    assert len(stage_aggregates.json()["stages"]) == 2


@pytest.mark.asyncio
async def test_shopfloor_over_issue_rejected(client, session) -> None:
    user = await _make_user(session, "shopfloor2@test.local")
    _, plan, pos = await _make_product_route_plan(session, "FG-SF-2")
    token = create_access_token(subject=user.email)
    headers = {"Authorization": f"Bearer {token}"}

    await _release_plan_position(client, plan.id, pos.id)
    task = (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == pos.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().first()
    assert task is not None

    res = await client.post(
        f"/api/shopfloor/tasks/{task.id}/issue",
        json={"quantity": "101"},
        headers=headers,
    )
    assert res.status_code == 400
    assert "exceeds available" in res.json()["detail"]
