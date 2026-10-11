"""Предупреждения импорта персистятся на позицию (#328).

Импортный проход кладёт предупреждения строки в ``plan_change_items.warnings``;
при применении change-set они должны дожить до ``plan_positions.validation_warnings``.
Правило статуса при этом не меняется: ``validation_status`` считается только по
ошибкам — позиция с предупреждением остаётся валидной (ADR-0066: предупреждения
берутся с элемента сета, а не пересчитываются валидацией).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from app.models.imports import ImportBatch, ImportBatchMode, ImportFile
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
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section
from sqlalchemy.ext.asyncio import AsyncSession

WARNING_CODE = "product_name_missing"
HANGER_WARNING = "hanger_quantity_not_set:2.7"


async def _make_ready_product(session: AsyncSession, sku: str) -> tuple[Product, ProductionRoute]:
    """Продукт + маршрут из трёх активных секций — позиция валидна."""
    product = Product(sku=sku, name=f"Finished {sku}", type=ProductType.finished_good, unit="pcs")
    sections = [
        Section(code=f"{sku}-CUT", name="Cut"),
        Section(code=f"{sku}-COLOR", name="Color"),
        Section(code=f"{sku}-PACK", name="Pack"),
    ]
    session.add_all([product, *sections])
    await session.flush()

    route = ProductionRoute(name=f"Route {sku}", is_active=True)
    session.add(route)
    await session.flush()
    for index, section in enumerate(sections, start=1):
        stage = RouteStage(
            route_id=route.id,
            sequence=index,
            section_id=section.id,
            is_final=index == len(sections),
        )
        session.add(stage)
        await session.flush()
        session.add(
            RouteOperation(
                route_stage_id=stage.id,
                sequence=1,
                operation_code=None,
                operation_name=f"Step {index}",
            )
        )
    await session.flush()
    return product, route


async def _make_plan_with_batch(session: AsyncSession, plan_no: str, tmp_path) -> tuple[ProductionPlan, ImportBatch]:
    plan = ProductionPlan(
        plan_no=plan_no,
        name=f"Plan {plan_no}",
        status=ProductionPlanStatus.draft,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
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
    return plan, batch


def _after_data(product: Product, route: ProductionRoute, *, row_number: int) -> dict:
    return {
        "product_id": product.id,
        "route_id": route.id,
        "source_sku": product.sku,
        "source_name": product.name,
        "quantity": "100",
        "source_ref": f"rows:{row_number}",
        "source_row_numbers": [row_number],
        "source_payload": {
            "period_start": "2026-05-01",
            "period_end": "2026-05-31",
        },
    }


async def _make_change_set(
    session: AsyncSession,
    plan: ProductionPlan,
    batch: ImportBatch,
    item_kwargs: dict,
) -> PlanChangeSet:
    change_set = PlanChangeSet(production_plan_id=plan.id, import_batch_id=batch.id, summary={})
    session.add(change_set)
    await session.flush()
    session.add(
        PlanChangeItem(
            change_set_id=change_set.id,
            status=PlanChangeItemStatus.pending,
            **{"warnings": [], "errors": [], **item_kwargs},
        )
    )
    await session.commit()
    return change_set


async def _apply(client, plan: ProductionPlan, change_set: PlanChangeSet) -> None:
    response = await client.post(
        f"/api/production-plans/{plan.id}/change-sets/{change_set.id}/apply"
    )
    assert response.status_code == 200, response.text


async def _position_from_db(session: AsyncSession, position_id: int) -> PlanPosition:
    position = await session.get(PlanPosition, position_id)
    assert position is not None
    await session.refresh(position)
    return position


async def _positions_from_api(client, plan: ProductionPlan) -> list[dict]:
    response = await client.get(f"/api/production-plans/{plan.id}/all-positions")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_create_position_persists_warnings_and_stays_valid(client, session, tmp_path) -> None:
    """Предупреждения элемента сета попадают на позицию, статус — по ошибкам."""
    product, route = await _make_ready_product(session, "WARN-CREATE")
    plan, batch = await _make_plan_with_batch(session, "PLAN-WARN-CREATE", tmp_path)
    change_set = await _make_change_set(
        session,
        plan,
        batch,
        {
            "source_row_number": 6,
            "source_ref": "rows:6",
            "change_action": PlanChangeAction.create_position,
            "before_data": None,
            "after_data": _after_data(product, route, row_number=6),
            "warnings": [WARNING_CODE],
            "errors": [],
        },
    )

    await _apply(client, plan, change_set)

    positions = await _positions_from_api(client, plan)
    assert len(positions) == 1
    assert positions[0]["validation_warnings"] == [WARNING_CODE]
    # Предупреждение не делает позицию невалидной: статус считается по ошибкам.
    assert positions[0]["validation_status"] == PlanPositionValidationStatus.valid.value
    assert positions[0]["status"] == PlanPositionStatus.draft.value
    assert positions[0]["errors"] == []

    stored = await _position_from_db(session, positions[0]["id"])
    assert stored.validation_warnings == [WARNING_CODE]
    assert stored.validation_status == PlanPositionValidationStatus.valid


@pytest.mark.asyncio
async def test_create_position_without_warnings_writes_empty_list(client, session, tmp_path) -> None:
    product, route = await _make_ready_product(session, "WARN-EMPTY")
    plan, batch = await _make_plan_with_batch(session, "PLAN-WARN-EMPTY", tmp_path)
    change_set = await _make_change_set(
        session,
        plan,
        batch,
        {
            "source_row_number": 3,
            "source_ref": "rows:3",
            "change_action": PlanChangeAction.create_position,
            "before_data": None,
            "after_data": _after_data(product, route, row_number=3),
            "warnings": [],
            "errors": [],
        },
    )

    await _apply(client, plan, change_set)

    positions = await _positions_from_api(client, plan)
    assert len(positions) == 1
    assert positions[0]["validation_warnings"] == []
    assert positions[0]["validation_status"] == PlanPositionValidationStatus.valid.value

    stored = await _position_from_db(session, positions[0]["id"])
    assert stored.validation_warnings == []


@pytest.mark.asyncio
async def test_update_draft_position_persists_warnings(client, session, tmp_path) -> None:
    """Ветка обновления: предупреждения берутся с элемента сета, а не с ошибок."""
    product, route = await _make_ready_product(session, "WARN-UPDATE")
    plan, batch = await _make_plan_with_batch(session, "PLAN-WARN-UPDATE", tmp_path)
    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        route_id=route.id,
        source_type=PlanSourceType.excel_import,
        source_system="excel",
        import_batch_id=batch.id,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal(100),
        source_payload={"period_start": "2026-05-01", "period_end": "2026-05-31"},
        period_start=plan.period_start,
        period_end=plan.period_end,
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        validation_warnings=[],
        source_row_number=7,
        has_pack_ops=False,
    )
    session.add(position)
    await session.flush()
    await session.commit()

    change_set = await _make_change_set(
        session,
        plan,
        batch,
        {
            "source_row_number": 7,
            "source_ref": "rows:7",
            "change_action": PlanChangeAction.update_draft_position,
            "plan_position_id": position.id,
            "before_data": None,
            "after_data": _after_data(product, route, row_number=7),
            "warnings": [HANGER_WARNING],
            "errors": [],
        },
    )

    await _apply(client, plan, change_set)

    stored = await _position_from_db(session, position.id)
    assert stored.validation_warnings == [HANGER_WARNING]
    assert stored.validation_status == PlanPositionValidationStatus.valid
    assert stored.status == PlanPositionStatus.draft
    assert stored.validation_errors == []

    api_position = (await _positions_from_api(client, plan))[0]
    assert api_position["validation_warnings"] == [HANGER_WARNING]


@pytest.mark.asyncio
async def test_update_draft_position_without_warnings_clears_previous(client, session, tmp_path) -> None:
    """Новое применение без предупреждений гасит прежние — позиция отражает
    последний сет, а не накопленное."""
    product, route = await _make_ready_product(session, "WARN-CLEAR")
    plan, batch = await _make_plan_with_batch(session, "PLAN-WARN-CLEAR", tmp_path)
    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        route_id=route.id,
        source_type=PlanSourceType.excel_import,
        source_system="excel",
        import_batch_id=batch.id,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal(50),
        source_payload={"period_start": "2026-05-01", "period_end": "2026-05-31"},
        period_start=plan.period_start,
        period_end=plan.period_end,
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        validation_warnings=[WARNING_CODE],
        source_row_number=4,
        has_pack_ops=False,
    )
    session.add(position)
    await session.flush()
    await session.commit()

    change_set = await _make_change_set(
        session,
        plan,
        batch,
        {
            "source_row_number": 4,
            "source_ref": "rows:4",
            "change_action": PlanChangeAction.update_draft_position,
            "plan_position_id": position.id,
            "before_data": None,
            "after_data": _after_data(product, route, row_number=4),
            "warnings": [],
            "errors": [],
        },
    )

    await _apply(client, plan, change_set)

    stored = await _position_from_db(session, position.id)
    assert stored.validation_warnings == []


@pytest.mark.asyncio
async def test_approve_response_carries_validation_warnings(client, session, tmp_path) -> None:
    """Утверждение отдаёт предупреждения рядом с ошибками (решение по строке
    принимается там же, где предупреждение видно)."""
    from app.core.security import create_access_token
    from app.models.user import User, UserRole

    user = User(email="warn-approve@test.local", full_name="Warn Approve", role=UserRole.planner, is_active=True)
    session.add(user)
    await session.flush()
    headers = {"Authorization": f"Bearer {create_access_token(subject=user.email)}"}

    product, route = await _make_ready_product(session, "WARN-APPROVE")
    plan, batch = await _make_plan_with_batch(session, "PLAN-WARN-APPROVE", tmp_path)
    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        route_id=route.id,
        source_type=PlanSourceType.excel_import,
        source_system="excel",
        import_batch_id=batch.id,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal(10),
        source_payload={"period_start": "2026-05-01", "period_end": "2026-05-31"},
        period_start=plan.period_start,
        period_end=plan.period_end,
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        validation_warnings=[HANGER_WARNING],
        source_row_number=8,
        has_pack_ops=False,
    )
    session.add(position)
    await session.flush()
    await session.commit()

    response = await client.post(
        f"/api/production-plans/{plan.id}/positions/{position.id}/approve",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["validation_warnings"] == [HANGER_WARNING]
    assert body["validation_errors"] == []
    assert body["validation_status"] == PlanPositionValidationStatus.valid.value


@pytest.mark.asyncio
async def test_import_positions_api_returns_validation_warnings(client, session, tmp_path) -> None:
    """Ответ импорта (`/api/imports/{batch_id}/positions`) несёт предупреждения."""
    product, route = await _make_ready_product(session, "WARN-IMPORT-API")
    plan, batch = await _make_plan_with_batch(session, "PLAN-WARN-IMPORT-API", tmp_path)
    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        route_id=route.id,
        source_type=PlanSourceType.excel_import,
        source_system="excel",
        import_batch_id=batch.id,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal(10),
        source_payload={},
        period_start=plan.period_start,
        period_end=plan.period_end,
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        validation_warnings=[WARNING_CODE],
        source_row_number=11,
        has_pack_ops=False,
    )
    session.add(position)
    await session.flush()
    await session.commit()

    response = await client.get(f"/api/imports/{batch.id}/positions")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["validation_warnings"] == [WARNING_CODE]
    assert body[0]["validation_errors"] == []
    assert body[0]["validation_status"] == PlanPositionValidationStatus.valid.value
