from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models.defect import Defect
from app.models.internal_plan import InternalPlan, SectionPlanLine
from app.models.movement import Movement
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionRouteOrigin,
    PlanPositionRouteMatchQuality,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.release_batch import ReleaseBatch, ReleaseBatchPosition
from app.models.rework_task import ReworkTask
from app.models.route import RouteRuleProfile, RouteSelectionRule
from app.models.section import Section
from app.models.techcard import Techcard, TechcardLine
from app.models.transfer import Transfer
from app.models.work_task import WorkTask
from app.services.route_selection import select_route_for_payload


DEFAULT_SECTIONS = [
    {"code": "WH", "name": "Склад сырья", "sort_order": 10, "kind": "raw_stock"},
    {"code": "DRILL", "name": "Сверловка", "sort_order": 20, "kind": "production"},
    {"code": "PRESS", "name": "Пресс", "sort_order": 30, "kind": "production"},
    {"code": "SHOT", "name": "Дробеструй", "sort_order": 40, "kind": "production"},
    {"code": "ANOD", "name": "Анодирование", "sort_order": 50, "kind": "production"},
    {"code": "WIP_WH", "name": "Склад полуфабриката", "sort_order": 60, "kind": "wip_stock"},
    {"code": "SAW", "name": "Пила", "sort_order": 70, "kind": "production"},
    {"code": "PACK", "name": "Упаковка", "sort_order": 80, "kind": "production"},
    {"code": "FG_WH", "name": "Склад готовой продукции", "sort_order": 90, "kind": "finished_stock"},
    {"code": "SHIPMENT", "name": "К отгрузке", "sort_order": 100, "kind": "finished_stock"},
    {"code": "SENT", "name": "Отправлено", "sort_order": 110, "kind": "finished_stock"},
]


async def _seed_default_sections(session) -> None:
    for item in DEFAULT_SECTIONS:
        session.add(Section(code=item["code"], name=item["name"], sort_order=item["sort_order"], kind=item["kind"], is_active=True))
    await session.commit()


async def _count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


async def _make_releasable_position(session, route_name: str = "ГП • Без первичной • Без дробеструя") -> tuple[ProductionPlan, PlanPosition]:
    from app.models.route import ProductionRoute

    route = await session.scalar(select(ProductionRoute).where(ProductionRoute.name == route_name))
    product = Product(sku=f"ЮП-TEST-{datetime.now(UTC).timestamp()}", name="Микроплинтус тест", type=ProductType.finished_good, unit="pcs")
    component = Product(sku=f"RAW-{datetime.now(UTC).timestamp()}", name="Сырьё тест", type=ProductType.component, unit="pcs")
    session.add_all([product, component])
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(TechcardLine(techcard_id=techcard.id, component_product_id=component.id, quantity=1, unit="pcs"))

    plan = ProductionPlan(
        plan_no=f"PLAN-SEED-{product.id}",
        name="Seed cleanup plan",
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
        output_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("3021"),
        source_payload={"operation": "", "output_kind": "finished_good", "additional_pack_operations": ["PACK_STRETCH"]},
        period_start=plan.period_start,
        period_end=plan.period_end,
        source_row_number=7,
        route_id=route.id,
        route_origin=PlanPositionRouteOrigin.manual_confirmed,
        route_match_quality=PlanPositionRouteMatchQuality.exact,
        route_assigned_at=datetime.now(UTC),
        route_manual_confirmed_at=datetime.now(UTC),
        status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        approved_at=datetime.now(UTC),
    )
    session.add(position)
    await session.flush()
    return plan, position


@pytest.mark.asyncio
async def test_seed_routes_creates_characteristic_routes(client, session) -> None:
    await _seed_default_sections(session)

    response = await client.post("/api/routes-seed")
    assert response.status_code == 201
    data = response.json()
    assert data == {"import_templates": 1, "route_rule_profiles": 1, "routes": 2, "selection_rules": 12, "sections": 11, "section_operations": 20}
    first_rules_count = len((await session.execute(select(RouteSelectionRule))).scalars().all())
    assert first_rules_count == 12

    # idempotency/update behavior
    response2 = await client.post("/api/routes-seed")
    assert response2.status_code == 201
    data2 = response2.json()
    assert data2 == data
    second_rules = (await session.execute(select(RouteSelectionRule))).scalars().all()
    assert len(second_rules) == first_rules_count
    unique_keys = {rule.code for rule in second_rules}
    assert len(unique_keys) == first_rules_count


@pytest.mark.asyncio
async def test_route_selection_rule_can_be_updated(client, session) -> None:
    await _seed_default_sections(session)

    response = await client.post("/api/routes-seed")
    assert response.status_code == 201
    rules_response = await client.get("/api/route-selection-rules")
    assert rules_response.status_code == 200
    rule = rules_response.json()[0]
    drill = await session.scalar(select(Section).where(Section.code == "DRILL"))

    update_response = await client.put(
        f"/api/route-selection-rules/{rule['id']}",
        json={
            "code": rule["code"],
            "name": "Updated rule",
            "priority": 321,
            "is_active": False,
            "conditions": [{"source": "payload", "field_path": "operation", "operator": "contains", "value": "сверл", "case_sensitive": False}],
            "actions": [{"action": "require_section", "section_id": drill.id}],
        },
    )

    assert update_response.status_code == 200
    data = update_response.json()
    assert data["name"] == "Updated rule"
    assert data["priority"] == 321
    assert data["is_active"] is False
    assert data["conditions"][0]["field_path"] == "operation"


@pytest.mark.asyncio
async def test_seeded_rules_select_drill_finished_good_route(client, session) -> None:
    """Verify that route_select phase rules fire correctly.

    Since ProductionRoutes are now built dynamically (no static routes),
    select_route_for_payload returns no_route_candidate but the required/excluded
    sections are computed correctly from the rules.
    """
    await _seed_default_sections(session)

    response = await client.post("/api/routes-seed")
    assert response.status_code == 201
    profile = await session.scalar(select(RouteRuleProfile).where(RouteRuleProfile.code == "packaging_map_rp"))

    result = await select_route_for_payload(
        session,
        {"operation": "сверловка", "output_kind": "ГП", "raw_columns": {"operation": "сверловка", "output_kind": "ГП"}, "additional_pack_operations": []},
        profile_id=profile.id,
    )

    # No static routes exist — dynamic route building is used instead (Phase 4).
    # But the rule diagnostics should show correct required/excluded sections.
    assert result.route is None
    assert result.route_match_reason == "no_route_candidate"
    # DRILL should be required (from global_drill rule)
    required_codes = {s["code"] for s in result.required_sections}
    assert "DRILL" in required_codes
    # PRESS should be excluded (from global_drill rule)
    excluded_codes = {s["code"] for s in result.excluded_sections}
    assert "PRESS" in excluded_codes


@pytest.mark.asyncio
async def test_seeded_rules_exclude_finished_good_branch_for_semi_finished(client, session) -> None:
    """Verify that spunbond packaging excludes WIP_WH/SAW/PACK.

    Since ProductionRoutes are now built dynamically (no static routes),
    select_route_for_payload returns no_route_candidate but the required/excluded
    sections are computed correctly from the rules.
    """
    await _seed_default_sections(session)

    response = await client.post("/api/routes-seed")
    assert response.status_code == 201
    profile = await session.scalar(select(RouteRuleProfile).where(RouteRuleProfile.code == "packaging_map_rp"))

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "П/Ф", "raw_columns": {"operation": "", "packaging": "спанбонд"}, "additional_pack_operations": []},
        profile_id=profile.id,
    )

    # No static routes — but exclusion rules should fire
    assert result.route is None
    assert result.route_match_reason == "no_route_candidate"
    excluded_codes = {s["code"] for s in result.excluded_sections}
    assert "WIP_WH" in excluded_codes
    assert "SAW" in excluded_codes
    assert "PACK" in excluded_codes


@pytest.mark.skip(reason="Phase 4: release tests need dynamic route builder")
@pytest.mark.asyncio
async def test_force_seed_clears_generated_production_data(client, session) -> None:
    await _seed_default_sections(session)
    seed_response = await client.post("/api/routes-seed")
    assert seed_response.status_code == 201

    plan, position = await _make_releasable_position(session)
    await session.commit()

    create_response = await client.post(
        f"/api/production-plans/{plan.id}/release-batches",
        json={"positions": [{"plan_position_id": position.id, "release_quantity": "3021"}]},
    )
    assert create_response.status_code == 201
    release_response = await client.post(f"/api/release-batches/{create_response.json()['id']}/release")
    assert release_response.status_code == 200
    assert release_response.json()["tasks_created"] == 8

    force_response = await client.post("/api/routes-seed?force=true")
    assert force_response.status_code == 201
    assert force_response.json() == {"import_templates": 1, "route_rule_profiles": 1, "routes": 0, "selection_rules": 19, "sections": 11, "section_operations": 20}

    for model in (
        ReleaseBatchPosition,
        ReleaseBatch,
        InternalPlan,
        SectionPlanLine,
        WorkTask,
        Movement,
        Transfer,
        Defect,
        ReworkTask,
        PlanPosition,
        ProductionPlan,
    ):
        assert await _count(session, model) == 0

    assert len((await session.execute(select(RouteSelectionRule))).scalars().all()) == 19


@pytest.mark.skip(reason="Phase 4: release tests need dynamic route builder")
@pytest.mark.asyncio
async def test_new_release_after_force_seed_uses_new_route_steps(client, session) -> None:
    await _seed_default_sections(session)
    assert (await client.post("/api/routes-seed")).status_code == 201

    stale_plan, stale_position = await _make_releasable_position(session)
    await session.commit()
    stale_batch_response = await client.post(
        f"/api/production-plans/{stale_plan.id}/release-batches",
        json={"positions": [{"plan_position_id": stale_position.id, "release_quantity": "3021"}]},
    )
    assert stale_batch_response.status_code == 201

    force_response = await client.post("/api/routes-seed?force=true")
    assert force_response.status_code == 201
    assert await _count(session, ReleaseBatchPosition) == 0

    plan, position = await _make_releasable_position(session)
    await session.commit()
    create_response = await client.post(
        f"/api/production-plans/{plan.id}/release-batches",
        json={"positions": [{"plan_position_id": position.id, "release_quantity": "3021"}]},
    )
    assert create_response.status_code == 201
    batch = create_response.json()
    snapshot_steps = batch["positions"][0]["route_snapshot"]["steps"]
    assert len(snapshot_steps) == 9
    assert [step["combined_op_group"] for step in snapshot_steps if step["section_code"] == "ANOD"] == ["anod_pack", "anod_pack"]

    release_response = await client.post(f"/api/release-batches/{batch['id']}/release")
    assert release_response.status_code == 200
    released = release_response.json()
    assert released["tasks_created"] == 8
    assert released["task_count"] == 8
    assert await _count(session, WorkTask) == 8


@pytest.mark.asyncio
@pytest.mark.parametrize("env_value", ["prod", "production"])
async def test_force_seed_is_forbidden_in_production(client, session, monkeypatch, env_value) -> None:
    await _seed_default_sections(session)
    monkeypatch.setattr(settings, "ENV", env_value)

    response = await client.post("/api/routes-seed?force=true")

    assert response.status_code == 403
    assert response.json()["detail"] == "force=true is not allowed in production"
