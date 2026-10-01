"""Pagination, total, search and sort for GET /api/production-plans/all-positions."""
from __future__ import annotations

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
    ProductionPlanStatus,
)
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_plan(session: AsyncSession, *, plan_no: str = "PLAN-PAGE") -> ProductionPlan:
    plan = ProductionPlan(
        plan_no=plan_no,
        name=f"Plan {plan_no}",
        status=ProductionPlanStatus.draft,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()
    return plan


async def _make_product(session: AsyncSession, sku: str, *, name: str | None = None) -> Product:
    product = Product(
        sku=sku,
        name=name or sku,
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
    )
    session.add(product)
    await session.flush()
    return product


async def _seed_planning_positions(
    session: AsyncSession,
    *,
    count: int,
    sku_prefix: str = "PLAN-SKU",
    name_prefix: str = "Plan item",
    status: PlanPositionStatus = PlanPositionStatus.draft,
    validation_status: PlanPositionValidationStatus = PlanPositionValidationStatus.valid,
    start_row: int = 1,
) -> tuple[ProductionPlan, list[PlanPosition]]:
    plan = await _make_plan(session, plan_no=f"PLAN-{sku_prefix}")
    positions: list[PlanPosition] = []
    for i in range(count):
        sku = f"{sku_prefix}-{i:03d}"
        product = await _make_product(session, sku, name=f"Product {sku}")
        pos = PlanPosition(
            production_plan_id=plan.id,
            product_id=product.id,
            source_type=PlanSourceType.manual,
            source_sku=sku,
            source_name=f"{name_prefix} {i:03d}",
            quantity=Decimal(str(10 + i)),
            source_payload={},
            status=status,
            validation_status=validation_status,
            validation_errors=[],
            source_row_number=start_row + i,
            period_start=plan.period_start,
            period_end=plan.period_end,
            has_pack_ops=False,
        )
        session.add(pos)
        positions.append(pos)
    await session.commit()
    return plan, positions


@pytest.mark.asyncio
async def test_all_positions_default_limit_returns_total(client, session: AsyncSession):
    await _seed_planning_positions(session, count=65, sku_prefix="PAGE-DEF")

    resp = await client.get("/api/production-plans/all-positions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["positions"]) == 50
    assert body["total"] == 65
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.asyncio
async def test_all_positions_offset_pagination(client, session: AsyncSession):
    await _seed_planning_positions(session, count=75, sku_prefix="PAGE-OFF")

    first = await client.get("/api/production-plans/all-positions?limit=50&offset=0")
    second = await client.get("/api/production-plans/all-positions?limit=50&offset=50")
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    first_ids = {pos["id"] for pos in first.json()["positions"]}
    second_ids = {pos["id"] for pos in second.json()["positions"]}
    assert len(first_ids) == 50
    assert len(second_ids) == 25
    assert first_ids.isdisjoint(second_ids)
    assert first.json()["total"] == 75
    assert second.json()["total"] == 75


@pytest.mark.asyncio
async def test_all_positions_search_finds_record_on_second_page(client, session: AsyncSession):
    await _seed_planning_positions(session, count=60, sku_prefix="PAGE-SRCH")
    plan = await _make_plan(session, plan_no="PLAN-MARKER")
    product = await _make_product(session, "UNIQUE-PLAN-MARKER-42", name="Marker product")
    marker = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku="UNIQUE-PLAN-MARKER-42",
        source_name="Special marker position",
        quantity=Decimal(1),
        source_payload={},
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        source_row_number=9999,
        period_start=plan.period_start,
        period_end=plan.period_end,
        has_pack_ops=False,
    )
    session.add(marker)
    await session.commit()

    resp = await client.get(
        "/api/production-plans/all-positions"
        "?search=UNIQUE-PLAN-MARKER-42&limit=50&offset=0"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["positions"]) == 1
    assert body["positions"][0]["source_sku"] == "UNIQUE-PLAN-MARKER-42"


@pytest.mark.asyncio
async def test_all_positions_sort_by_source_sku(client, session: AsyncSession):
    plan = await _make_plan(session, plan_no="PLAN-SORT")
    skus = ["PLAN-SORT-Z", "PLAN-SORT-A", "PLAN-SORT-M"]
    for idx, sku in enumerate(skus):
        product = await _make_product(session, sku)
        session.add(
            PlanPosition(
                production_plan_id=plan.id,
                product_id=product.id,
                source_type=PlanSourceType.manual,
                source_sku=sku,
                source_name=sku,
                quantity=Decimal(1),
                source_payload={},
                status=PlanPositionStatus.draft,
                validation_status=PlanPositionValidationStatus.valid,
                validation_errors=[],
                source_row_number=idx + 1,
                period_start=plan.period_start,
                period_end=plan.period_end,
                has_pack_ops=False,
            )
        )
    await session.commit()

    resp = await client.get(
        "/api/production-plans/all-positions?sort=source_sku:asc&limit=50"
    )
    assert resp.status_code == 200, resp.text
    returned_skus = [pos["source_sku"] for pos in resp.json()["positions"]]
    assert returned_skus == sorted(skus)


@pytest.mark.asyncio
async def test_all_positions_sort_by_source_name_id_and_errors(client, session: AsyncSession):
    """Колонки «Наименование», «Id» и «Ошибки» сортируются сервером по своим полям.

    Раньше эти поля не резолвились, и фронт молча слал sort_by=source_row_number —
    порядок строк не менялся.
    """
    plan = await _make_plan(session, plan_no="PLAN-SORT-NEW")
    rows = [
        # (sku, source_name, source_row_number, validation_errors)
        ("NEW-SORT-1", "Яблоко", 1, ["ошибка 1", "ошибка 2"]),
        ("NEW-SORT-2", "Абрикос", 2, []),
        ("NEW-SORT-3", "Вишня", 3, ["ошибка 1"]),
    ]
    for sku, name, row_number, errors in rows:
        product = await _make_product(session, sku, name=name)
        session.add(
            PlanPosition(
                production_plan_id=plan.id,
                product_id=product.id,
                source_type=PlanSourceType.manual,
                source_sku=sku,
                source_name=name,
                quantity=Decimal(1),
                source_payload={},
                status=PlanPositionStatus.draft,
                validation_status=PlanPositionValidationStatus.valid,
                validation_errors=errors,
                source_row_number=row_number,
                period_start=plan.period_start,
                period_end=plan.period_end,
                has_pack_ops=False,
            )
        )
    await session.commit()

    by_name = await client.get(
        "/api/production-plans/all-positions?sort=source_name:asc&limit=50"
    )
    assert by_name.status_code == 200, by_name.text
    names = [pos["source_name"] for pos in by_name.json()["positions"]]
    assert names == ["Абрикос", "Вишня", "Яблоко"]

    by_name_desc = await client.get(
        "/api/production-plans/all-positions?sort=source_name:desc&limit=50"
    )
    assert by_name_desc.status_code == 200, by_name_desc.text
    assert [pos["source_name"] for pos in by_name_desc.json()["positions"]] == [
        "Яблоко",
        "Вишня",
        "Абрикос",
    ]

    by_id = await client.get(
        "/api/production-plans/all-positions?sort=id:asc&limit=50"
    )
    assert by_id.status_code == 200, by_id.text
    ids = [pos["id"] for pos in by_id.json()["positions"]]
    assert ids == sorted(ids)

    # Сортировка по числу ошибок валидации: 0 → 1 → 2.
    by_errors = await client.get(
        "/api/production-plans/all-positions?sort=errors:asc&limit=50"
    )
    assert by_errors.status_code == 200, by_errors.text
    assert [len(pos["errors"]) for pos in by_errors.json()["positions"]] == [0, 1, 2]

    by_errors_desc = await client.get(
        "/api/production-plans/all-positions?sort=errors:desc&limit=50"
    )
    assert by_errors_desc.status_code == 200, by_errors_desc.text
    assert [len(pos["errors"]) for pos in by_errors_desc.json()["positions"]] == [2, 1, 0]


@pytest.mark.asyncio
async def test_all_positions_filter_validation_status(client, session: AsyncSession):
    await _seed_planning_positions(
        session,
        count=5,
        sku_prefix="PAGE-VAL-OK",
        validation_status=PlanPositionValidationStatus.valid,
    )
    await _seed_planning_positions(
        session,
        count=3,
        sku_prefix="PAGE-VAL-BAD",
        validation_status=PlanPositionValidationStatus.invalid,
    )

    resp = await client.get(
        "/api/production-plans/all-positions?validation_status=invalid&limit=50&offset=0"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert len(body["positions"]) == 3
    assert all(pos["validation_status"] == "invalid" for pos in body["positions"])


@pytest.mark.asyncio
async def test_all_positions_limit_max_validation(client, session: AsyncSession):
    resp = await client.get("/api/production-plans/all-positions?limit=1000")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_all_positions_excludes_non_planning_statuses(client, session: AsyncSession):
    plan = await _make_plan(session, plan_no="PLAN-STATUS")
    product = await _make_product(session, "PLAN-STATUS-ITEM")
    for pos_status in (
        PlanPositionStatus.draft,
        PlanPositionStatus.approved,
        PlanPositionStatus.released,
        PlanPositionStatus.cancelled,
    ):
        session.add(
            PlanPosition(
                production_plan_id=plan.id,
                product_id=product.id,
                source_type=PlanSourceType.manual,
                source_sku=f"SKU-{pos_status.value}",
                source_name=pos_status.value,
                quantity=Decimal(1),
                source_payload={},
                status=pos_status,
                validation_status=PlanPositionValidationStatus.valid,
                validation_errors=[],
                source_row_number=1,
                period_start=plan.period_start,
                period_end=plan.period_end,
                has_pack_ops=False,
            )
        )
    await session.commit()

    resp = await client.get("/api/production-plans/all-positions?limit=50")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["positions"][0]["status"] == "draft"


@pytest.mark.asyncio
async def test_all_positions_filter_sort_by_dimensions(client, session: AsyncSession):
    """Тикет #95: колонка «Размер» на странице плана — серверные фильтр и сортировка."""
    plan = await _make_plan(session, plan_no="PLAN-DIMS")
    for idx, (sku, length) in enumerate(
        [("DIMS-3000", 3000), ("DIMS-2700", 2700), ("DIMS-1000", 1000), ("DIMS-NONE", None)],
        start=1,
    ):
        product = await _make_product(session, sku)
        session.add(
            PlanPosition(
                production_plan_id=plan.id,
                product_id=product.id,
                source_type=PlanSourceType.manual,
                source_sku=sku,
                source_name=sku,
                quantity=Decimal(10),
                input_dimensions={"length_mm": length} if length is not None else None,
                source_payload={},
                status=PlanPositionStatus.draft,
                validation_status=PlanPositionValidationStatus.valid,
                validation_errors=[],
                source_row_number=idx,
                period_start=plan.period_start,
                period_end=plan.period_end,
                has_pack_ops=False,
            )
        )
    await session.commit()

    # Сериализация: позиции несут dimensions + dimensions_label.
    all_resp = await client.get("/api/production-plans/all-positions?limit=50")
    assert all_resp.status_code == 200, all_resp.text
    all_positions = all_resp.json()["positions"]
    by_sku = {p["source_sku"]: p for p in all_positions}
    assert by_sku["DIMS-3000"]["dimensions"] == {"length_mm": 3000}
    assert by_sku["DIMS-3000"]["dimensions_label"] == "3 м"
    assert by_sku["DIMS-NONE"]["dimensions"] is None
    assert by_sku["DIMS-NONE"]["dimensions_label"] == "—"

    # Фильтр точного совпадения: только 2700.
    from urllib.parse import quote

    filt = await client.get(
        f"/api/production-plans/all-positions?dimensions={quote('{"length_mm":2700}')}"
    )
    assert filt.status_code == 200, filt.text
    assert [p["source_sku"] for p in filt.json()["positions"]] == ["DIMS-2700"]

    # Фильтр безразмерных.
    none_filt = await client.get("/api/production-plans/all-positions?dimensions=null")
    assert none_filt.status_code == 200, none_filt.text
    assert [p["source_sku"] for p in none_filt.json()["positions"]] == ["DIMS-NONE"]

    # Сортировка по размеру убыв.: 3000 → 2700 → 1000 → безразмерные в конце.
    sort_resp = await client.get(
        "/api/production-plans/all-positions?sort=dimensions:desc"
    )
    skus = [p["source_sku"] for p in sort_resp.json()["positions"]]
    assert skus == ["DIMS-3000", "DIMS-2700", "DIMS-1000", "DIMS-NONE"]

    # Мусор в dimensions → 422.
    bad = await client.get("/api/production-plans/all-positions?dimensions=not-json")
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_all_positions_default_order_unchanged(client, session: AsyncSession):
    """Без параметра сортировки позиции идут по номеру строки импорта, как и раньше."""
    plan = await _make_plan(session, plan_no="PLAN-DEF-ORDER")
    for idx, row_number in enumerate((30, 10, 20)):
        product = await _make_product(session, f"DEF-ORDER-{idx}")
        session.add(
            PlanPosition(
                production_plan_id=plan.id,
                product_id=product.id,
                source_type=PlanSourceType.manual,
                source_sku=f"DEF-ORDER-{idx}",
                source_name=f"DEF-ORDER-{idx}",
                quantity=Decimal(1),
                source_payload={},
                status=PlanPositionStatus.draft,
                validation_status=PlanPositionValidationStatus.valid,
                validation_errors=[],
                source_row_number=row_number,
                period_start=plan.period_start,
                period_end=plan.period_end,
                has_pack_ops=False,
            )
        )
    await session.commit()

    default_resp = await client.get("/api/production-plans/all-positions?limit=50")
    assert default_resp.status_code == 200, default_resp.text
    default_rows = [p["source_row_number"] for p in default_resp.json()["positions"]]
    assert default_rows == [10, 20, 30]

    # Явный дефолт даёт тот же порядок, что и отсутствие параметра.
    explicit = await client.get(
        "/api/production-plans/all-positions?sort=source_row_number:asc&limit=50"
    )
    assert explicit.status_code == 200, explicit.text
    assert [p["source_row_number"] for p in explicit.json()["positions"]] == default_rows

    # Дефолт не «просто любой»: сортировка по не-дефолтному полю переставляет
    # строки. На HEAD, где параметра sort нет, остался бы исходный порядок —
    # этот assert ловит именно перевод на общий контракт.
    by_sku = await client.get(
        "/api/production-plans/all-positions?sort=source_sku:desc&limit=50"
    )
    assert by_sku.status_code == 200, by_sku.text
    # Артикулы заведены как DEF-ORDER-0/1/2 для строк 30/10/20, поэтому по
    # source_sku:desc получаем 2, 1, 0.
    assert [p["source_row_number"] for p in by_sku.json()["positions"]] == [20, 10, 30]


@pytest.mark.asyncio
async def test_all_positions_multi_sort_priorities(client, session: AsyncSession):
    """Два приоритета: сначала валидация, потом наименование.

    validation_status у всех позиций одинаковый, поэтому порядок по одному полю
    не алфавитный, а по двум — алфавитный. Иначе тест не отличает
    мультисортировку от одиночной сортировки по второму полю.
    """
    plan = await _make_plan(session, plan_no="PLAN-MULTI")
    for name, row_number in (("Яблоко", 1), ("Абрикос", 2), ("Вишня", 3)):
        product = await _make_product(session, f"MULTI-{row_number}")
        session.add(
            PlanPosition(
                production_plan_id=plan.id,
                product_id=product.id,
                source_type=PlanSourceType.manual,
                source_sku=f"MULTI-{row_number}",
                source_name=name,
                quantity=Decimal(1),
                source_payload={},
                status=PlanPositionStatus.draft,
                validation_status=PlanPositionValidationStatus.valid,
                validation_errors=[],
                source_row_number=row_number,
                period_start=plan.period_start,
                period_end=plan.period_end,
                has_pack_ops=False,
            )
        )
    await session.commit()

    # Один приоритет: validation_status у всех valid, порядок задаёт tiebreaker
    # по id, то есть порядок посева, а не алфавитный.
    by_status = await client.get(
        "/api/production-plans/all-positions?sort=validation_status:asc&limit=50"
    )
    assert by_status.status_code == 200, by_status.text
    seeded_names = [p["source_name"] for p in by_status.json()["positions"]]
    assert seeded_names == ["Яблоко", "Абрикос", "Вишня"], (
 "одиночная сортировка по статусу не должна совпасть с алфавитной"
    )

    # Второй приоритет переставляет строки внутри равных по статусу.
    by_both = await client.get(
        "/api/production-plans/all-positions"
        "?sort=validation_status:asc,source_name:asc&limit=50"
    )
    assert by_both.status_code == 200, by_both.text
    assert [p["source_name"] for p in by_both.json()["positions"]] == [
        "Абрикос",
        "Вишня",
        "Яблоко",
    ]


@pytest.mark.asyncio
async def test_all_positions_rejects_unknown_field_and_direction(client, session: AsyncSession):
    """Неизвестное поле или направление — 400, а не молчаливый фолбэк."""
    unknown_field = await client.get(
        "/api/production-plans/all-positions?sort=nope:asc"
    )
    assert unknown_field.status_code == 400, unknown_field.text

    bad_direction = await client.get(
        "/api/production-plans/all-positions?sort=status:sideways"
    )
    assert bad_direction.status_code == 400, bad_direction.text


@pytest.mark.asyncio
async def test_all_positions_finds_position_by_id_beyond_current_page(
    client, session: AsyncSession
):
    """Тикет #270: переход к позиции по дублю догружает цель по id.

    Цель может лежать вне текущей страницы (и под текущим фильтром её нет) —
    `plan_position_id` должен достать её независимо от пагинации.
    """
    _plan, positions = await _seed_planning_positions(session, count=60, sku_prefix="PAGE-JUMP")
    target = positions[-1]

    # Без фильтра цель на третьей странице и в дефолтную первую не попадает.
    default_page = await client.get("/api/production-plans/all-positions")
    assert default_page.status_code == 200, default_page.text
    assert all(p["id"] != target.id for p in default_page.json()["positions"])

    resp = await client.get(
        f"/api/production-plans/all-positions?plan_position_id={target.id}"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert [p["id"] for p in body["positions"]] == [target.id]
    assert body["positions"][0]["source_sku"] == target.source_sku


@pytest.mark.asyncio
async def test_all_positions_unknown_plan_position_id_returns_empty(
    client, session: AsyncSession
):
    """Неизвестный id — пустой ответ, а не молчаливая первая страница."""
    _plan, positions = await _seed_planning_positions(session, count=3, sku_prefix="PAGE-MISS")
    missing = max(p.id for p in positions) + 10_000

    resp = await client.get(
        f"/api/production-plans/all-positions?plan_position_id={missing}"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 0
    assert body["positions"] == []


@pytest.mark.asyncio
async def test_all_positions_plan_position_id_combines_with_other_filters(
    client, session: AsyncSession
):
    """id-фильтр аддитивен: он сужает выборку, а не подменяет остальные фильтры."""
    _plan, positions = await _seed_planning_positions(session, count=5, sku_prefix="PAGE-COMB")
    target, other = positions[2], positions[0]

    matched = await client.get(
        "/api/production-plans/all-positions"
        f"?plan_position_id={target.id}&search={target.source_sku}"
    )
    assert matched.status_code == 200, matched.text
    assert [p["id"] for p in matched.json()["positions"]] == [target.id]

    # Тот же id, но чужой поиск: условия комбинируются по «И» — пусто.
    mismatched = await client.get(
        "/api/production-plans/all-positions"
        f"?plan_position_id={target.id}&search={other.source_sku}"
    )
    assert mismatched.status_code == 200, mismatched.text
    assert mismatched.json()["positions"] == []


@pytest.mark.asyncio
async def test_all_positions_id_filter_respects_planning_stage_gate(
    client, session: AsyncSession
):
    """id не пробивает гейт «только планируемые статусы»: чужая страница — не повод показать позицию вне планирования."""
    _plan, positions = await _seed_planning_positions(
        session,
        count=1,
        sku_prefix="PAGE-GATE",
        status=PlanPositionStatus.approved,
    )

    resp = await client.get(
        f"/api/production-plans/all-positions?plan_position_id={positions[0].id}"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["positions"] == []