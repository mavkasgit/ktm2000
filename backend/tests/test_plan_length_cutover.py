"""Публичные API-контракты перехода плана на модель normal/raw (ADR-0028)."""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanChangeSet,
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
)
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section


SIMULATE_URL = "/api/imports/excel/simulate"


def _plan_row(
    sku: str,
    *,
    input_length_m: float,
    output_length_m: float,
    quantity: int,
) -> dict:
    return {
        "sku": sku,
        "name": f"Profile {sku}",
        "qty_per_27": quantity,
        "length_m": input_length_m,
        "output_length_m": output_length_m,
        "output_qty": quantity,
        "kind": "ГП",
    }


async def _create_linear_product(
    client,
    session: AsyncSession,
    *,
    sku: str,
    lengths: list[dict],
) -> Product:
    response = await client.post(
        "/api/products",
        json={
            "sku": sku,
            "name": f"Profile {sku}",
            "type": ProductType.component.value,
            "unit": "pcs",
            "dimension_state": "length",
            "lengths": lengths,
            "perimeter_mm": 500,
            "mount_width_mm": 100,
            "hanger_mode": "auto",
        },
    )
    assert response.status_code == 201, response.text
    product = await session.get(Product, response.json()["id"])
    assert product is not None
    return product


async def _seed_route(session: AsyncSession, sku: str) -> None:
    sections = [
        Section(code=f"{sku}-CUT", name="Cut", type="production", is_active=True),
        Section(code=f"{sku}-PACK", name="Pack", type="production", is_active=True),
    ]
    session.add_all(sections)
    await session.flush()

    route = ProductionRoute(name=f"Route {sku}", is_active=True)
    session.add(route)
    await session.flush()
    for index, section in enumerate(sections, start=1):
        stage = RouteStage(
            route_id=route.id,
            sequence=index * 10,
            section_id=section.id,
            is_final=index == len(sections),
        )
        session.add(stage)
        await session.flush()
        session.add(
            RouteOperation(
                route_stage_id=stage.id,
                sequence=1,
                operation_name=f"Operation {index}",
            )
        )
    await session.commit()


async def _import_item(client, *, sku: str, rows: list[dict]) -> dict:
    response = await client.post(
        SIMULATE_URL,
        json={
            "sheet_name": f"plan-{sku}",
            "rows": rows,
            "normalize_hanger_quantity": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _full_item(client, item_id: int) -> dict:
    response = await client.get(f"/api/imports/items/{item_id}?full=1")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_import_keeps_excel_normal_length_when_catalog_raw_differs(
    client,
    session: AsyncSession,
) -> None:
    """Excel 2700 remains the plan geometry when its catalog raw length is 2750."""
    sku = "PLAN-CUTOVER-NORMAL"
    await _create_linear_product(
        client,
        session,
        sku=sku,
        lengths=[{"length_mm": 2700, "raw_length_mm": 2750, "is_primary": True}],
    )
    await _seed_route(session, sku)

    body = await _import_item(
        client,
        sku=sku,
        rows=[
            _plan_row(
                sku,
                input_length_m=2.7,
                output_length_m=2.7,
                quantity=19,
            )
        ],
    )
    item = body["items"][0]
    full = await _full_item(client, item["item_id"])

    assert full["source_sku"] == sku
    assert full["errors"] == []
    assert full["warnings"] == []
    assert full["after_data"]["input_dimensions"] == {"length_mm": 2700}
    assert full["after_data"]["quantity_per_hanger"] == 9
    assert not any(
        code.startswith(("raw_length_not_found", "raw_length_substituted"))
        for code in item["codes"]
    )
    apply = await client.post(
        f"/api/production-plans/{body['production_plan_id']}"
        f"/change-sets/{body['change_set_id']}/apply"
    )
    assert apply.status_code == 200, apply.text
    assert apply.json()["created_positions"] == 1

    positions_response = await client.get(
        f"/api/production-plans/{body['production_plan_id']}/all-positions"
    )
    assert positions_response.status_code == 200, positions_response.text
    positions = positions_response.json()
    assert len(positions) == 1
    assert positions[0]["input_dimensions"] == {"length_mm": 2700}


@pytest.mark.asyncio
async def test_unknown_normal_length_errors_only_its_import_position(
    client,
    session: AsyncSession,
) -> None:
    """A missing normal length invalidates exactly one row and leaves its sibling importable."""
    sku = "PLAN-CUTOVER-PER-ROW"
    await _create_linear_product(
        client,
        session,
        sku=sku,
        lengths=[
            {"length_mm": 2700, "raw_length_mm": 2750, "is_primary": True},
            {"length_mm": 3000, "raw_length_mm": 3050, "is_primary": False},
        ],
    )
    await _seed_route(session, sku)

    body = await _import_item(
        client,
        sku=sku,
        rows=[
            _plan_row(
                sku,
                input_length_m=2.7,
                output_length_m=2.7,
                quantity=18,
            ),
            _plan_row(
                sku,
                input_length_m=2.8,
                output_length_m=2.8,
                quantity=18,
            ),
        ],
    )
    assert body["summary"]["total_positions"] == 2
    known, unknown = body["items"]

    known_full = await _full_item(client, known["item_id"])
    unknown_full = await _full_item(client, unknown["item_id"])
    assert known_full["status"] == "pending"
    assert known_full["errors"] == []
    assert known_full["after_data"]["input_dimensions"] == {"length_mm": 2700}
    assert unknown_full["status"] == "invalid"
    assert unknown_full["errors"]
    assert unknown_full["after_data"]["input_dimensions"] == {"length_mm": 2800}
    assert unknown["codes"] == ["normal_length_not_found"]
    assert not any(
        code.startswith(("raw_length_not_found", "raw_length_substituted"))
        for code in known["codes"] + unknown["codes"]
    )
    apply = await client.post(
        f"/api/production-plans/{body['production_plan_id']}"
        f"/change-sets/{body['change_set_id']}/apply"
    )
    assert apply.status_code == 200, apply.text
    assert apply.json()["created_positions"] == 2

    positions_response = await client.get(
        f"/api/production-plans/{body['production_plan_id']}/all-positions"
    )
    assert positions_response.status_code == 200, positions_response.text
    by_length = {
        position["input_dimensions"]["length_mm"]: position
        for position in positions_response.json()
    }
    assert by_length[2700]["status"] == "draft"
    assert by_length[2800]["status"] == "invalid"
    assert by_length[2800]["errors"]


@pytest.mark.asyncio
async def test_import_hanger_snapshot_survives_catalog_raw_change(
    client,
    session: AsyncSession,
) -> None:
    """The import item keeps N=9 after the catalog raw length changes 2750→3000."""
    sku = "PLAN-CUTOVER-SNAPSHOT"
    product = await _create_linear_product(
        client,
        session,
        sku=sku,
        lengths=[{"length_mm": 2700, "raw_length_mm": 2750, "is_primary": True}],
    )
    await _seed_route(session, sku)

    body = await _import_item(
        client,
        sku=sku,
        rows=[
            _plan_row(
                sku,
                input_length_m=2.7,
                output_length_m=2.7,
                quantity=18,
            )
        ],
    )
    item_id = body["items"][0]["item_id"]
    before = await _full_item(client, item_id)
    assert before["after_data"]["quantity_per_hanger"] == 9

    changed = await client.patch(
        f"/api/products/{product.id}",
        json={
            "lengths": [
                {"length_mm": 2700, "raw_length_mm": 3000, "is_primary": True}
            ]
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["lengths"] == [
        {"length_mm": 2700.0, "raw_length_mm": 3000.0, "is_primary": True}
    ]

    after = await _full_item(client, item_id)
    assert after["after_data"]["quantity_per_hanger"] == 9


@pytest.mark.asyncio
async def test_version_one_plan_is_readable_but_all_position_mutations_are_blocked(
    client,
    session: AsyncSession,
) -> None:
    """A v1 plan remains readable while apply/approve/cancel/release/edit/delete return one stable error."""
    plan = ProductionPlan(
        plan_no="PLAN-CUTOVER-LEGACY",
        name="Legacy length plan",
        length_model_version=1,
    )
    session.add(plan)
    await session.flush()
    change_set = PlanChangeSet(production_plan_id=plan.id, summary={})
    session.add(change_set)
    position = PlanPosition(
        production_plan_id=plan.id,
        source_type=PlanSourceType.excel_import,
        source_sku="PLAN-CUTOVER-LEGACY-SKU",
        source_name="Legacy profile",
        quantity=Decimal("10"),
        input_dimensions={"length_mm": 2700},
        outputs=[{"quantity": "10", "dimensions": {"length_mm": 2700}}],
        source_payload={},
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
    )
    session.add(position)
    await session.commit()

    listed = await client.get("/api/production-plans")
    assert listed.status_code == 200, listed.text
    summary = next(item for item in listed.json() if item["id"] == plan.id)
    assert summary["plan_no"] == "PLAN-CUTOVER-LEGACY"
    assert summary["length_model_version"] == 1

    preview = await client.get(f"/api/production-plans/{plan.id}/preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["length_model_version"] == 1
    assert preview.json()["positions_total"] == 1

    positions_response = await client.get(
        f"/api/production-plans/{plan.id}/all-positions"
    )
    assert positions_response.status_code == 200, positions_response.text
    assert positions_response.json()[0]["input_dimensions"] == {"length_mm": 2700}

    mutations = [
        (
            "apply",
            "POST",
            f"/api/production-plans/{plan.id}/change-sets/{change_set.id}/apply",
            None,
        ),
        (
            "approve",
            "POST",
            f"/api/production-plans/{plan.id}/positions/{position.id}/approve?force=true",
            None,
        ),
        (
            "cancel",
            "POST",
            f"/api/production-plans/{plan.id}/positions/{position.id}/cancel",
            {"reason": "must not mutate"},
        ),
        (
            "release",
            "POST",
            f"/api/production-plans/{plan.id}/release-batches",
            {"name": "must not release", "positions": []},
        ),
        (
            "quantity",
            "PATCH",
            f"/api/production-plans/{plan.id}/positions/{position.id}/quantity",
            {"quantity": "11"},
        ),
        (
            "delete",
            "DELETE",
            f"/api/production-plans/{plan.id}/positions/{position.id}",
            None,
        ),
    ]
    for name, method, url, json_body in mutations:
        response = await client.request(method, url, json=json_body)
        assert response.status_code == 400, f"{name}: {response.text}"
        assert response.json() == {"detail": "legacy_plan_read_only"}, name

    unchanged = await client.get(f"/api/production-plans/{plan.id}/all-positions")
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()[0]["quantity"] == "10"
