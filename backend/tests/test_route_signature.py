"""Сигнатура маршрута (#214, ADR-0045).

Сигнатура — упорядоченный набор шагов с признаками этапа; она, а не имя,
делает два маршрута одним. Считается из ВХОДА сборки (профиль минус
исключённые участки плюс разрешённые операции), а не из записанных этапов:
сверка, читающая обе стороны из базы, сравнивает базу саму с собой.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.imports import ImportBatch, ImportBatchMode, ImportBatchStatus, ImportFile
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanChangeItemStatus,
    PlanChangeSet,
    PlanPosition,
    PlanPositionRouteOrigin,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)

from app.models.route import (
    ProductionRoute,
    RouteOperation,
    RouteRuleProfile,
    RouteSelectionRule,
    RouteStage,
    SectionOperation,
)
from app.models.section import Section
from app.seeds.run_seed import run_full_seed
from app.services.plan_import_service import _make_change_items
from app.services.production_plan_service import apply_change_set
from app.services.route_builder import build_route_from_profile
from app.services.route_signature import (
    auto_route_code,
    encode_signature,
    signature_for_route_stages,
    signature_steps_from_stages,
)


async def _signature_steps(session, route_id: int) -> list:
    stages = (
        await session.execute(
            select(RouteStage)
            .where(RouteStage.route_id == route_id)
            .options(
                selectinload(RouteStage.operations),
                selectinload(RouteStage.section),
                selectinload(RouteStage.storage_section),
            )
            .order_by(RouteStage.sequence)
        )
    ).scalars().all()
    return signature_steps_from_stages(stages)


PROFILE_SECTIONS = ["RAW_STOCK", "SAWING", "PACKING", "FINISHED_STOCK"]


async def _seed_sections(session) -> None:
    """Склад сырья → пила → упаковка → склад готовой продукции."""
    for code, name, sort_order, section_type in (
        ("RAW_STOCK", "Склад сырья", 10, "raw_stock"),
        ("SAWING", "Пила", 20, "production"),
        ("PACKING", "Упаковка", 30, "production"),
        ("FINISHED_STOCK", "Склад готовой продукции", 40, "finished_stock"),
    ):
        session.add(Section(code=code, name=name, sort_order=sort_order, type=section_type, is_active=True))
    await session.flush()

    sawing = await session.scalar(select(Section).where(Section.code == "SAWING"))
    session.add(SectionOperation(
        section_id=sawing.id,
        operation_code="SAW",
        operation_name="Распил",
        group_code="SAW",
        group_name="Пиление",
        is_significant=True,
        transforms_dimensions=True,
        sort_order=1,
    ))
    packing = await session.scalar(select(Section).where(Section.code == "PACKING"))
    session.add(SectionOperation(
        section_id=packing.id,
        operation_code="PACK_STRETCH",
        operation_name="Стрейч",
        group_code="PACK",
        group_name="Упаковка",
        is_significant=False,
        sort_order=1,
    ))
    await session.commit()


async def _make_profile(session, *, code: str = "sig_profile", sections=None) -> RouteRuleProfile:
    profile = RouteRuleProfile(
        code=code,
        name="Профиль подписи",
        is_active=True,
        priority=1000,
        route_sections=list(sections or PROFILE_SECTIONS),
    )
    session.add(profile)
    await session.commit()
    return profile


@pytest.mark.asyncio
async def test_built_route_carries_signature_of_its_steps(session) -> None:
    """Сборка из профиля даёт сигнатуру: склад — транзитом, признаки этапа — в ней."""
    await _seed_sections(session)
    profile = await _make_profile(session)

    built = await build_route_from_profile(session, profile, {"output_kind": "ГП"})

    assert built.error is None
    assert built.signature == (
        "transit:RAW_STOCK::0:0:0"
        ">production:SAWING:SAW:1:1:0"
        ">production:PACKING:PACK_STRETCH:0:0:0"
        ">transit:FINISHED_STOCK::0:0:1"
    )


class ParsedRow:
    """Минимальный образ разобранной строки плана (как в тестах импорта)."""

    def __init__(self, sku: str, name: str, quantity: Decimal, payload: dict):
        self.source_sku = sku
        self.source_name = name
        self.quantity = quantity
        self.payload = payload
        self.source_row_number = 1
        self.source_row_numbers = [1]
        self.source_ref = None
        self.source_fingerprint = f"{sku}_{name}_{quantity}"
        self.source_row_hash = f"hash_{sku}"
        self.input_quantity = None
        self.input_dimensions = None
        self.outputs: list = []
        self.warnings: list = []
        self.errors: list = []


@pytest.mark.asyncio
async def test_import_writes_stage_significance_by_any_step_of_group(session) -> None:
    """Запись и сборка считают значимость этапа одинаково: этап значим, если
    значим хотя бы один шаг группы (#221).

    Участок с двумя группами, где первая незначимая, а вторая значимая, — и
    есть тот случай, где «первый шаг» и «любой шаг» расходятся. Импорт
    обязан записать ``is_significant = 1`` именно по этому признаку, и тогда
    сохранённая сигнатура совпадает с сигнатурой по записанным этапам.
    """
    await _seed_sections(session)
    sawing = await session.scalar(select(Section).where(Section.code == "SAWING"))
    session.add(SectionOperation(
        section_id=sawing.id,
        operation_code="SAW_PREP",
        operation_name="Разметка",
        group_code="SAW_PREP_GRP",
        group_name="Разметка",
        is_significant=False,
        sort_order=0,
    ))
    await session.commit()
    profile = await _make_profile(session)
    product = Product(sku="FG-SIG", name="Артикул подписи", type=ProductType.finished_good, unit="pcs")
    session.add(product)
    await session.commit()

    items, _diagnostics = await _make_change_items(
        session,
        change_set_id=1,
        parsed_rows=[ParsedRow("FG-SIG", "Артикул подписи", Decimal("10"), {"output_kind": "ГП"})],
        products_by_sku={"fg-sig": product},
        mode=None,
        existing_positions=[],
        rule_profile_id=profile.id,
        template_id=None,
    )

    route_id = items[0].after_data.get("route_id")
    assert route_id is not None
    route = await session.get(ProductionRoute, route_id)

    from_build_input = (
        "transit:RAW_STOCK::0:0:0"
        ">production:SAWING:SAW_PREP,SAW:1:1:0"
        ">production:PACKING:PACK_STRETCH:0:0:0"
        ">transit:FINISHED_STOCK::0:0:1"
    )
    assert route.route_signature == from_build_input

    # Записанный этап значим по ЛЮБОМУ шагу группы: первый шаг незначимый.
    sawing_stage = await session.scalar(
        select(RouteStage).where(
            RouteStage.route_id == route.id,
            RouteStage.section_id == sawing.id,
        )
    )
    assert sawing_stage.is_significant is True

    # Регресс в том же маршруте: незначимая упаковка и транзитные этапы
    # складов остались незначимыми — расхождения нет нигде.
    assert await signature_for_route_stages(session, route.id) == from_build_input


@pytest.mark.asyncio
async def test_seed_routes_sharing_sections_differ_by_stage_significance(session) -> None:
    """Два сид-маршрута завода с одинаковым набором участков и пустыми кодами
    операций различаются только признаком значимости этапа — и сигнатуры у
    них разные. Сигнатура из одних пар «участок + операция» их бы не различила.
    """
    await run_full_seed(session, force=True)

    universal = await session.scalar(
        select(ProductionRoute).where(ProductionRoute.code == "universal_rp")
    )
    dynamic = await session.scalar(
        select(ProductionRoute).where(ProductionRoute.code == "dynamic_packaging_map_rp")
    )
    assert universal is not None and dynamic is not None

    universal_steps = await _signature_steps(session, universal.id)
    dynamic_steps = await _signature_steps(session, dynamic.id)

    assert [
        (step.stage_kind, step.section_code, step.operation_codes,
         step.transforms_dimensions, step.is_final)
        for step in universal_steps
    ] == [
        (step.stage_kind, step.section_code, step.operation_codes,
         step.transforms_dimensions, step.is_final)
        for step in dynamic_steps
    ], "фикстура: маршруты должны совпадать во всём, кроме значимости этапа"
    assert [step.is_significant for step in universal_steps] != [
        step.is_significant for step in dynamic_steps
    ]

    assert universal.route_signature != dynamic.route_signature
    assert universal.route_signature == encode_signature(universal_steps)
    assert dynamic.route_signature == encode_signature(dynamic_steps)


async def _make_position_with_route(
    session,
    profile: RouteRuleProfile,
    route: ProductionRoute,
    *,
    sku: str = "FG-CHECK",
) -> tuple:
    """Позиция плана, импортированная профилем и обслуживаемая маршрутом."""
    plan = ProductionPlan(
        plan_no=f"PLAN-{sku}",
        name="План проверки",
        status=ProductionPlanStatus.draft,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
    )
    file = ImportFile(
        original_filename="plan.xlsx",
        stored_path="plan.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_extension=".xlsx",
        detected_format="zip-workbook",
        file_sha256=f"sig-{sku}",
        size_bytes=10,
    )
    product = Product(sku=sku, name="Позиция проверки", type=ProductType.finished_good, unit="pcs")
    session.add_all([plan, file, product])
    await session.flush()
    batch = ImportBatch(
        source_file_id=file.id,
        production_plan_id=plan.id,
        rule_profile_id=profile.id,
        mode=ImportBatchMode.create_plan,
        status=ImportBatchStatus.applied,
        sheet_name="Лист1",
        header_row_number=1,
        total_rows=1,
        parsed_rows=1,
        summary={},
    )
    session.add(batch)
    await session.flush()
    position = PlanPosition(
        production_plan_id=plan.id,
        import_batch_id=batch.id,
        product_id=product.id,
        source_type=PlanSourceType.excel_import,
        source_sku=sku,
        source_name="Позиция проверки",
        quantity=Decimal("10"),
        source_payload={"output_kind": "ГП"},
        period_start=plan.period_start,
        period_end=plan.period_end,
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        route_id=route.id,
        route_origin=PlanPositionRouteOrigin.manual_confirmed,
        route_assigned_at=datetime.now(UTC),
        route_manual_confirmed_at=datetime.now(UTC),
    )
    session.add(position)
    await session.commit()
    return plan, position


async def _make_route_with_signature(session, name: str, signature: str) -> ProductionRoute:
    """Маршрут с этапами профиля и сохранённой сигнатурой."""
    sections = {
        code: await session.scalar(select(Section).where(Section.code == code))
        for code in ("RAW_STOCK", "SAWING", "PACKING", "FINISHED_STOCK")
    }
    route = ProductionRoute(name=name, is_active=True, route_signature=signature)
    session.add(route)
    await session.flush()
    for sequence, (code, operation_code, is_significant, transforms) in enumerate((
        ("RAW_STOCK", None, False, False),
        ("SAWING", "SAW", True, True),
        ("PACKING", "PACK_STRETCH", False, False),
        ("FINISHED_STOCK", None, False, False),
    ), start=1):
        section = sections[code]
        transit = section.type in ("raw_stock", "finished_stock")
        stage = RouteStage(
            route_id=route.id,
            sequence=sequence,
            section_id=None if transit else section.id,
            stage_kind="transit" if transit else "production",
            storage_section_id=section.id if transit else None,
            is_significant=is_significant,
            transforms_dimensions=transforms,
            is_final=sequence == 4,
        )
        session.add(stage)
        await session.flush()
        if not transit:
            session.add(RouteOperation(
                route_stage_id=stage.id,
                sequence=1,
                operation_code=operation_code,
                operation_name=operation_code or "",
            ))
    await session.commit()
    return route


MATCHED_SIGNATURE = (
    "transit:RAW_STOCK::0:0:0"
    ">production:SAWING:SAW:1:1:0"
    ">production:PACKING:PACK_STRETCH:0:0:0"
    ">transit:FINISHED_STOCK::0:0:1"
)

FOREIGN_SIGNATURE = (
    "production:SAWING:SAW:1:1:1"
)


@pytest.mark.asyncio
async def test_route_check_shows_matching_signatures(client, session) -> None:
    """Проверка маршрута позиции показывает обе сигнатуры и вердикт «совпадает»."""
    await _seed_sections(session)
    profile = await _make_profile(session)
    route = await _make_route_with_signature(session, "Совпадающий", MATCHED_SIGNATURE)
    plan, position = await _make_position_with_route(session, profile, route)

    response = await client.get(
        f"/api/production-plans/{plan.id}/positions/{position.id}/route-check"
    )

    assert response.status_code == 200
    check = response.json()["route_signature"]
    assert check["verdict"] == "match"
    assert check["expected"] == MATCHED_SIGNATURE
    assert check["actual"] == MATCHED_SIGNATURE
    assert [step["section_code"] for step in check["expected_steps"]] == [
        "RAW_STOCK", "SAWING", "PACKING", "FINISHED_STOCK",
    ]
    assert [step["section_code"] for step in check["actual_steps"]] == [
        "RAW_STOCK", "SAWING", "PACKING", "FINISHED_STOCK",
    ]



SECTION_NAMES_BY_CODE = {
    "RAW_STOCK": "Склад сырья",
    "SAWING": "Пила",
    "PACKING": "Упаковка",
    "FINISHED_STOCK": "Склад готовой продукции",
}


def _assert_section_names_from_catalog(steps: list) -> None:
    """Имя участка в проверке — из справочника, а не из кода."""
    for step in steps:
        assert step["section_name"] == SECTION_NAMES_BY_CODE[step["section_code"]]


@pytest.mark.asyncio
async def test_route_check_shows_section_and_operation_names(client, session) -> None:
    """Проверка маршрута подписывает шаги по-русски: участок — именем из
    справочника, производственный шаг — именами операций, столько же,
    сколько кодов, чтобы строки читались, а не угадывались.
    """
    await _seed_sections(session)
    profile = await _make_profile(session)
    route = await _make_route_with_signature(session, "Совпадающий", MATCHED_SIGNATURE)
    plan, position = await _make_position_with_route(session, profile, route)

    response = await client.get(
        f"/api/production-plans/{plan.id}/positions/{position.id}/route-check"
    )

    assert response.status_code == 200
    check = response.json()["route_signature"]
    _assert_section_names_from_catalog(check["expected_steps"])
    _assert_section_names_from_catalog(check["actual_steps"])

    # Ожидаемая сторона собрана профилем: имена операций — из справочника.
    expected_names = {
        step["section_code"]: step["operation_names"]
        for step in check["expected_steps"]
    }
    assert expected_names["SAWING"] == ["Распил"]
    assert expected_names["PACKING"] == ["Стрейч"]

    # Фактическая сторона — записанные этапы: у каждой операции столько же
    # имён, сколько кодов, и ни одного шага без имён.
    for step in check["actual_steps"]:
        assert len(step["operation_names"]) == len(step["operation_codes"])
        if step["stage_kind"] == "production":
            assert step["operation_names"]


@pytest.mark.asyncio
async def test_route_check_section_rename_keeps_verdict_and_signature(client, session) -> None:
    """Переименование участка — подпись, а не тождество: вердикт и обе
    сигнатуры прежние (нового имени в них нет), но оператор видит в шагах
    маршрута актуальное название участка.
    """
    await _seed_sections(session)
    profile = await _make_profile(session)
    route = await _make_route_with_signature(session, "Совпадающий", MATCHED_SIGNATURE)
    plan, position = await _make_position_with_route(session, profile, route)
    url = f"/api/production-plans/{plan.id}/positions/{position.id}/route-check"

    before = (await client.get(url)).json()["route_signature"]
    assert before["verdict"] == "match"

    sawing = await session.scalar(select(Section).where(Section.code == "SAWING"))
    sawing.name = "Пиление корпусов"
    await session.commit()
    await session.refresh(sawing)

    after = (await client.get(url)).json()["route_signature"]

    assert after["verdict"] == "match"
    assert after["expected"] == MATCHED_SIGNATURE
    assert after["actual"] == MATCHED_SIGNATURE
    assert "Пиление корпусов" not in after["actual"]
    assert {step["section_code"]: step["section_name"] for step in after["actual_steps"]}[
        "SAWING"
    ] == "Пиление корпусов"


@pytest.mark.asyncio
async def test_route_check_reports_mismatch_and_blocks_nothing(auth_client, session) -> None:
    """Расхождение видно в проверке, но утверждение позиции работает как раньше."""
    await _seed_sections(session)
    profile = await _make_profile(session)
    route = await _make_route_with_signature(session, "Чужой", FOREIGN_SIGNATURE)
    plan, position = await _make_position_with_route(session, profile, route)

    response = await auth_client.get(
        f"/api/production-plans/{plan.id}/positions/{position.id}/route-check"
    )

    assert response.status_code == 200
    check = response.json()["route_signature"]
    assert check["verdict"] == "mismatch"
    assert check["expected"] == MATCHED_SIGNATURE
    assert check["actual"] == FOREIGN_SIGNATURE

    approve = await auth_client.post(
        f"/api/production-plans/{plan.id}/positions/{position.id}/approve"
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_manual_rename_keeps_route_signature(client, session) -> None:
    """Ручное переименование маршрута — подпись, а не тождество: сигнатура
    маршрута, собранного в UI из этапов, после переименования та же.
    """
    await _seed_sections(session)
    section_ids = {
        code: (await session.scalar(select(Section).where(Section.code == code))).id
        for code in ("SAWING", "PACKING")
    }

    created = await client.post("/api/routes", json={"name": "Маршрут оператора"})
    assert created.status_code == 201, created.text
    route_id = created.json()["id"]

    steps = await client.put(
        f"/api/routes/{route_id}/steps",
        json=[
            {
                "sequence": 1,
                "section_id": section_ids["SAWING"],
                "operation_code": "SAW",
                "operation_name": "Распил",
                "is_final": False,
            },
            {
                "sequence": 2,
                "section_id": section_ids["PACKING"],
                "operation_code": "PACK_STRETCH",
                "operation_name": "Стрейч",
                "is_final": True,
            },
        ],
    )
    assert steps.status_code == 200, steps.text

    route = await session.get(ProductionRoute, route_id)
    assert route.route_signature == "production:SAWING:SAW:0:1:0>production:PACKING:PACK_STRETCH:0:0:1"

    renamed = await client.put(
        f"/api/routes/{route_id}", json={"name": "Маршрут оператора (переименован)"}
    )
    assert renamed.status_code == 200, renamed.text

    await session.refresh(route)
    assert route.name == "Маршрут оператора (переименован)"
    assert route.route_signature == "production:SAWING:SAW:0:1:0>production:PACKING:PACK_STRETCH:0:0:1"


ROUTE_NAME = "ГП"


async def _make_product(session, sku: str) -> Product:
    product = Product(sku=sku, name="Артикул", type=ProductType.finished_good, unit="pcs")
    session.add(product)
    await session.commit()
    return product


async def _make_named_profile(session, code: str, sections=None) -> RouteRuleProfile:
    """Профиль, имя маршрута которого равно `output_kind` — иначе сверять не с чем."""
    profile = await _make_profile(session, code=code, sections=sections)
    profile.route_name_pattern = "{output_kind}"
    await session.commit()
    return profile


async def _import_one_row(session, profile, product, *, sku: str, payload: dict | None = None):
    """Импорт одной строки плана профилем — публичный шов импорта."""
    items, _diagnostics = await _make_change_items(
        session,
        change_set_id=1,
        parsed_rows=[ParsedRow(sku, "Артикул", Decimal("10"), payload or {"output_kind": "ГП"})],
        products_by_sku={sku.lower(): product},
        mode=None,
        existing_positions=[],
        rule_profile_id=profile.id,
        template_id=None,
    )
    return items


@pytest.mark.asyncio
async def test_import_rejects_row_when_named_route_has_other_signature(session) -> None:
    """Маршрут с тем же именем и другой сигнатурой — другой маршрут: строка
    импорта получает ошибку, а маршрут под неё не подставляется (#215).
    """
    await _seed_sections(session)
    profile = await _make_named_profile(session, "sig_conflict")
    product = await _make_product(session, "FG-CONFLICT")
    existing = await _make_route_with_signature(session, ROUTE_NAME, FOREIGN_SIGNATURE)

    items = await _import_one_row(session, profile, product, sku="FG-CONFLICT")

    item = items[0]
    assert item.errors == ["route_signature_conflict"]
    assert item.status == PlanChangeItemStatus.invalid
    assert item.after_data.get("route_id") is None
    # Чужой маршрут остался на месте — импорт не переименовал и не заменил его.
    await session.refresh(existing)
    assert existing.name == ROUTE_NAME


@pytest.mark.asyncio
async def test_import_preview_shows_signature_conflict(session) -> None:
    """Предпросмотр импорта показывает тот же конфликт: `change_set_id = 0` —
    записи маршрута в нём нет, иначе невалидность всплыла бы только при
    применении сета."""
    await _seed_sections(session)
    profile = await _make_named_profile(session, "sig_preview")
    product = await _make_product(session, "FG-PREVIEW")
    await _make_route_with_signature(session, ROUTE_NAME, FOREIGN_SIGNATURE)

    items, _diagnostics = await _make_change_items(
        session,
        change_set_id=0,
        parsed_rows=[ParsedRow("FG-PREVIEW", "Артикул", Decimal("10"), {"output_kind": "ГП"})],
        products_by_sku={"fg-preview": product},
        mode=None,
        existing_positions=[],
        rule_profile_id=profile.id,
        template_id=None,
    )

    assert items[0].errors == ["route_signature_conflict"]
    assert items[0].status == PlanChangeItemStatus.invalid
    assert items[0].after_data.get("route_id") is None
    # Собранные шаги остаются видны: оператор видит, что именно не совпало.
    assert [step["section_code"] for step in items[0].after_data["route_steps"]] == [
        "RAW_STOCK", "SAWING", "PACKING", "FINISHED_STOCK",
    ]


@pytest.mark.asyncio
async def test_import_reuses_named_route_with_matching_signature(session) -> None:
    """Регресс: сигнатуры совпадают — маршрут, найденный по имени,
    переиспользуется как раньше, без ошибки строки."""
    await _seed_sections(session)
    profile = await _make_named_profile(session, "sig_matched")
    product = await _make_product(session, "FG-MATCHED")
    existing = await _make_route_with_signature(session, ROUTE_NAME, MATCHED_SIGNATURE)

    items = await _import_one_row(session, profile, product, sku="FG-MATCHED")

    item = items[0]
    assert item.errors == []
    assert item.status != PlanChangeItemStatus.invalid
    assert item.after_data["route_id"] == existing.id


@pytest.mark.asyncio
async def test_two_rows_of_one_import_share_the_route(session) -> None:
    """Регресс: две строки с одинаковым маршрутом в одном импорте
    переиспользуют один маршрут, а не спорят за него."""
    await _seed_sections(session)
    profile = await _make_named_profile(session, "sig_pair")
    first = await _make_product(session, "FG-PAIR-1")
    second = await _make_product(session, "FG-PAIR-2")

    items, _diagnostics = await _make_change_items(
        session,
        change_set_id=1,
        parsed_rows=[
            ParsedRow("FG-PAIR-1", "Артикул", Decimal("10"), {"output_kind": "ГП"}),
            ParsedRow("FG-PAIR-2", "Артикул", Decimal("10"), {"output_kind": "ГП"}),
        ],
        products_by_sku={"fg-pair-1": first, "fg-pair-2": second},
        mode=None,
        existing_positions=[],
        rule_profile_id=profile.id,
        template_id=None,
    )

    assert [item.errors for item in items] == [[], []]
    route_ids = {item.after_data["route_id"] for item in items}
    assert len(route_ids) == 1 and None not in route_ids
    assert await session.scalar(
        select(func.count(ProductionRoute.id)).where(ProductionRoute.name == ROUTE_NAME)
    ) == 1


@pytest.mark.asyncio
async def test_route_build_error_stays_out_of_row_errors(session) -> None:
    """Регресс: ошибки сборки, не связанные с конфликтом, остаются в журнале
    и в ошибки строки не превращаются (глушение снимать нельзя — см. ADR-0045).
    """
    await _seed_sections(session)
    profile = await _make_named_profile(session, "sig_broken", sections=["NO_SUCH_SECTION"])
    product = await _make_product(session, "FG-BROKEN")
    await _make_route_with_signature(session, ROUTE_NAME, FOREIGN_SIGNATURE)

    items = await _import_one_row(session, profile, product, sku="FG-BROKEN")

    assert items[0].errors == []


@pytest.mark.asyncio
async def test_conflicting_row_becomes_invalid_position_in_plan(session) -> None:
    """Строка с конфликтом не исчезает из импорта: применение сета создаёт
    позицию со статусом «невалидна» и кодом в её ошибках — её видно в
    плане, и оператор видит, что чинить."""
    await _seed_sections(session)
    profile = await _make_named_profile(session, "sig_apply")
    product = await _make_product(session, "FG-APPLY")
    await _make_route_with_signature(session, ROUTE_NAME, FOREIGN_SIGNATURE)
    plan = ProductionPlan(plan_no="PLAN-215", name="План 215", status=ProductionPlanStatus.draft)
    session.add(plan)
    await session.commit()
    change_set = PlanChangeSet(production_plan_id=plan.id, summary={})
    session.add(change_set)
    await session.commit()

    items = await _import_one_row(session, profile, product, sku="FG-APPLY")
    items[0].change_set_id = change_set.id
    session.add(items[0])
    await session.commit()

    await apply_change_set(session, change_set.id)

    positions = (
        await session.execute(
            select(PlanPosition).where(PlanPosition.production_plan_id == plan.id)
        )
    ).scalars().all()
    assert len(positions) == 1
    assert positions[0].status == PlanPositionStatus.invalid
    assert "route_signature_conflict" in positions[0].validation_errors
    assert positions[0].route_id is None


# --- #230: идентичность маршрута импорта — код, а не имя -------------------


PACKING_GROUP = "PACK"
SECOND_PACKING_OP = "PACK_SPUNBOND"


async def _add_packing_variants(session) -> None:
    """Вторая операция упаковки в своей группе участка и правило выбора.

    Нужна, чтобы получить ДВА разных состава при ОДНОМ имени: имя
    профиля — ``{output_kind}``, то есть константа, а состав меняет
    операция упаковки, выбираемая правилом по значению строки. Ровно этот
    случай и порождал ``route_signature_conflict`` до #230.
    """
    packing = await session.scalar(select(Section).where(Section.code == "PACKING"))
    session.add(SectionOperation(
        section_id=packing.id,
        operation_code=SECOND_PACKING_OP,
        operation_name="Спанбонд",
        group_code=PACKING_GROUP,
        group_name="Упаковка",
        is_significant=False,
        sort_order=2,
    ))
    await session.flush()

    profile = await session.scalar(
        select(RouteRuleProfile).where(RouteRuleProfile.code == "sig_shared_name")
    )
    for index, (value, operation_code) in enumerate(
        (("спанбонд", SECOND_PACKING_OP), ("стрейч", "PACK_STRETCH"))
    ):
        session.add(RouteSelectionRule(
            code=f"shared_name_pack_{index}",
            name=f"Упаковка: {value}",
            profile_id=profile.id,
            priority=100,
            is_active=True,
            phase="resolve_operations",
            conditions=[
                {"source": "payload", "field_path": "pack", "operator": "equals", "value": value},
            ],
            actions=[
                {
                    "action": "set_operation",
                    "section_code": "PACKING",
                    "group_code": PACKING_GROUP,
                    "operation_code": operation_code,
                },
            ],
        ))
    await session.commit()


@pytest.mark.asyncio
async def test_compositions_with_same_name_get_separate_routes(session) -> None:
    """Два разных состава с ОДНИМ именем — два маршрута, а не конфликт.

    До #230 вторая строка приходила в импорт как
    ``route_signature_conflict``: имя то же, а сигнатуры разные, и БД
    запрещала вторую строку с тем же именем вовсе. Теперь идентичность —
    код, а имя — подпись, поэтому оба маршрута законны, имеют разные коды
    и обе строки валидны.
    """
    await _seed_sections(session)
    await _make_named_profile(session, "sig_shared_name")
    await _add_packing_variants(session)
    first = await _make_product(session, "FG-PACK-STRETCH")
    second = await _make_product(session, "FG-PACK-SPUNBOND")

    items, _diagnostics = await _make_change_items(
        session,
        change_set_id=1,
        parsed_rows=[
            ParsedRow("FG-PACK-STRETCH", "Артикул", Decimal("10"), {"output_kind": ROUTE_NAME, "pack": "стрейч"}),
            ParsedRow("FG-PACK-SPUNBOND", "Артикул", Decimal("10"), {"output_kind": ROUTE_NAME, "pack": "спанбонд"}),
        ],
        products_by_sku={"fg-pack-stretch": first, "fg-pack-spunbond": second},
        mode=None,
        existing_positions=[],
        rule_profile_id=(await session.scalar(
            select(RouteRuleProfile).where(RouteRuleProfile.code == "sig_shared_name")
        )).id,
        template_id=None,
    )

    assert [item.errors for item in items] == [[], []]
    route_ids = {item.after_data["route_id"] for item in items}
    assert len(route_ids) == 2, "разные составы обязаны получить разные маршруты"

    routes = (
        await session.execute(select(ProductionRoute).order_by(ProductionRoute.id))
    ).scalars().all()
    assert len(routes) == 2
    # Имя одно и то же — это законно; различает их код.
    assert {route.name for route in routes} == {ROUTE_NAME}
    assert {route.code for route in routes} == {
        auto_route_code(route.route_signature) for route in routes
    }
    assert all(route.code and route.code.startswith("auto-") for route in routes)


@pytest.mark.asyncio
async def test_same_composition_reuses_route_across_imports(session) -> None:
    """Повторный импорт того же состава переиспользует маршрут по коду.

    Ключ переиспользования — код, поэтому второй импорт (другой батч, но та
    же БД) находит маршрут первого и не плодит дубль. Проверяем и кэш
    внутри батча: обе строки одного импорта получают один route_id.
    """
    await _seed_sections(session)
    profile = await _make_named_profile(session, "sig_reuse_by_code")
    product = await _make_product(session, "FG-REUSE-CODE")

    first = await _import_one_row(session, profile, product, sku="FG-REUSE-CODE")
    second = await _import_one_row(session, profile, product, sku="FG-REUSE-CODE")

    assert first[0].errors == [] and second[0].errors == []
    assert first[0].after_data["route_id"] == second[0].after_data["route_id"]
    assert await session.scalar(
        select(func.count(ProductionRoute.id)).where(ProductionRoute.name == ROUTE_NAME)
    ) == 1


@pytest.mark.asyncio
async def test_legacy_route_without_code_is_reused_by_name(session) -> None:
    """Маршрут, созданный импортом ДО #230 (кода нет), импорт находит по имени.

    Переходное состояние существующих БД: у таких маршрутов кода ещё нет, и
    поиск только по коду сделал бы их недостижимыми. Импорт обязан найти их
    по имени — и, как и раньше, сверить сигнатуру, прежде чем подставить.
    """
    await _seed_sections(session)
    profile = await _make_named_profile(session, "sig_legacy_fallback")
    product = await _make_product(session, "FG-LEGACY")
    legacy = await _make_route_with_signature(session, ROUTE_NAME, MATCHED_SIGNATURE)
    assert legacy.code is None, "фикстура должна имитировать маршрут до #230"

    items = await _import_one_row(session, profile, product, sku="FG-LEGACY")

    assert items[0].errors == []
    assert items[0].after_data["route_id"] == legacy.id


@pytest.mark.asyncio
async def test_legacy_route_with_other_signature_still_conflicts(session) -> None:
    """Fallback по имени не отменяет защиту ADR-0045.

    Маршрут без кода, с тем же именем и ЧУЖОЙ сигнатурой, подставлять нельзя:
    строка получает ``route_signature_conflict`` и остаётся в плане
    невалидной. Иначе импорт молча навесил бы на позицию маршрут, к
    которому она отношения не имеет.
    """
    await _seed_sections(session)
    profile = await _make_named_profile(session, "sig_legacy_conflict")
    product = await _make_product(session, "FG-LEGACY-CONFLICT")
    legacy = await _make_route_with_signature(session, ROUTE_NAME, FOREIGN_SIGNATURE)

    items = await _import_one_row(session, profile, product, sku="FG-LEGACY-CONFLICT")

    assert items[0].errors == ["route_signature_conflict"]
    assert items[0].after_data.get("route_id") is None
    await session.refresh(legacy)
    assert legacy.name == ROUTE_NAME


@pytest.mark.asyncio
async def test_created_route_code_is_deterministic_for_signature() -> None:
    """Код — функция сигнатуры: тот же состав даёт тот же код всегда."""
    assert auto_route_code(MATCHED_SIGNATURE) == auto_route_code(MATCHED_SIGNATURE)
    assert auto_route_code(MATCHED_SIGNATURE) != auto_route_code(FOREIGN_SIGNATURE)
    # Маршрут без этапов сигнатуры не имеет — кода тоже.
    assert auto_route_code("") is None


@pytest.mark.asyncio
async def test_signature_conflict_verified_against_stages_when_not_saved(session) -> None:
    """Сверка сигнатуры работает и по этапам, когда сигнатура не сохранена.

    Ветка «сохранённой сигнатуры нет — считаем по этапам» передавала в
    ``encode_signature`` сами ``RouteStage`` вместо ``RouteSignatureStep`` и
    падала ``AttributeError: 'RouteStage' object has no attribute 'encode'``.
    Вызывающий ``route_matcher`` глотал это общим ``except Exception``, так
    что сверка не выполнялась вовсе, а позиция получала маршрут чужого
    состава с ``error=None``.
    """
    from app.services.route_signature import route_signature_conflicts

    await _seed_sections(session)
    route = await _make_route_with_signature(session, ROUTE_NAME, MATCHED_SIGNATURE)
    # Гасим сохранённую сигнатуру — сверка обязана посчитать её по этапам.
    route.route_signature = None
    await session.flush()

    assert await route_signature_conflicts(session, route, MATCHED_SIGNATURE) is False
    assert await route_signature_conflicts(session, route, FOREIGN_SIGNATURE) is True
    # Пустая ожидаемая сигнатура — сравнивать не с чем.
    assert await route_signature_conflicts(session, route, "") is False
