from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.bom import BOM, BOMLine
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
from app.models.section import Section
from app.models.work_task import WorkTask, WorkTaskStatus


async def _make_ready_product(session, sku: str = "FG-1") -> tuple[Product, list[Section], ProductionRoute]:
    product = Product(sku=sku, name=f"Finished {sku}", type=ProductType.finished_good, unit="pcs")
    component = Product(sku=f"{sku}-RAW", name=f"Raw {sku}", type=ProductType.component, unit="pcs")
    sections = [
        Section(code=f"{sku}-CUT", name="Cut"),
        Section(code=f"{sku}-COLOR", name="Color"),
        Section(code=f"{sku}-PACK", name="Pack"),
    ]
    session.add_all([product, component, *sections])
    await session.flush()

    bom = BOM(product_id=product.id, version="v1", is_active=True)
    session.add(bom)
    await session.flush()
    session.add(BOMLine(bom_id=bom.id, component_product_id=component.id, quantity=1, unit="pcs"))

    route = ProductionRoute(product_id=product.id, name="Main", version="v1", is_active=True)
    session.add(route)
    await session.flush()
    for index, section in enumerate(sections, start=1):
        session.add(
            RouteStep(
                route_id=route.id,
                sequence=index,
                section_id=section.id,
                operation_name=f"Step {index}",
                is_final=index == len(sections),
            )
        )
    await session.flush()
    return product, sections, route


async def _make_plan_position(session, product: Product, quantity: Decimal = Decimal("100")) -> tuple[ProductionPlan, PlanPosition]:
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
    )
    session.add(position)
    await session.flush()
    return plan, position


@pytest.mark.asyncio
async def test_apply_change_set_and_approve_position(client, session, tmp_path, monkeypatch) -> None:
    product, _, _ = await _make_ready_product(session, "FG-APPLY")
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
    position_id = apply_response.json()["positions"][0]["id"]

    approve_response = await client.post(f"/api/production-plans/{plan.id}/positions/{position_id}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_release_batch_generates_tasks_and_is_idempotent(client, session) -> None:
    product, sections, route = await _make_ready_product(session)
    plan, position = await _make_plan_position(session, product)
    await session.commit()

    create_response = await client.post(
        f"/api/production-plans/{plan.id}/release-batches",
        json={"positions": [{"plan_position_id": position.id, "release_quantity": "100"}]},
    )
    assert create_response.status_code == 201
    batch = create_response.json()
    assert batch["positions"][0]["route_id"] == route.id
    assert batch["positions"][0]["route_version"] == "v1"
    assert [step["section_id"] for step in batch["positions"][0]["route_snapshot"]["steps"]] == [section.id for section in sections]

    # Changing the route after batch creation must not affect the fixed snapshot.
    route.version = "v2"
    await session.commit()

    release_response = await client.post(f"/api/release-batches/{batch['id']}/release")
    assert release_response.status_code == 200
    released = release_response.json()
    assert released["status"] == "released"
    assert released["task_count"] == 3
    assert released["tasks_created"] == 3

    retry_response = await client.post(f"/api/release-batches/{batch['id']}/release")
    assert retry_response.status_code == 200
    assert retry_response.json()["task_count"] == 3

    tasks = (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()
    assert [task.status for task in tasks] == [
        WorkTaskStatus.ready,
        WorkTaskStatus.waiting_previous,
        WorkTaskStatus.waiting_previous,
    ]
    assert {task.planned_quantity for task in tasks} == {Decimal("100.000")}

    batch_position = await session.scalar(select(ReleaseBatchPosition).where(ReleaseBatchPosition.plan_position_id == position.id))
    assert batch_position.route_version == "v1"


@pytest.mark.asyncio
async def test_release_quantity_cannot_exceed_approved_quantity(client, session) -> None:
    product, _, _ = await _make_ready_product(session, "FG-LIMIT")
    plan, position = await _make_plan_position(session, product, Decimal("50"))
    await session.commit()

    response = await client.post(
        f"/api/production-plans/{plan.id}/release-batches",
        json={"positions": [{"plan_position_id": position.id, "release_quantity": "51"}]},
    )
    assert response.status_code == 400
    assert "exceeds approved" in response.json()["detail"]
