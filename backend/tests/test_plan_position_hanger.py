"""Тесты интеграции авторасчёта с планированием (#66, спек #59 п. 57).

Две зоны ответственности:
- `validate_plan_position`: код ошибки `hanger_calc_zero` при невозможном
  расчёте (total<=0 или несовместимые габариты).
- контракт вывода сериализации `PlanPositionOut`: `quantity_per_hanger`
  + `quantity_per_hanger_source` ("auto"|"manual"|null), приоритет
  ручной override из payload > авто > null.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
)
from app.models.product import Product, ProductType
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section
from app.models.techcard import Techcard, TechcardLine
from app.services.plan_validation import validate_plan_position


async def _make_ready_product(session, sku: str, *, auto: bool = False) -> Product:
    """Продукт с техкартой и маршрутом. `auto` — авто-поля периметр/габарит."""
    product = Product(sku=sku, name=f"Finished {sku}", type=ProductType.finished_good, unit="pcs")
    component = Product(sku=f"{sku}-RAW", name=f"Raw {sku}", type=ProductType.component, unit="pcs")
    if auto:
        product.perimeter_mm = 64.2
        product.mount_width_mm = 19.35
    sections = [
        Section(code=f"{sku}-CUT", name="Cut"),
        Section(code=f"{sku}-PACK", name="Pack"),
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
    for index, section in enumerate(sections, start=1):
        stage = RouteStage(route_id=route.id, sequence=index, section_id=section.id, is_final=index == len(sections))
        session.add(stage)
        await session.flush()
        session.add(RouteOperation(route_stage_id=stage.id, sequence=1, operation_code=None, operation_name=f"Step {index}"))
    await session.flush()
    return product


async def _make_plan_position(
    session,
    product: Product,
    *,
    length_mm: float | None = None,
    payload_quantity_per_hanger: int | None = None,
    quantity: Decimal = Decimal("100"),
) -> tuple[ProductionPlan, PlanPosition]:
    plan = ProductionPlan(
        plan_no=f"PLAN-{product.sku}",
        name=f"Plan {product.sku}",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()
    payload: dict = {}
    if payload_quantity_per_hanger is not None:
        payload["quantity_per_hanger"] = payload_quantity_per_hanger
    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=quantity,
        input_dimensions={"length_mm": int(length_mm)} if length_mm is not None else None,
        source_payload=payload,
        period_start=plan.period_start,
        period_end=plan.period_end,
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
    )
    session.add(position)
    await session.flush()
    return plan, position


# ─── Валидация: код ошибки hanger_calc_zero ─────────────────────────────────


@pytest.mark.asyncio
async def test_validate_hanger_calc_zero_when_total_zero(session) -> None:
    """total<=0 (очень длинная заготовка → by_area=0) → hanger_calc_zero."""
    product = await _make_ready_product(session, "FG-ZERO", auto=True)
    _, position = await _make_plan_position(session, product, length_mm=500_000)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "hanger_calc_zero" in errors


@pytest.mark.asyncio
async def test_validate_hanger_calc_zero_on_incompatible_dimensions(session) -> None:
    """mount_width + gap > rod_length (не влезает на клюшку) → hanger_calc_zero."""
    product = await _make_ready_product(session, "FG-CROSS", auto=True)
    product.mount_width_mm = 2000
    await session.flush()
    _, position = await _make_plan_position(session, product, length_mm=2800)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "hanger_calc_zero" in errors


@pytest.mark.asyncio
async def test_validate_no_hanger_error_when_auto_ok(session) -> None:
    """Авто-артикул с валидной длиной (ЮП-460 → 72) — ошибки нет."""
    product = await _make_ready_product(session, "FG-AUTO-OK", auto=True)
    _, position = await _make_plan_position(session, product, length_mm=2800)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "hanger_calc_zero" not in errors


@pytest.mark.asyncio
async def test_validate_no_hanger_error_when_no_length(session) -> None:
    """Без конкретной длины — текущее поведение, hanger_calc_zero нет."""
    product = await _make_ready_product(session, "FG-NOLEN", auto=True)
    _, position = await _make_plan_position(session, product, length_mm=None)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "hanger_calc_zero" not in errors


@pytest.mark.asyncio
async def test_validate_no_hanger_error_when_manual_override(session) -> None:
    """Ручной override из payload подавляет авто-ошибку (приоритет payload > авто)."""
    product = await _make_ready_product(session, "FG-OVR", auto=True)
    _, position = await _make_plan_position(session, product, length_mm=500_000, payload_quantity_per_hanger=10)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "hanger_calc_zero" not in errors


@pytest.mark.asyncio
async def test_validate_no_hanger_error_for_manual_article(session) -> None:
    """Не-авто артикул (без периметра/габарита) — авто-проверка не запускается."""
    product = await _make_ready_product(session, "FG-MANUAL", auto=False)
    _, position = await _make_plan_position(session, product, length_mm=2800)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "hanger_calc_zero" not in errors


# ─── Контракт вывода сериализации: quantity_per_hanger + source ─────────────


@pytest.mark.asyncio
async def test_serialize_auto_per_length_source(client, session) -> None:
    """Авто-артикул + длина позиции → значение для этой длины, source="auto"."""
    product = await _make_ready_product(session, "FG-SER-AUTO", auto=True)
    plan, _ = await _make_plan_position(session, product, length_mm=2800)
    await session.flush()

    resp = await client.get(f"/api/production-plans/{plan.id}/all-positions")
    assert resp.status_code == 200, resp.text
    position = resp.json()[0]
    assert position["quantity_per_hanger"] == 72
    assert position["quantity_per_hanger_source"] == "auto"


@pytest.mark.asyncio
async def test_serialize_manual_override_wins(client, session) -> None:
    """Ручной override из payload побеждает авто (приоритет payload > авто)."""
    product = await _make_ready_product(session, "FG-SER-OVR", auto=True)
    plan, _ = await _make_plan_position(session, product, length_mm=2800, payload_quantity_per_hanger=10)
    await session.flush()

    resp = await client.get(f"/api/production-plans/{plan.id}/all-positions")
    assert resp.status_code == 200, resp.text
    position = resp.json()[0]
    assert position["quantity_per_hanger"] == 10
    assert position["quantity_per_hanger_source"] == "manual"


@pytest.mark.asyncio
async def test_serialize_payload_fallback_without_length(client, session) -> None:
    """Без длины/не авто → текущее payload-значение со source="manual"."""
    product = await _make_ready_product(session, "FG-SER-MAN", auto=False)
    plan, _ = await _make_plan_position(session, product, length_mm=None, payload_quantity_per_hanger=40)
    await session.flush()

    resp = await client.get(f"/api/production-plans/{plan.id}/all-positions")
    assert resp.status_code == 200, resp.text
    position = resp.json()[0]
    assert position["quantity_per_hanger"] == 40
    assert position["quantity_per_hanger_source"] == "manual"


@pytest.mark.asyncio
async def test_serialize_null_without_data(client, session) -> None:
    """Артикул без данных и без длины → null/null."""
    product = await _make_ready_product(session, "FG-SER-NULL", auto=False)
    plan, _ = await _make_plan_position(session, product, length_mm=None)
    await session.flush()

    resp = await client.get(f"/api/production-plans/{plan.id}/all-positions")
    assert resp.status_code == 200, resp.text
    position = resp.json()[0]
    assert position["quantity_per_hanger"] is None
    assert position["quantity_per_hanger_source"] is None


@pytest.mark.asyncio
async def test_serialize_zero_total_is_null(client, session) -> None:
    """total<=0 → null (ноль как число не существует); ошибку покажет валидация."""
    product = await _make_ready_product(session, "FG-SER-ZERO", auto=True)
    plan, _ = await _make_plan_position(session, product, length_mm=500_000)
    await session.flush()

    resp = await client.get(f"/api/production-plans/{plan.id}/all-positions")
    assert resp.status_code == 200, resp.text
    position = resp.json()[0]
    assert position["quantity_per_hanger"] is None
    assert position["quantity_per_hanger_source"] is None
