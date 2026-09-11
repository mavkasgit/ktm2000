from datetime import date
from decimal import Decimal

import pytest

from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
)
from app.models.route import ProductionRoute, RouteStage, RouteOperation
from app.models.section import Section
from app.services.plan_validation import validate_plan_position


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

    route = ProductionRoute(name="Main", is_active=True)
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
    return product, sections, route


async def _make_plan_position(
    session,
    product: Product,
    quantity: Decimal = Decimal("100"),
    **kwargs,
) -> tuple[ProductionPlan, PlanPosition]:
    plan = ProductionPlan(
        plan_no=f"PLAN-{product.sku}",
        name=f"Plan {product.sku}",
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
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
        **kwargs,
    )
    session.add(position)
    await session.flush()
    return plan, position


@pytest.mark.asyncio
async def test_validate_position_fails_on_inactive_product(session) -> None:
    product = Product(
        sku="INACTIVE-1",
        name="Inactive Product",
        type=ProductType.finished_good,
        unit="pcs",
        is_active=False,
    )
    session.add(product)
    await session.flush()

    plan = ProductionPlan(plan_no="PLAN-TEST", name="Test Plan")
    session.add(plan)
    await session.flush()

    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("10"),
        source_payload={},
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
    )
    session.add(position)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "product_inactive" in errors


@pytest.mark.asyncio
async def test_validate_position_fails_on_duplicate_sku_due_date(session) -> None:
    product, _, _ = await _make_ready_product(session, "FG-DUP")
    plan = ProductionPlan(plan_no="PLAN-DUP", name="Dup Plan")
    session.add(plan)
    await session.flush()

    position1 = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("10"),
        due_date=date(2026, 5, 15),
        source_payload={},
        source_fingerprint="fp-duplicate-sku",
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
    )
    session.add(position1)
    await session.flush()

    position2 = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("20"),
        due_date=date(2026, 5, 15),
        source_payload={},
        source_fingerprint="fp-duplicate-sku",
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
    )
    session.add(position2)
    await session.flush()

    errors = await validate_plan_position(session, position2)
    assert "duplicate_sku_due_date" in errors


@pytest.mark.asyncio
async def test_validate_position_ignores_cancelled_duplicate(session) -> None:
    product, _, _ = await _make_ready_product(session, "FG-DUP-CAN")
    plan = ProductionPlan(plan_no="PLAN-DUP-CAN", name="Dup Plan Cancelled")
    session.add(plan)
    await session.flush()

    position1 = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("10"),
        due_date=date(2026, 5, 15),
        source_payload={},
        source_fingerprint="fp-dup-cancelled",
        status=PlanPositionStatus.cancelled,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
    )
    session.add(position1)
    await session.flush()

    position2 = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("20"),
        due_date=date(2026, 5, 15),
        source_payload={},
        source_fingerprint="fp-dup-cancelled",
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
    )
    session.add(position2)
    await session.flush()

    errors = await validate_plan_position(session, position2)
    assert "duplicate_sku_due_date" not in errors


@pytest.mark.asyncio
async def test_validate_position_passes_on_valid_position(session) -> None:
    product, _, route = await _make_ready_product(session, "FG-OK")
    plan, position = await _make_plan_position(session, product, route_id=route.id)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert errors == []


@pytest.mark.asyncio
async def test_validate_position_detects_product_not_found(session) -> None:
    plan = ProductionPlan(plan_no="PLAN-NO-PROD", name="No Product Plan")
    session.add(plan)
    await session.flush()

    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=None,
        source_type=PlanSourceType.manual,
        source_sku="MISSING",
        source_name="Missing",
        quantity=Decimal("10"),
        source_payload={},
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
    )
    session.add(position)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "product_not_found" in errors
    assert "product_inactive" not in errors


async def _make_raw_pair(session, sku_a: str = "ЮП-2616", sku_b: str = "ЮП-2604", *, manual_n: int | None = None) -> None:
    """Пара сырьевых артикулов в product_pairs с длиной 2700 у обоих."""
    from app.models.product import ProductLength, ProductPair

    comp_a = Product(sku=sku_a, name=f"Raw {sku_a}", type=ProductType.component, unit="pcs")
    comp_b = Product(sku=sku_b, name=f"Raw {sku_b}", type=ProductType.component, unit="pcs")
    session.add_all([comp_a, comp_b])
    await session.flush()
    session.add_all([
        ProductLength(product_id=comp_a.id, length_mm=2700),
        ProductLength(product_id=comp_b.id, length_mm=2700),
    ])
    quantity = {"2700": {"auto": None, "manual": manual_n}} if manual_n is not None else {}
    session.add(ProductPair(
        product_a_id=min(comp_a.id, comp_b.id),
        product_b_id=max(comp_a.id, comp_b.id),
        quantity_per_hanger=quantity,
    ))
    await session.flush()


def _paired_payload(*, with_snapshot: bool = False) -> dict:
    payload = {
        "paired_profile": True,
        "components": [{"sku": "ЮП-2616"}, {"sku": "ЮП-2604"}],
    }
    if with_snapshot:
        payload["product_pair"] = {
            "resolved": True,
            "reason": None,
            "inputs": [
                {"product_id": 1, "sku": "ЮП-2616", "quantity_per_hanger": "8", "available_quantity": "100", "unit": "pcs"},
                {"product_id": 2, "sku": "ЮП-2604", "quantity_per_hanger": "8", "available_quantity": "100", "unit": "pcs"},
            ],
        }
    return payload


async def _make_paired_position(session, sku: str, payload: dict) -> tuple[ProductionPlan, PlanPosition]:
    plan = ProductionPlan(plan_no=f"PLAN-{sku}", name=f"Plan {sku}")
    session.add(plan)
    await session.flush()
    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=None,
        source_type=PlanSourceType.excel_import,
        source_sku=sku,
        source_name=None,
        quantity=Decimal("100"),
        input_dimensions={"length_mm": 2700},
        source_payload=payload,
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
    )
    session.add(position)
    await session.flush()
    return plan, position


@pytest.mark.asyncio
async def test_validate_paired_position_without_pair_reports_error(session) -> None:
    """Пара не найдена в product_pairs → product_pair_not_found."""
    plan, position = await _make_paired_position(session, "ЮП-2616+ЮП-2604", _paired_payload())
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "product_pair_not_found" in errors


@pytest.mark.asyncio
async def test_validate_paired_position_with_manual_pair_n_passes(session) -> None:
    """Пара найдена, ручная N из словаря пары — ошибок нет."""
    await _make_raw_pair(session, manual_n=8)
    plan, position = await _make_paired_position(session, "ЮП-2616+ЮП-2604", _paired_payload())
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "product_pair_not_found" not in errors
    assert "hanger_calc_zero" not in errors


@pytest.mark.asyncio
async def test_validate_paired_position_without_n_reports_hanger_calc_zero(session) -> None:
    """Пара найдена, но N невозможна (ручной нет, авто не считается) → hanger_calc_zero."""
    await _make_raw_pair(session)
    plan, position = await _make_paired_position(session, "ЮП-2616+ЮП-2604", _paired_payload())
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "product_pair_not_found" not in errors
    assert "hanger_calc_zero" in errors


@pytest.mark.asyncio
async def test_validate_paired_position_with_snapshot_skips_revalidation(session) -> None:
    """Позиция с непустым снапшотом (product_pair.resolved) не ревалидирует пару и нормы (#142)."""
    plan, position = await _make_paired_position(session, "ЮП-2616+ЮП-2604", _paired_payload(with_snapshot=True))
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "product_pair_not_found" not in errors
    assert "hanger_calc_zero" not in errors


@pytest.mark.asyncio
async def test_validate_position_detects_missing_route(session) -> None:
    product = Product(sku="FG-NO-ROUTE", name="No Route", type=ProductType.finished_good, unit="pcs")
    component = Product(sku="FG-NO-ROUTE-RAW", name="Raw", type=ProductType.component, unit="pcs")
    session.add_all([product, component])
    await session.flush()

    await session.flush()

    

    plan, position = await _make_plan_position(
        session,
        product,
        has_pack_ops=False,
    )
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "no_route_candidate" in errors


@pytest.mark.asyncio
async def test_validate_position_detects_empty_route(session) -> None:
    product = Product(sku="FG-EMPTY-ROUTE", name="Empty Route", type=ProductType.finished_good, unit="pcs")
    component = Product(sku="FG-EMPTY-ROUTE-RAW", name="Raw", type=ProductType.component, unit="pcs")
    session.add_all([product, component])
    await session.flush()


    route = ProductionRoute(name="Main", is_active=True)
    session.add(route)
    await session.flush()

    plan, position = await _make_plan_position(session, product, route_id=route.id)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "active_route_has_no_steps" in errors


@pytest.mark.asyncio
async def test_validate_position_detects_inactive_section(session) -> None:
    product = Product(sku="FG-INACT-SEC", name="Inactive Section", type=ProductType.finished_good, unit="pcs")
    component = Product(sku="FG-INACT-SEC-RAW", name="Raw", type=ProductType.component, unit="pcs")
    section = Section(code="CUT", name="Cut", is_active=False)
    session.add_all([product, component, section])
    await session.flush()


    route = ProductionRoute(name="Main", is_active=True)
    session.add(route)
    await session.flush()
    stage = RouteStage(route_id=route.id, sequence=1, section_id=section.id, is_final=True)
    session.add(stage)
    await session.flush()
    session.add(RouteOperation(route_stage_id=stage.id, sequence=1, operation_code=None, operation_name="Cut"))
    await session.flush()

    plan, position = await _make_plan_position(session, product, route_id=route.id)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "route_contains_inactive_section" in errors


@pytest.mark.asyncio
async def test_validate_position_accepts_transit_stage_with_active_storage_section(session) -> None:
    """Transit-шаг (section_id=NULL, storage_section_id задан) не должен
    считаться неактивным: валидация использует effective_section_id."""
    product = Product(sku="FG-TRANSIT", name="Transit", type=ProductType.finished_good, unit="pcs")
    component = Product(sku="FG-TRANSIT-RAW", name="Raw", type=ProductType.component, unit="pcs")
    storage = Section(code="RAW_STOCK", name="Склад сырья", is_active=True, type="raw_stock")
    production = Section(code="PACK", name="Упаковка", is_active=True)
    session.add_all([product, component, storage, production])
    await session.flush()


    route = ProductionRoute(name="Main", is_active=True)
    session.add(route)
    await session.flush()
    stage = RouteStage(
        route_id=route.id,
        sequence=1,
        section_id=None,
        stage_kind="transit",
        storage_section_id=storage.id,
        is_final=False,
    )
    session.add(stage)
    await session.flush()
    stage2 = RouteStage(
        route_id=route.id,
        sequence=2,
        section_id=production.id,
        is_final=True,
    )
    session.add(stage2)
    await session.flush()

    plan, position = await _make_plan_position(session, product, route_id=route.id)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "route_contains_inactive_section" not in errors


@pytest.mark.asyncio
async def test_validate_position_rejects_transit_stage_with_inactive_storage_section(session) -> None:
    """Неактивная storage-секция transit-шага должна давать ошибку."""
    product = Product(sku="FG-TRANSIT-2", name="Transit2", type=ProductType.finished_good, unit="pcs")
    component = Product(sku="FG-TRANSIT-2-RAW", name="Raw2", type=ProductType.component, unit="pcs")
    storage = Section(code="RAW_STOCK_2", name="Склад сырья", is_active=False, type="raw_stock")
    session.add_all([product, component, storage])
    await session.flush()


    route = ProductionRoute(name="Main", is_active=True)
    session.add(route)
    await session.flush()
    stage = RouteStage(
        route_id=route.id,
        sequence=1,
        section_id=None,
        stage_kind="transit",
        storage_section_id=storage.id,
        is_final=True,
    )
    session.add(stage)
    await session.flush()

    plan, position = await _make_plan_position(session, product, route_id=route.id)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "route_contains_inactive_section" in errors
