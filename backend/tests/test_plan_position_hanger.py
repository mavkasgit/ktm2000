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
from app.models.product import Product, ProductLength, ProductPair, ProductType
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section
from app.services.plan_position_hanger import resolve_position_hanger
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

    await session.flush()

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


# ─── #127: source соответствует режиму артикула, а не наличию данных ──────


@pytest.mark.asyncio
async def test_serialize_manual_mode_with_fields_uses_manual(client, session) -> None:
    """Режим manual + заполненные периметр/габарит → ручное значение, не расчёт."""
    product = await _make_ready_product(session, "FG-MODE-MAN", auto=True)
    product.hanger_mode = "manual"
    product.quantity_per_hanger = {"2800": {"auto": None, "manual": 25}}
    plan, _ = await _make_plan_position(session, product, length_mm=2800)
    await session.flush()

    resp = await client.get(f"/api/production-plans/{plan.id}/all-positions")
    assert resp.status_code == 200, resp.text
    position = resp.json()[0]
    assert position["quantity_per_hanger"] == 25
    assert position["quantity_per_hanger_source"] == "manual"


@pytest.mark.asyncio
async def test_serialize_auto_mode_without_fields_is_null(client, session) -> None:
    """Режим auto без периметра/габарита → null (наличие данных не решает)."""
    product = await _make_ready_product(session, "FG-MODE-AUTO", auto=False)
    product.hanger_mode = "auto"
    plan, _ = await _make_plan_position(session, product, length_mm=2800)
    await session.flush()

    resp = await client.get(f"/api/production-plans/{plan.id}/all-positions")
    assert resp.status_code == 200, resp.text
    position = resp.json()[0]
    assert position["quantity_per_hanger"] is None
    assert position["quantity_per_hanger_source"] is None


@pytest.mark.asyncio
async def test_validate_manual_mode_skips_auto_calc(session) -> None:
    """Режим manual не запускает авто-проверку даже при несовместимом габарите."""
    product = await _make_ready_product(session, "FG-MODE-SKIP", auto=True)
    product.hanger_mode = "manual"
    product.mount_width_mm = 2000  # для авто — несовместимый габарит
    product.quantity_per_hanger = {"2800": {"auto": None, "manual": 12}}
    _, position = await _make_plan_position(session, product, length_mm=2800)
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "hanger_calc_zero" not in errors


# ─── #170: норма по конкретной длине — тот же резолвер, что и импорт ───────


def _resolver_product(
    sku: str,
    *,
    hanger_mode: str,
    quantity_per_hanger: dict | int | None = None,
    perimeter_mm: float | None = None,
    mount_width_mm: float | None = None,
) -> Product:
    product = Product(sku=sku, name=f"Resolver {sku}", type=ProductType.finished_good, unit="pcs")
    product.hanger_mode = hanger_mode
    if quantity_per_hanger is not None:
        product.quantity_per_hanger = quantity_per_hanger
    if perimeter_mm is not None:
        product.perimeter_mm = perimeter_mm
    if mount_width_mm is not None:
        product.mount_width_mm = mount_width_mm
    return product


def test_resolve_manual_per_length_by_length_not_primary() -> None:
    """manual + per-length: значение строго по длине; нет ключа → None (не основная)."""
    product = _resolver_product(
        "RES-PER-LEN",
        hanger_mode="manual",
        quantity_per_hanger={
            "2750": {"auto": None, "manual": 5},
            "3000": {"auto": None, "manual": 7},
        },
    )

    assert resolve_position_hanger(product, length_mm=2750, payload_quantity_per_hanger=None).quantity_per_hanger == 5
    assert resolve_position_hanger(product, length_mm=3000, payload_quantity_per_hanger=None).quantity_per_hanger == 7

    missing = resolve_position_hanger(product, length_mm=2600, payload_quantity_per_hanger=None)
    assert missing.quantity_per_hanger is None
    assert missing.source is None


def test_resolve_manual_bare_norm_is_length_independent() -> None:
    """manual + legacy-скаляр: bare-норма длина-независима (#170)."""
    product = _resolver_product("RES-BARE", hanger_mode="manual", quantity_per_hanger=5)

    for length_mm in (2700, 3000, 1234):
        resolved = resolve_position_hanger(product, length_mm=length_mm, payload_quantity_per_hanger=None)
        assert resolved.quantity_per_hanger == 5
        assert resolved.source == "manual"


def test_resolve_auto_norm_computed_by_length_ignores_stored_value() -> None:
    """auto + геометрия: авторасчёт по длине, хранимое manual-значение не используется."""
    product = _resolver_product(
        "RES-AUTO",
        hanger_mode="auto",
        quantity_per_hanger={"auto": None, "manual": 71},
        perimeter_mm=60,
        mount_width_mm=15,
    )

    resolved = resolve_position_hanger(product, length_mm=3000, payload_quantity_per_hanger=None)
    assert resolved.quantity_per_hanger == 72
    assert resolved.source == "auto"


def test_resolve_auto_without_geometry_is_none() -> None:
    """auto без периметра/габарита: N не резолвится, даже при хранимом значении."""
    product = _resolver_product("RES-AUTO-NOGEO", hanger_mode="auto", quantity_per_hanger=71)

    resolved = resolve_position_hanger(product, length_mm=3000, payload_quantity_per_hanger=None)
    assert resolved.quantity_per_hanger is None
    assert resolved.source is None


def test_resolve_payload_override_wins_in_both_modes() -> None:
    """payload-override побеждает и в manual, и в auto."""
    manual = _resolver_product("RES-OVR-MAN", hanger_mode="manual", quantity_per_hanger=5)
    auto = _resolver_product(
        "RES-OVR-AUTO", hanger_mode="auto", perimeter_mm=60, mount_width_mm=15
    )

    for product in (manual, auto):
        resolved = resolve_position_hanger(product, length_mm=3000, payload_quantity_per_hanger=9)
        assert resolved.quantity_per_hanger == 9
        assert resolved.source == "manual"


@pytest.mark.asyncio
async def test_serialize_manual_per_length_uses_position_length(client, session) -> None:
    """Чтение плана даёт тот же N по длине позиции, что и импорт (#170)."""
    product = await _make_ready_product(session, "FG-PER-LEN")
    product.hanger_mode = "manual"
    product.quantity_per_hanger = {
        "2750": {"auto": None, "manual": 5},
        "3000": {"auto": None, "manual": 7},
    }
    plan, _ = await _make_plan_position(session, product, length_mm=2750)
    await session.flush()

    resp = await client.get(f"/api/production-plans/{plan.id}/all-positions")
    assert resp.status_code == 200, resp.text
    position = resp.json()[0]
    assert position["quantity_per_hanger"] == 5
    assert position["quantity_per_hanger_source"] == "manual"


def test_position_dimensions_for_task_edges() -> None:
    """position_dimensions_for_task: вход → единственный выход → None (не выход вместо входа)."""
    from app.models.production_plan import (
        PlanPosition,
        PlanPositionStatus,
        PlanPositionValidationStatus,
        PlanSourceType,
    )
    from app.services.plan_position_hanger import position_dimensions_for_task

    def make_pos(**overrides) -> PlanPosition:
        fields: dict = dict(
            production_plan_id=1,
            source_type=PlanSourceType.manual,
            source_sku="EDGE",
            quantity=Decimal("1"),
            status=PlanPositionStatus.approved,
            validation_status=PlanPositionValidationStatus.valid,
            input_quantity=None,
            input_dimensions=None,
            outputs=[],
        )
        fields.update(overrides)
        return PlanPosition(**fields)

    # Обычная позиция: длина из входа (input_dimensions).
    assert position_dimensions_for_task(
        make_pos(input_dimensions={"length_mm": 2700})
    ) == {"length_mm": 2700}
    # Без входа — длина единственного выхода (это и есть поток).
    assert position_dimensions_for_task(
        make_pos(outputs=[{"quantity": "1", "dimensions": {"length_mm": 900}}])
    ) == {"length_mm": 900}
    # Трансформирующая (есть input_quantity) без длины входа — выход НЕ подставляем.
    assert position_dimensions_for_task(
        make_pos(
            input_quantity=Decimal("100"),
            outputs=[{"quantity": "1", "dimensions": {"length_mm": 900}}],
        )
    ) is None
    # Без размеров — безразмерные штуки.
    assert position_dimensions_for_task(make_pos()) is None


# ─── #171: парная позиция — снапшот product_pair и ручной override ─────────────


async def _make_pair_components(
    session,
    sku_a: str,
    sku_b: str,
    *,
    manual_n: int | None = None,
    length_mm: int = 2700,
) -> ProductPair:
    """Пара сырьевых артикулов с общей длиной; manual_n=None — без ручной нормы."""
    comp_a = Product(sku=sku_a, name=f"Pair {sku_a}", type=ProductType.component, unit="pcs")
    comp_b = Product(sku=sku_b, name=f"Pair {sku_b}", type=ProductType.component, unit="pcs")
    session.add_all([comp_a, comp_b])
    await session.flush()
    session.add_all([
        ProductLength(product_id=comp_a.id, length_mm=length_mm),
        ProductLength(product_id=comp_b.id, length_mm=length_mm),
    ])
    quantity = {str(length_mm): {"auto": None, "manual": manual_n}} if manual_n is not None else {}
    pair = ProductPair(
        product_a_id=min(comp_a.id, comp_b.id),
        product_b_id=max(comp_a.id, comp_b.id),
        quantity_per_hanger=quantity,
    )
    session.add(pair)
    await session.flush()
    return pair


async def _make_pair_position(
    session,
    payload: dict,
    *,
    length_mm: int = 2700,
    plan_no: str,
) -> tuple[ProductionPlan, PlanPosition]:
    """Парная позиция плана: product_id=None, payload с paired_profile."""
    plan = ProductionPlan(
        plan_no=plan_no,
        name=plan_no,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()
    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=None,
        source_type=PlanSourceType.excel_import,
        source_sku="PAIR-POS",
        source_name="Pair position",
        quantity=Decimal("100"),
        input_dimensions={"length_mm": length_mm},
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


def _pair_payload(
    *,
    snapshot: bool,
    override: int | None = None,
    sku_a: str = "PAIR-A",
    sku_b: str = "PAIR-B",
) -> dict:
    """Payload парной позиции: компоненты + опционально снапшот и override."""
    payload: dict = {
        "paired_profile": True,
        "components": [{"sku": sku_a}, {"sku": sku_b}],
    }
    if snapshot:
        payload["product_pair"] = {
            "resolved": True,
            "quantity_per_hanger": 8,
            "source": "manual",
            "inputs": [{"sku": sku_a}, {"sku": sku_b}],
        }
    if override is not None:
        payload["quantity_per_hanger"] = override
    return payload


@pytest.mark.asyncio
async def test_serialize_paired_position_n_from_snapshot(client, session) -> None:
    """Парная позиция без override берёт N и source из снапшота product_pair."""
    plan, _ = await _make_pair_position(
        session, _pair_payload(snapshot=True), plan_no="PLAN-PAIR-SNAP",
    )
    await session.flush()

    resp = await client.get(f"/api/production-plans/{plan.id}/all-positions")
    assert resp.status_code == 200, resp.text
    position = resp.json()[0]
    assert position["quantity_per_hanger"] == 8
    assert position["quantity_per_hanger_source"] == "manual"


@pytest.mark.asyncio
async def test_serialize_paired_position_override_wins_and_null_clears(client, session) -> None:
    """Override побеждает снапшот; явный null снимает override, отсутствие поля — нет."""
    plan, position = await _make_pair_position(
        session, _pair_payload(snapshot=True, override=5), plan_no="PLAN-PAIR-OVR",
    )
    await session.flush()

    resp = await client.get(f"/api/production-plans/{plan.id}/all-positions")
    assert resp.status_code == 200, resp.text
    paired = resp.json()[0]
    assert paired["quantity_per_hanger"] == 5
    assert paired["quantity_per_hanger_source"] == "manual"

    url = f"/api/production-plans/{plan.id}/positions/{position.id}/quantity"

    # Явный null — ручной override снят, норма снова из снапшота.
    cleared = await client.patch(url, json={"quantity": 20, "quantity_per_hanger": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["quantity_per_hanger"] == 8
    assert cleared.json()["quantity_per_hanger_source"] == "manual"
    assert "quantity_per_hanger" not in position.source_payload

    # Новое число — override записан и побеждает снапшот.
    written = await client.patch(url, json={"quantity": 20, "quantity_per_hanger": 4})
    assert written.status_code == 200, written.text
    assert written.json()["quantity_per_hanger"] == 4
    assert written.json()["quantity_per_hanger_source"] == "manual"
    assert position.source_payload["quantity_per_hanger"] == 4

    # Поле отсутствует в теле — существующий override не трогаем.
    absent = await client.patch(url, json={"quantity": 20})
    assert absent.status_code == 200, absent.text
    assert absent.json()["quantity_per_hanger"] == 4
    assert position.source_payload["quantity_per_hanger"] == 4


@pytest.mark.asyncio
async def test_serialize_paired_position_n_from_dictionary(client, session) -> None:
    """Без снапшота N пары резолвится из product_pairs по SKU-компонентам."""
    await _make_pair_components(session, "PAIR-DICT-A", "PAIR-DICT-B", manual_n=8)
    plan, _ = await _make_pair_position(
        session,
        _pair_payload(snapshot=False, sku_a="PAIR-DICT-A", sku_b="PAIR-DICT-B"),
        plan_no="PLAN-PAIR-DICT",
    )
    await session.flush()

    resp = await client.get(f"/api/production-plans/{plan.id}/all-positions")
    assert resp.status_code == 200, resp.text
    position = resp.json()[0]
    assert position["quantity_per_hanger"] == 8
    assert position["quantity_per_hanger_source"] == "manual"


@pytest.mark.asyncio
async def test_validate_paired_position_override_suppresses_calc_error(session) -> None:
    """Override подавляет hanger_calc_zero пары без ручной и авто-нормы."""
    await _make_pair_components(session, "PAIR-NON-A", "PAIR-NON-B", manual_n=None)
    _, position = await _make_pair_position(
        session,
        _pair_payload(snapshot=False, override=5, sku_a="PAIR-NON-A", sku_b="PAIR-NON-B"),
        plan_no="PLAN-PAIR-NON",
    )
    await session.flush()

    errors = await validate_plan_position(session, position)
    assert "hanger_calc_zero" not in errors
    assert "product_pair_not_found" not in errors
