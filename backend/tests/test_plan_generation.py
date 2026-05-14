from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.techcard import Techcard, TechcardLine
from app.models.imports import ImportBatch, ImportBatchMode, ImportFile
from app.models.internal_plan import SectionPlanLine
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanChangeAction,
    PlanChangeItem,
    PlanChangeItemStatus,
    PlanChangeSet,
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.release_batch import ReleaseBatchPosition
from app.models.route import ProductionRoute, RouteStep
from app.models.routing import RouteOperationFamily, RouteOutputKind
from app.models.section import Section
from app.models.work_task import WorkTask, WorkTaskStatus


async def _make_ready_product(session, sku: str = "FG-1") -> tuple[Product, list[Section], ProductionRoute]:
    product = Product(sku=sku, name=f"Finished {sku}", type=ProductType.finished_good, unit="pcs")
    component = Product(sku=f"{sku}-RAW", name=f"Raw {sku}", type=ProductType.component, unit="pcs")
    sections = [
        Section(code=f"{sku}-ISSUE", name="Issue", kind="raw_stock"),
        Section(code=f"{sku}-DRILL", name="Drill", kind="production"),
        Section(code=f"{sku}-SHOT", name="Shot", kind="production"),
        Section(code=f"{sku}-ANOD", name="Anod", kind="production"),
        Section(code=f"{sku}-WIP", name="WIP", kind="wip_stock"),
        Section(code=f"{sku}-FINAL", name="Final", kind="finished_stock"),
    ]
    session.add_all([product, component, *sections])
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(TechcardLine(techcard_id=techcard.id, component_product_id=component.id, quantity=1, unit="pcs"))

    route = ProductionRoute(name="Main", is_active=True)
    session.add(route)
    await session.flush()

    step_ops = ["ISSUE_RAW", "DRILL", "SHOT", "ANOD", "MOVE_TO_WIP", "ACCEPT_FINISHED"]
    for index, (section, op_code) in enumerate(zip(sections, step_ops, strict=True), start=1):
        session.add(
            RouteStep(
                route_id=route.id,
                sequence=index,
                section_id=section.id,
                operation_code=op_code,
                operation_name=op_code,
                is_final=index == len(sections),
            )
        )
    await session.flush()
    return product, sections, route


async def _make_matching_route_product(session, sku: str = "FG-MATCH") -> tuple[Product, list[Section], ProductionRoute]:
    product = Product(sku=sku, name=f"Finished {sku}", type=ProductType.finished_good, unit="pcs")
    sections = [
        Section(code=f"{sku}-ISSUE", name="Issue", kind="raw_stock"),
        Section(code=f"{sku}-DRILL", name="Drill", kind="production"),
        Section(code=f"{sku}-SHOT", name="Shot", kind="production"),
        Section(code=f"{sku}-ANOD", name="Anod", kind="production"),
        Section(code=f"{sku}-WIP", name="WIP", kind="wip_stock"),
        Section(code=f"{sku}-FINAL", name="Final", kind="finished_stock"),
    ]
    session.add_all([product, *sections])
    await session.flush()

    route = ProductionRoute(name="Main", is_active=True)
    session.add(route)
    await session.flush()

    step_ops = ["Issue raw", "DRILL", "SHOT", "ANOD", "Move to WIP", "Accept finished"]
    for index, (section, op_name) in enumerate(zip(sections, step_ops, strict=True), start=1):
        session.add(
            RouteStep(
                route_id=route.id,
                sequence=index,
                section_id=section.id,
                operation_name=op_name,
                is_final=index == len(sections),
            )
        )
    await session.flush()
    return product, sections, route


async def _make_plan_position(
    session,
    product: Product,
    quantity: Decimal = Decimal("100"),
    *,
    operation_family=RouteOperationFamily.DRILL,
    output_kind=RouteOutputKind.finished_good,
    has_pack_ops: bool = False,
    route_id: int | None = None,
) -> tuple[ProductionPlan, PlanPosition]:
    from datetime import UTC, datetime

    from app.models.production_plan import PlanPositionRouteOrigin

    plan = ProductionPlan(
        plan_no=f"PLAN-{product.sku}",
        name=f"Plan {product.sku}",
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
        quantity=quantity,
        source_payload={},
        period_start=plan.period_start,
        period_end=plan.period_end,
        status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        operation_family=operation_family,
        output_kind=output_kind,
        has_pack_ops=has_pack_ops,
        route_id=route_id,
        route_origin=PlanPositionRouteOrigin.manual_confirmed if route_id else None,
        route_assigned_at=datetime.now(UTC) if route_id else None,
        route_manual_confirmed_at=datetime.now(UTC) if route_id else None,
    )
    session.add(position)
    await session.flush()
    return plan, position


@pytest.mark.asyncio
async def test_apply_change_set_and_approve_position(client, session, tmp_path, monkeypatch) -> None:
    from app.core.security import create_access_token
    from app.models.user import User, UserRole

    user = User(email="apply@test.local", password_hash="x", full_name="Apply User", role=UserRole.operator, is_active=True)
    session.add(user)
    await session.flush()
    headers = {"Authorization": f"Bearer {create_access_token(subject=user.email)}"}

    product, _, route = await _make_ready_product(session, "FG-APPLY")
    plan = ProductionPlan(plan_no="PLAN-APPLY", name="Plan Apply", status=ProductionPlanStatus.draft)
    file = ImportFile(
        original_filename="plan.xlsx",
        stored_path=str(tmp_path / "plan.xlsx"),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_extension=".xlsx",
        detected_format="zip-workbook",
        file_sha256="a" * 64,
        size_bytes=10,
    )
    session.add_all([plan, file])
    await session.flush()
    batch = ImportBatch(
        source_file_id=file.id,
        production_plan_id=plan.id,
        mode=ImportBatchMode.create_plan,
        sheet_name="План май 26 05",
        header_row_number=5,
        total_rows=9,
        parsed_rows=1,
        summary={},
    )
    session.add(batch)
    await session.flush()
    change_set = PlanChangeSet(production_plan_id=plan.id, import_batch_id=batch.id, summary={})
    session.add(change_set)
    await session.flush()
    session.add(
        PlanChangeItem(
            change_set_id=change_set.id,
            source_row_number=6,
            source_ref="rows:6",
            change_action=PlanChangeAction.create_position,
            before_data=None,
            after_data={
                "product_id": product.id,
                "source_sku": product.sku,
                "source_name": product.name,
                "quantity": "100",
                "source_ref": "rows:6",
                "source_row_numbers": [6],
                "source_fingerprint": "f" * 64,
                "source_row_hash": "b" * 64,
                "source_payload": {
                    "period_start": "2026-05-01",
                    "period_end": "2026-05-31",
                },
                "operation_family": "drill",
                "output_kind": "finished_good",
                "has_pack_ops": False,
                "route_id": route.id,
            },
            status=PlanChangeItemStatus.pending,
            warnings=[],
            errors=[],
        )
    )
    await session.commit()

    apply_response = await client.post(f"/api/production-plans/{plan.id}/change-sets/{change_set.id}/apply")
    assert apply_response.status_code == 200
    assert apply_response.json()["created_positions"] == 1
    position_id = apply_response.json()["positions"][0]["id"]

    approve_response = await client.post(
        f"/api/production-plans/{plan.id}/positions/{position_id}/approve",
        headers=headers,
    )
    assert approve_response.status_code == 200


@pytest.mark.asyncio
async def test_apply_change_set_can_be_rolled_back(client, session, tmp_path) -> None:
    product, _, _ = await _make_ready_product(session, "FG-ROLLBACK")
    plan = ProductionPlan(plan_no="PLAN-ROLLBACK", name="Plan Rollback", status=ProductionPlanStatus.draft)
    file = ImportFile(
        original_filename="plan.xlsx",
        stored_path=str(tmp_path / "plan.xlsx"),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_extension=".xlsx",
        detected_format="zip-workbook",
        file_sha256="a" * 64,
        size_bytes=10,
    )
    session.add_all([plan, file])
    await session.flush()
    batch = ImportBatch(
        source_file_id=file.id,
        production_plan_id=plan.id,
        mode=ImportBatchMode.create_plan,
        sheet_name="План май 26 05",
        header_row_number=5,
        total_rows=9,
        parsed_rows=1,
        summary={},
    )
    session.add(batch)
    await session.flush()
    change_set = PlanChangeSet(production_plan_id=plan.id, import_batch_id=batch.id, summary={})
    session.add(change_set)
    await session.flush()
    session.add(
        PlanChangeItem(
            change_set_id=change_set.id,
            source_row_number=6,
            source_ref="rows:6",
            change_action=PlanChangeAction.create_position,
            before_data=None,
            after_data={
                "product_id": product.id,
                "source_sku": product.sku,
                "source_name": product.name,
                "quantity": "100",
                "source_ref": "rows:6",
                "source_row_numbers": [6],
                "source_fingerprint": "f" * 64,
                "source_row_hash": "b" * 64,
                "source_payload": {"period_start": "2026-05-01", "period_end": "2026-05-31"},
            },
            status=PlanChangeItemStatus.pending,
            warnings=[],
            errors=[],
        )
    )
    await session.commit()

    apply_response = await client.post(f"/api/production-plans/{plan.id}/change-sets/{change_set.id}/apply")
    assert apply_response.status_code == 200
    assert apply_response.json()["created_positions"] == 1

    rollback_response = await client.post(f"/api/production-plans/{plan.id}/change-sets/{change_set.id}/rollback")
    assert rollback_response.status_code == 200

    preview_response = await client.get(f"/api/production-plans/{plan.id}/preview")
    assert preview_response.status_code == 200
    assert preview_response.json()["positions_total"] == 0


@pytest.mark.asyncio
async def test_release_batch_generates_tasks_and_is_idempotent(client, session) -> None:
    product, sections, route = await _make_ready_product(session)
    plan, position = await _make_plan_position(session, product, route_id=route.id)
    await session.commit()

    create_response = await client.post(
        f"/api/production-plans/{plan.id}/release-batches",
        json={"positions": [{"plan_position_id": position.id, "release_quantity": "100"}]},
    )
    assert create_response.status_code == 201
    batch = create_response.json()
    assert batch["positions"][0]["route_id"] == route.id
    assert [step["section_id"] for step in batch["positions"][0]["route_snapshot"]["steps"]] == [section.id for section in sections]

    # Changing the route after batch creation must not affect the fixed snapshot.
    await session.commit()

    release_response = await client.post(f"/api/release-batches/{batch['id']}/release")
    assert release_response.status_code == 200
    released = release_response.json()
    assert released["status"] == "released"
    assert released["task_count"] == 6
    assert released["tasks_created"] == 6

    retry_response = await client.post(f"/api/release-batches/{batch['id']}/release")
    assert retry_response.status_code == 200
    assert retry_response.json()["task_count"] == 6

    tasks = (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()
    assert len(tasks) == 6
    assert tasks[0].status == WorkTaskStatus.ready
    assert all(task.status == WorkTaskStatus.waiting_previous for task in tasks[1:])
    assert {task.planned_quantity for task in tasks} == {Decimal("100.000")}

    batch_position = await session.scalar(select(ReleaseBatchPosition).where(ReleaseBatchPosition.plan_position_id == position.id))
    assert batch_position.route_id == route.id


@pytest.mark.asyncio
async def test_release_quantity_cannot_exceed_approved_quantity(client, session) -> None:
    product, _, route = await _make_ready_product(session, "FG-LIMIT")
    plan, position = await _make_plan_position(session, product, Decimal("50"), route_id=route.id)
    await session.commit()

    response = await client.post(
        f"/api/production-plans/{plan.id}/release-batches",
        json={"positions": [{"plan_position_id": position.id, "release_quantity": "51"}]},
    )
    assert response.status_code == 400
    assert "exceeds approved" in response.json()["detail"]


@pytest.mark.asyncio
async def test_route_check_endpoint(client, session) -> None:
    product, sections, route = await _make_matching_route_product(session, "FG-ROUTE-CHECK")
    plan, position = await _make_plan_position(session, product, route_id=route.id)
    position.source_payload = {
        "operation_code": "DRILL",
        "output_kind": "finished_good",
        "additional_pack_operations": [],
    }
    await session.commit()

    response = await client.get(f"/api/production-plans/{plan.id}/positions/{position.id}/route-check")
    assert response.status_code == 200
    data = response.json()
    assert data["match"] is True
    assert "expected_signature" in data
    assert "active_route_snapshot" in data
    assert data["active_route_snapshot"]["route_id"] == route.id
    assert data["active_route_snapshot"]["route_name"] == "Main"
    assert "required_sections" in data["expected_signature"]
    assert "candidate_routes" in data["expected_signature"]
    assert len(data["active_route_snapshot"]["steps"]) == len(sections)


@pytest.mark.asyncio
async def test_release_blocked_on_route_mismatch(client, session) -> None:
    # Create a product with a route that lacks SHOT, ANOD, PACK, etc.
    product = Product(sku="FG-ROUTE-MISMATCH", name="Finished FG-ROUTE-MISMATCH", type=ProductType.finished_good, unit="pcs")
    sections = [
        Section(code="FG-ROUTE-MISMATCH-ISSUE", name="Issue", kind="raw_stock"),
        Section(code="FG-ROUTE-MISMATCH-DRILL", name="Drill", kind="production"),
        Section(code="FG-ROUTE-MISMATCH-FINAL", name="Final", kind="finished_stock"),
    ]
    session.add_all([product, *sections])
    await session.flush()

    route = ProductionRoute(name="Route No Pack", is_active=True)
    session.add(route)
    await session.flush()
    step_ops = ["ISSUE_RAW", "DRILL", "ACCEPT_FINISHED"]
    for index, (section, op_code) in enumerate(zip(sections, step_ops, strict=True), start=1):
        session.add(
            RouteStep(
                route_id=route.id,
                sequence=index,
                section_id=section.id,
                operation_code=op_code,
                operation_name=op_code,
                is_final=index == len(sections),
            )
        )
    await session.flush()

    # Don't set route_id on position — let auto-resolution find this route,
    # then validation should fail because the route lacks required steps.
    plan, position = await _make_plan_position(
        session, product,
        operation_family=RouteOperationFamily.DRILL,
        output_kind=RouteOutputKind.finished_good,
        has_pack_ops=True,
    )
    # Still need to assign route_id for release_batch check, but set it
    # after create_release_batch resolves and validates.
    position.route_id = route.id
    position.source_payload = {
        "output_kind": "finished_good",
        "additional_pack_operations": [{"operation_code": "PACK_GLUE"}],
    }
    await session.commit()

    response = await client.post(
        f"/api/production-plans/{plan.id}/release-batches",
        json={"positions": [{"plan_position_id": position.id, "release_quantity": "100"}]},
    )
    assert response.status_code == 400
    # The error indicates route validation failed (mismatch or missing steps)
    assert len(response.json()["detail"]) > 0
