from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from app.core.config import settings
from app.models.defect import Defect
from app.models.internal_plan import InternalPlan, SectionPlanLine
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionRouteMatchQuality,
    PlanPositionRouteOrigin,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.release_batch import ReleaseBatch, ReleaseBatchPosition
from app.models.rework_task import ReworkTask
from app.models.route import RouteRuleProfile, RouteSelectionRule, SectionOperation
from app.models.section import Section
from app.models.transfer import Transfer
from app.models.work_task import WorkTask
from app.seeds.canon.quality_data import DEFECT_TYPES
from app.seeds.import_templates import IMPORT_TEMPLATES
from app.seeds.route_rule_profiles import ROUTE_RULE_PROFILES
from app.seeds.routes import ROUTES
from app.seeds.sections import SECTION_OPS, SECTIONS_DATA
from app.seeds.selection_rules import SELECTION_RULES
from app.services.route_selection import select_route_for_payload
from app.stock.models import StockBalance, StockTransaction
from sqlalchemy import func, select


def _declared_rule_codes() -> set[str]:
    """Коды правил отбора, объявленных в сиде."""
    return {rule["code"] for rule in SELECTION_RULES}


def _declared_operation_codes() -> set[tuple[str, str]]:
    """Пары (участок, операция) из объявления сида.

    Операция без кода — placeholder, резолвится динамически и в справочник
    не попадает, поэтому в множество не входит.
    """
    return {
        (section_code, op[3])
        for section_code, ops in SECTION_OPS.items()
        for op in ops
        if op[3] is not None
    }


def _expected_seed_summary() -> dict[str, int]:
    """Сводка сида, посчитанная по объявлению, а не по зафиксированным числам.

    Смысл проверки — «сколько создаст» и «сколько создалось» не разъезжаются:
    иначе пропавшее из сида правило или операция никто не заметит.
    """
    return {
        "import_templates": len(IMPORT_TEMPLATES),
        "route_rule_profiles": len(ROUTE_RULE_PROFILES),
        # Статический маршрут + по одному динамическому на профиль с этапами.
        "routes": len(ROUTES)
        + sum(1 for profile in ROUTE_RULE_PROFILES if profile.get("route_sections")),
        "selection_rules": len(SELECTION_RULES),
        "sections": len(SECTIONS_DATA),
        "section_operations": len(_declared_operation_codes()),
        "defect_types": len(DEFECT_TYPES),
    }


#: Пила различает рез по целевой длине и раскрой в несколько длин (#226/#277),
#: упаковка — вид и сборку (#226). Без этих операций в справочнике строка
#: плана осталась бы с дефолтной `SAW`/`PACK`, и колонка плана перестала бы
#: что-либо различать.
SAWING_LENGTH_OPS = {"SAW_0900", "SAW_1350", "SAW_1800", "SAW_2700", "SAW_MULTI", "SAW_CUT"}
PACKING_VARIANT_OPS = {"PACK_GLUE", "PACK_LENS"}

#: Правила, которые назначают эти операции и снимают с упаковочной строки
#: участки, которых на плане нет.
SAWING_LENGTH_RULES = {
    "saw_length_0900",
    "saw_length_1350",
    "saw_length_1800",
    "saw_length_2700",
    "saw_multi_length",
    "saw_cut_any_length",
}
PACKING_ROUTE_RULES = {"pack_glue_route", "pack_lens_route"}
PACKING_TYPE_RULES = {"pack_glue_types", "pack_lens_types"}


async def _seeded_rule_codes(session) -> set[str]:
    return set((await session.scalars(select(RouteSelectionRule.code))).all())


async def _seeded_operation_codes(session) -> set[tuple[str, str]]:
    rows = await session.execute(
        select(Section.code, SectionOperation.operation_code).join(
            Section, Section.id == SectionOperation.section_id
        )
    )
    return set(rows.all())


DEFAULT_SECTIONS = [
    {"code": "RAW_STOCK", "name": "Склад сырья", "sort_order": 10, "type": "raw_stock"},
    {"code": "DRILLING", "name": "Сверловка", "sort_order": 20, "type": "production"},
    {"code": "PRESSING", "name": "Пресс", "sort_order": 30, "type": "production"},
    {"code": "SHOT_BLAST", "name": "Дробеструй", "sort_order": 40, "type": "production"},
    {"code": "PREP_STOCK", "name": "Склад подготовки", "sort_order": 45, "type": "wip_stock"},
    {"code": "ANODIZING", "name": "Анодирование", "sort_order": 50, "type": "production"},
    {"code": "WIP_STOCK", "name": "Склад полуфабриката", "sort_order": 60, "type": "wip_stock"},
    {"code": "SAWING", "name": "Пила", "sort_order": 70, "type": "production"},
    {"code": "PACKING", "name": "Упаковка", "sort_order": 80, "type": "production"},
    {"code": "FINISHED_STOCK", "name": "Склад готовой продукции", "sort_order": 90, "type": "finished_stock"},
    {"code": "SHIPMENT", "name": "К отгрузке", "sort_order": 100, "type": "finished_stock"},
    {"code": "SHIPPED", "name": "Отправлено", "sort_order": 110, "type": "finished_stock"},
]


async def _seed_default_sections(session) -> None:
    for item in DEFAULT_SECTIONS:
        session.add(Section(code=item["code"], name=item["name"], sort_order=item["sort_order"], type=item["type"], is_active=True))
    await session.commit()


async def _count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


async def _make_releasable_position(session, route_name: str = "Универсальный маршрут РП") -> tuple[ProductionPlan, PlanPosition]:
    from app.models.route import ProductionRoute

    route = await session.scalar(
        select(ProductionRoute).where(
            (ProductionRoute.name == route_name) | (ProductionRoute.code == "universal_rp")
        )
    )
    assert route is not None, f"Route not found: {route_name!r} / universal_rp"
    product = Product(sku=f"ЮП-TEST-{datetime.now(UTC).timestamp()}", name="Микроплинтус тест", type=ProductType.finished_good, unit="pcs")
    session.add(product)
    await session.flush()

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
        quantity=Decimal(3021),
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
    assert data == _expected_seed_summary()

    # Правила отбора в БД — ровно объявленный набор кодов: ни потерянных,
    # ни лишних, ни задвоенных.
    assert await _seeded_rule_codes(session) == _declared_rule_codes()

    # Операции участков — справочник совпадает с объявлением по парам
    # (участок, операция): иначе резолв операции строки плана уходит в никуда.
    assert await _seeded_operation_codes(session) == _declared_operation_codes()

    # idempotency/update behavior
    response2 = await client.post("/api/routes-seed")
    assert response2.status_code == 201
    data2 = response2.json()
    assert data2 == data
    # Повторный сид не плодит дубли: тот же набор кодов и тот же состав.
    assert await _seeded_rule_codes(session) == _declared_rule_codes()
    assert await _seeded_operation_codes(session) == _declared_operation_codes()


@pytest.mark.asyncio
async def test_seed_lands_the_declared_sawing_and_packing_operations(client, session) -> None:
    """#226: резка по длине и вид упаковки — операции справочника.

    Сверка по кодам, а не по количеству: операция, объявленная сидом и
    потерявшаяся при seeding, не сдвинет счётчик — она просто исчезнет.
    """
    await _seed_default_sections(session)
    assert (await client.post("/api/routes-seed")).status_code == 201

    operations_by_section: dict[str, set[str]] = {}
    for section_code, operation_code in await _seeded_operation_codes(session):
        operations_by_section.setdefault(section_code, set()).add(operation_code)

    assert operations_by_section["SAWING"] >= SAWING_LENGTH_OPS
    assert operations_by_section["PACKING"] >= PACKING_VARIANT_OPS

    rule_codes = await _seeded_rule_codes(session)
    assert rule_codes >= SAWING_LENGTH_RULES | PACKING_ROUTE_RULES | PACKING_TYPE_RULES


@pytest.mark.asyncio
async def test_route_selection_rule_can_be_updated(client, session) -> None:
    await _seed_default_sections(session)

    response = await client.post("/api/routes-seed")
    assert response.status_code == 201
    rules_response = await client.get("/api/route-selection-rules")
    assert rules_response.status_code == 200
    rule = rules_response.json()[0]
    drill = await session.scalar(select(Section).where(Section.code == "DRILLING"))

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
    assert "DRILLING" in required_codes
    # PRESS should be excluded (from global_drill rule)
    excluded_codes = {s["code"] for s in result.excluded_sections}
    assert "PRESSING" in excluded_codes


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
    assert "WIP_STOCK" in excluded_codes
    assert "SAWING" in excluded_codes
    assert "PACKING" in excluded_codes


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
    assert release_response.json()["tasks_created"] == 6

    force_response = await client.post("/api/routes-seed?force=true")
    assert force_response.status_code == 201
    assert force_response.json() == _expected_seed_summary()

    for model in (
        ReleaseBatchPosition,
        ReleaseBatch,
        InternalPlan,
        SectionPlanLine,
        WorkTask,
        StockTransaction,
        StockBalance,
        Transfer,
        Defect,
        ReworkTask,
        PlanPosition,
        ProductionPlan,
    ):
        assert await _count(session, model) == 0

    # Force-сид пересоздаёт справочник целиком: после очистки в нём снова
    # весь объявленный набор — правил по кодам и операций по парам.
    assert await _seeded_rule_codes(session) == _declared_rule_codes()
    assert await _seeded_operation_codes(session) == _declared_operation_codes()


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
    assert len(snapshot_steps) == 12

    release_response = await client.post(f"/api/release-batches/{batch['id']}/release")
    assert release_response.status_code == 200
    released = release_response.json()
    assert released["tasks_created"] == 6
    assert released["task_count"] == 6
    assert await _count(session, WorkTask) == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("env_value", ["prod", "production"])
async def test_force_seed_is_forbidden_in_production(client, session, monkeypatch, env_value) -> None:
    await _seed_default_sections(session)
    monkeypatch.setattr(settings, "ENV", env_value)

    response = await client.post("/api/routes-seed?force=true")

    assert response.status_code == 403
    assert response.json()["detail"] == "force=true запрещён на продуктивной среде"


@pytest.mark.asyncio
async def test_cleanup_endpoints(client, session) -> None:
    # 1. Заполняем секции по умолчанию
    await _seed_default_sections(session)
    
    # Добавим одну операцию участка для проверки
    from app.models.route import SectionOperation
    section = await session.scalar(select(Section).where(Section.code == "RAW_STOCK"))
    op = SectionOperation(section_id=section.id, operation_code="OP_TEST", operation_name="Test Op")
    session.add(op)
    await session.commit()

    # 2. Проверяем cleanup-stats
    stats_response = await client.get("/api/routes-seed/cleanup-stats")
    assert stats_response.status_code == 200
    stats_data = stats_response.json()
    assert "stats" in stats_data
    assert stats_data["stats"]["sections"] == 12
    assert stats_data["stats"]["section_operations"] == 1

    # 3. Вызываем cleanup с неправильной таблицей для проверки валидации
    bad_cleanup = await client.post("/api/routes-seed/cleanup", json={"tables": ["users", "invalid_table_name"]})
    assert bad_cleanup.status_code == 400

    # 4. Выполняем очистку только операций участков
    cleanup_response = await client.post("/api/routes-seed/cleanup", json={"tables": ["section_operations"]})
    assert cleanup_response.status_code == 204

    # 5. Проверяем, что операции удалены, а секции остались на месте
    stats_response = await client.get("/api/routes-seed/cleanup-stats")
    assert stats_response.json()["stats"]["section_operations"] == 0
    assert stats_response.json()["stats"]["sections"] == 12

    # 6. Очищаем секции
    cleanup_sections = await client.post("/api/routes-seed/cleanup", json={"tables": ["sections"]})
    assert cleanup_sections.status_code == 204

    stats_response = await client.get("/api/routes-seed/cleanup-stats")
    assert stats_response.json()["stats"]["sections"] == 0

    # 7. Проверяем очистку import_templates с внешним ключом в route_rule_profiles
    from app.models.import_template import ImportTemplate
    from app.models.route import RouteRuleProfile

    template = ImportTemplate(name="Test Template")
    session.add(template)
    await session.flush()

    profile = RouteRuleProfile(
        code="TEST_CODE",
        name="Test Profile",
        import_template_id=template.id,
    )
    session.add(profile)
    await session.commit()

    # Проверяем, что статистика показывает их наличие
    stats_response = await client.get("/api/routes-seed/cleanup-stats")
    assert stats_response.json()["stats"]["import_templates"] == 1
    assert stats_response.json()["stats"]["route_rule_profiles"] == 1

    # Запускаем очистку только шаблонов импорта
    cleanup_templates = await client.post("/api/routes-seed/cleanup", json={"tables": ["import_templates"]})
    assert cleanup_templates.status_code == 204

    # Проверяем, что шаблон удален, а профиль остался, но его FK сброшен в NULL
    stats_response = await client.get("/api/routes-seed/cleanup-stats")
    assert stats_response.json()["stats"]["import_templates"] == 0
    assert stats_response.json()["stats"]["route_rule_profiles"] == 1

    # Обновляем объект из БД
    await session.refresh(profile)
    assert profile.import_template_id is None


@pytest.mark.asyncio
async def test_cleanup_stats_exposes_stock_ledger_not_legacy_tables(client, session) -> None:
    """Статистика очистки отражает Stock Ledger, а не удалённые movements/spg_remainders."""
    response = await client.get("/api/routes-seed/cleanup-stats")
    assert response.status_code == 200
    stats = response.json()["stats"]
    assert "stock_transactions" in stats
    assert "stock_balances" in stats
    assert "movements" not in stats
    assert "spg_remainders" not in stats


@pytest.mark.asyncio
async def test_cleanup_transfers_does_not_query_legacy_movements(client, session) -> None:
    """Очистка transfers не выполняет UPDATE по удалённой таблице movements."""
    cleanup_response = await client.post("/api/routes-seed/cleanup", json={"tables": ["transfers"]})
    assert cleanup_response.status_code == 204, cleanup_response.text
