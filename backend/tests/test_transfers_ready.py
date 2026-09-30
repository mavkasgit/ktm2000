"""Tests for GET /api/transfers/ready pagination (offset, limit, total, search)."""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import quote

import pytest
from sqlalchemy import select

from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
)
from app.models.section import Section
from app.models.work_task import WorkTask
from app.stock import Reason, StockCommand, StockCommandService
from app.services.material_operations import completed_operations_for_task
from tests.helpers.transfers import _make_dim_route_fixture, _make_two_ghp_setup, _seed_balance
from tests.test_integrity_invariants import _make_user, _release_via_take_to_work


async def _complete_source_tasks(session, setup: dict) -> list[int]:
    """Complete all source-section tasks (must be released beforehand)."""
    sec1 = setup["sections"][0]

    stock = (
        await session.execute(select(Section).where(Section.code == "RDY-STK"))
    ).scalar_one_or_none()
    if stock is None:
        stock = Section(code="RDY-STK", name="Stock", type="raw_stock", is_active=True, sort_order=0)
        session.add(stock)
        await session.flush()

    tasks = (
        await session.execute(
            select(WorkTask)
            .where(WorkTask.section_id == sec1.id)
            .order_by(WorkTask.id)
        )
    ).scalars().all()

    svc = StockCommandService()
    for task in tasks:
        # Признак берём у того же источника, что и плановая проводка задания
        # (ADR-0043 §2): иначе приход лёг бы в NULL-группу, а последующее
        # списание искало бы группу маршрута и получало «available 0» (ADR-0055).
        ops = await completed_operations_for_task(session, task)
        await svc.record(
            session,
            StockCommand(
                product_id=task.product_id,
                from_location_id=None,
                to_location_id=stock.id,
                quantity=task.planned_quantity,
                reason=Reason.MANUAL_IN,
                completed_operations=ops,
                created_by=setup["user"].id,
            ),
        )
        await svc.record(
            session,
            StockCommand(
                product_id=task.product_id,
                from_location_id=stock.id,
                to_location_id=task.section_id,
                quantity=task.planned_quantity,
                reason=Reason.TRANSFER_RECEIVE,
                task_id=task.id,
                created_by=setup["user"].id,
            ),
        )
        await svc.record(
            session,
            StockCommand(
                product_id=task.product_id,
                from_location_id=task.section_id,
                to_location_id=task.section_id,
                quantity=task.planned_quantity,
                reason=Reason.COMPLETE,
                task_id=task.id,
                source_ref="test_seed",
                created_by=setup["user"].id,
            ),
        )
    await session.commit()
    return [task.id for task in tasks]


async def _seed_many_ready_tasks(session, client, count: int) -> dict:
    """Create *count* plan positions and complete their source tasks."""
    setup = await _make_two_ghp_setup(session, sku="RDY-PG", qty=Decimal("1"))
    plan = setup["plan"]
    route = setup["route"]

    for i in range(1, count):
        sku = f"RDY-PG-{i:03d}"
        product = Product(
            sku=sku,
            name=sku,
            type=ProductType.finished_good,
            unit="pcs",
            is_active=True,
        )
        session.add(product)
        await session.flush()
        await session.flush()
        session.add(
            PlanPosition(
                production_plan_id=plan.id,
                product_id=product.id,
                source_type=PlanSourceType.manual,
                source_sku=product.sku,
                source_name=product.name,
                quantity=Decimal("1"),
                source_payload={},
                status=PlanPositionStatus.approved,
                validation_status=PlanPositionValidationStatus.valid,
                validation_errors=[],
                period_start=plan.period_start,
                period_end=plan.period_end,
                has_pack_ops=False,
                route_id=route.id,
                route_assigned_at=None,
            )
        )
    await session.commit()

    positions = (
        await session.execute(
            select(PlanPosition)
            .where(PlanPosition.production_plan_id == plan.id)
            .order_by(PlanPosition.id)
        )
    ).scalars().all()

    for position in positions:
        await _release_via_take_to_work(client, position.id)

    task_ids = await _complete_source_tasks(session, setup)
    return {"setup": setup, "task_ids": task_ids}


@pytest.mark.asyncio
async def test_ready_empty_total_zero(client, session) -> None:
    response = await client.get("/api/transfers/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.asyncio
async def test_ready_offset_limit_pagination(client, session) -> None:
    seeded = await _seed_many_ready_tasks(session, client, count=3)
    sec1 = seeded["setup"]["sections"][0]

    first_page = await client.get(f"/api/transfers/ready?section_id={sec1.id}&limit=2&offset=0")
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert len(first_body["items"]) == 2
    assert first_body["total"] == 3
    assert first_body["limit"] == 2
    assert first_body["offset"] == 0

    second_page = await client.get(f"/api/transfers/ready?section_id={sec1.id}&limit=2&offset=2")
    assert second_page.status_code == 200
    second_body = second_page.json()
    assert len(second_body["items"]) == 1
    assert second_body["total"] == 3
    assert second_body["limit"] == 2
    assert second_body["offset"] == 2

    first_ids = {item["task_id"] for item in first_body["items"]}
    second_ids = {item["task_id"] for item in second_body["items"]}
    assert first_ids.isdisjoint(second_ids)


@pytest.mark.asyncio
async def test_ready_limit_max_validation(client, session) -> None:
    response = await client.get("/api/transfers/ready?limit=1000")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ready_search_by_sku(client, session) -> None:
    seeded = await _seed_many_ready_tasks(session, client, count=3)
    sec1 = seeded["setup"]["sections"][0]
    marker_sku = "RDY-PG-002"

    all_response = await client.get(f"/api/transfers/ready?section_id={sec1.id}")
    assert all_response.status_code == 200
    assert all_response.json()["total"] == 3

    search_response = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&search={marker_sku}"
    )
    assert search_response.status_code == 200
    search_body = search_response.json()
    assert search_body["total"] == 1
    assert len(search_body["items"]) == 1
    assert search_body["items"][0]["product_sku"] == marker_sku


@pytest.mark.asyncio
async def test_ready_search_finds_not_on_first_page(client, session) -> None:
    """Search must find a SKU that would not appear on page 1 with limit=2."""
    seeded = await _seed_many_ready_tasks(session, client, count=3)
    sec1 = seeded["setup"]["sections"][0]
    marker_sku = "RDY-PG-002"

    first_page = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&limit=2&offset=0"
    )
    assert first_page.status_code == 200
    first_skus = {item["product_sku"] for item in first_page.json()["items"]}
    assert marker_sku not in first_skus

    search_response = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&search={marker_sku}&limit=2&offset=0"
    )
    assert search_response.status_code == 200
    search_body = search_response.json()
    assert search_body["total"] == 1
    assert len(search_body["items"]) == 1
    assert search_body["items"][0]["product_sku"] == marker_sku


@pytest.mark.asyncio
async def test_ready_search_by_task_id(client, session) -> None:
    seeded = await _seed_many_ready_tasks(session, client, count=3)
    sec1 = seeded["setup"]["sections"][0]
    # Use the last task id to avoid accidental SKU substring matches (e.g. "1" in RDY-PG-001).
    task_id = seeded["task_ids"][-1]

    search_response = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&search={task_id}"
    )
    assert search_response.status_code == 200
    search_body = search_response.json()
    assert search_body["total"] == 1
    assert search_body["items"][0]["task_id"] == task_id


@pytest.mark.asyncio
async def test_ready_filter_plan_position_id_param(client, session) -> None:
    seeded = await _seed_many_ready_tasks(session, client, count=3)
    sec1 = seeded["setup"]["sections"][0]

    all_response = await client.get(f"/api/transfers/ready?section_id={sec1.id}")
    assert all_response.status_code == 200
    items = all_response.json()["items"]
    assert len(items) == 3
    marker_position_id = items[1]["plan_position_id"]

    filter_response = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&plan_position_id={marker_position_id}"
    )
    assert filter_response.status_code == 200
    filter_body = filter_response.json()
    assert filter_body["total"] == 1
    assert filter_body["items"][0]["plan_position_id"] == marker_position_id


@pytest.mark.asyncio
async def test_ready_filter_product_sku_param(client, session) -> None:
    seeded = await _seed_many_ready_tasks(session, client, count=3)
    sec1 = seeded["setup"]["sections"][0]
    marker_sku = "RDY-PG-002"

    all_response = await client.get(f"/api/transfers/ready?section_id={sec1.id}")
    assert all_response.status_code == 200
    assert all_response.json()["total"] == 3

    filter_response = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&product_sku={marker_sku}"
    )
    assert filter_response.status_code == 200
    filter_body = filter_response.json()
    assert filter_body["total"] == 1
    assert len(filter_body["items"]) == 1
    assert filter_body["items"][0]["product_sku"] == marker_sku


@pytest.mark.asyncio
async def test_ready_sort_by_task_id(client, session) -> None:
    seeded = await _seed_many_ready_tasks(session, client, count=3)
    sec1 = seeded["setup"]["sections"][0]
    task_ids = sorted(seeded["task_ids"])

    asc_response = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&sort=task_id:asc&limit=50"
    )
    assert asc_response.status_code == 200
    asc_body = asc_response.json()
    assert asc_body["total"] == 3
    asc_ids = [item["task_id"] for item in asc_body["items"]]
    assert asc_ids == task_ids

    desc_response = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&sort=task_id:desc&limit=50"
    )
    assert desc_response.status_code == 200
    desc_body = desc_response.json()
    desc_ids = [item["task_id"] for item in desc_body["items"]]
    assert desc_ids == list(reversed(task_ids))


async def _seed_dimensioned_ready_tasks(session, client, dims_list: list[dict | None]) -> dict:
    """Create one plan position per entry (None = dimensionless) on a shared route.

    Releases every position and completes source-section tasks, so each
    position produces a ready-to-transfer row on the first section.
    """
    setup = await _make_two_ghp_setup(session, sku="RDY-DIM", qty=Decimal("1"))
    plan = setup["plan"]
    route = setup["route"]
    setup["position"].input_dimensions = dims_list[0]

    for i in range(1, len(dims_list)):
        sku = f"RDY-DIM-{i:03d}"
        product = Product(
            sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True
        )
        session.add(product)
        await session.flush()
        await session.flush()
        session.add(
            PlanPosition(
                production_plan_id=plan.id,
                product_id=product.id,
                source_type=PlanSourceType.manual,
                source_sku=product.sku,
                source_name=product.name,
                quantity=Decimal("1"),
                input_dimensions=dims_list[i],
                source_payload={},
                status=PlanPositionStatus.approved,
                validation_status=PlanPositionValidationStatus.valid,
                validation_errors=[],
                period_start=plan.period_start,
                period_end=plan.period_end,
                has_pack_ops=False,
                route_id=route.id,
                route_assigned_at=None,
            )
        )
    await session.commit()

    positions = (
        await session.execute(
            select(PlanPosition)
            .where(PlanPosition.production_plan_id == plan.id)
            .order_by(PlanPosition.id)
        )
    ).scalars().all()
    for position in positions:
        await _release_via_take_to_work(client, position.id)

    await _complete_source_tasks(session, setup)
    return setup


@pytest.mark.asyncio
async def test_ready_sort_by_dimensions_desc(client, session) -> None:
    """sort_by=dimensions (SQL-path): 3 м → 1 м → безразмерные в конце."""
    setup = await _seed_dimensioned_ready_tasks(
        session, client, dims_list=[
            {"length_mm": 1000},
            {"length_mm": 3000},
            None,
        ]
    )
    sec1 = setup["sections"][0]

    resp = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&sort=dimensions:desc&limit=50"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert [item["dimensions"] for item in body["items"]] == [
        {"length_mm": 3000},
        {"length_mm": 1000},
        None,
    ]


@pytest.mark.asyncio
async def test_ready_sort_by_dimensions_combined_path(client, session) -> None:
    """sort_by=dimensions без section_id — комбинированный Python-sort (has_stock)."""
    await _seed_dimensioned_ready_tasks(
        session, client, dims_list=[
            {"length_mm": 1000},
            {"length_mm": 3000},
            None,
        ]
    )

    resp = await client.get(
        "/api/transfers/ready?sort=dimensions:desc&limit=50"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert [item["dimensions"] for item in body["items"]] == [
        {"length_mm": 3000},
        {"length_mm": 1000},
        None,
    ]


@pytest.mark.asyncio
async def test_ready_filter_by_dimensions_exact(client, session) -> None:
    """Фильтр dimensions='{"length_mm":1000}' — точное совпадение."""
    setup = await _seed_dimensioned_ready_tasks(
        session, client, dims_list=[
            {"length_mm": 1000},
            {"length_mm": 3000},
            None,
        ]
    )
    sec1 = setup["sections"][0]

    resp = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&dimensions={quote('{"length_mm":1000}')}"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["dimensions"] == {"length_mm": 1000}


@pytest.mark.asyncio
async def test_ready_filter_dimensionless(client, session) -> None:
    """Фильтр dimensions=null — только безразмерные строки."""
    setup = await _seed_dimensioned_ready_tasks(
        session, client, dims_list=[
            {"length_mm": 1000},
            {"length_mm": 3000},
            None,
        ]
    )
    sec1 = setup["sections"][0]

    resp = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&dimensions=null"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["dimensions"] is None


async def _complete_section_tasks(session, section_id: int, *, user_id: int, stock_code: str) -> None:
    """Выдать материал и закрыть все задания секции — её строки становятся ready."""
    stock = Section(
        code=stock_code, name="Stock", type="raw_stock", is_active=True, sort_order=0,
    )
    session.add(stock)
    await session.flush()

    tasks = (
        await session.execute(
            select(WorkTask)
            .where(WorkTask.section_id == section_id)
            .order_by(WorkTask.id)
        )
    ).scalars().all()
    svc = StockCommandService()
    for task in tasks:
        # Тот же источник признака, что у плановой проводки задания (ADR-0043 §2) —
        # см. комментарий в _complete_source_tasks.
        ops = await completed_operations_for_task(session, task)
        await svc.record(
            session,
            StockCommand(
                product_id=task.product_id,
                from_location_id=None,
                to_location_id=stock.id,
                quantity=task.planned_quantity,
                reason=Reason.MANUAL_IN,
                completed_operations=ops,
                created_by=user_id,
            ),
        )
        await svc.record(
            session,
            StockCommand(
                product_id=task.product_id,
                from_location_id=stock.id,
                to_location_id=task.section_id,
                quantity=task.planned_quantity,
                reason=Reason.TRANSFER_RECEIVE,
                task_id=task.id,
                created_by=user_id,
            ),
        )
        await svc.record(
            session,
            StockCommand(
                product_id=task.product_id,
                from_location_id=task.section_id,
                to_location_id=task.section_id,
                quantity=task.planned_quantity,
                reason=Reason.COMPLETE,
                task_id=task.id,
                source_ref="test_seed",
                created_by=user_id,
            ),
        )
    await session.commit()


async def _seed_raw_to_prod_route(
    session,
    client,
    *,
    sku_prefix: str,
    skus: list[str],
    qty: Decimal,
) -> dict:
    """Маршрут raw_stock → prod1 → prod2, по одной позиции плана на каждый SKU.

    Позиции освобождаются, поэтому у prod1 и raw есть задания/план-строки —
    обе ветки ready (производственная и складская) получают строки.
    """
    fx = await _make_dim_route_fixture(session, sku=sku_prefix, qty=qty)
    plan = fx["plan"]
    route_id = fx["position"].route_id

    for sku in skus[1:]:
        product = Product(
            sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True,
        )
        session.add(product)
        await session.flush()
        session.add(
            PlanPosition(
                production_plan_id=plan.id,
                product_id=product.id,
                source_type=PlanSourceType.manual,
                source_sku=product.sku,
                source_name=product.name,
                quantity=qty,
                source_payload={},
                status=PlanPositionStatus.approved,
                validation_status=PlanPositionValidationStatus.valid,
                validation_errors=[],
                period_start=plan.period_start,
                period_end=plan.period_end,
                has_pack_ops=False,
                route_id=route_id,
                route_assigned_at=None,
            )
        )
    await session.commit()

    positions = (
        await session.execute(
            select(PlanPosition)
            .where(PlanPosition.production_plan_id == plan.id)
            .order_by(PlanPosition.id)
        )
    ).scalars().all()
    for position in positions:
        await _release_via_take_to_work(client, position.id)
    return fx


@pytest.mark.asyncio
async def test_ready_two_sort_paths_agree(client, session) -> None:
    """Одна сортировка из двух колонок: порядок секции одинаков в обеих ветках.

    Запрос с ``section_id`` идёт по производственной ветке, запрос без него
    дополнительно тянет складские строки; общий Python-проход сортировки
    обязан выдать для строк этой секции ТОТ ЖЕ порядок.
    """
    user = await _make_user(session, "rdy-2path@local")
    # Первый SKU — продукт самой фикстуры (_make_dim_route_fixture), остальные
    # заводятся сверху в том же плане.
    skus = ["RDY-2P", "RDY-2P-A", "RDY-2P-B"]
    fx = await _seed_raw_to_prod_route(
        session, client, sku_prefix="RDY-2P", skus=skus, qty=Decimal("5"),
    )
    raw_sec, prod1_sec = fx["sections"][0], fx["sections"][1]

    # Остаток на складе → складская ветка тоже даёт строки.
    for sku in skus:
        product = (
            await session.execute(select(Product).where(Product.sku == sku))
        ).scalar_one()
        await _seed_balance(
            session,
            user_id=user.id,
            location_id=raw_sec.id,
            product_id=product.id,
            qty=Decimal("5"),
        )
    # Задания prod1 закрыты → производственная ветка даёт строки.
    await _complete_section_tasks(
        session, prod1_sec.id, user_id=user.id, stock_code="RDY-2P-TMP",
    )

    # Порядок берут sequence и product_sku — они одинаковы в обеих ветках.
    # transferable_qty берём НЕ здесь: он считается от разных контекстов
    # (складской остаток в комбинированном запросе участвует, в отфильтрованном
    # по section_id — нет), и на одних и тех же заданиях значения расходятся.
    # Проверять равенство веток на таком поле — значит сравнивать разные данные.
    sort = "sequence:asc,product_sku:desc"
    scoped = await client.get(
        f"/api/transfers/ready?section_id={prod1_sec.id}&sort={sort}&limit=50",
    )
    combined = await client.get(f"/api/transfers/ready?sort={sort}&limit=50")
    assert scoped.status_code == 200, scoped.text
    assert combined.status_code == 200, combined.text

    scoped_body = scoped.json()
    combined_body = combined.json()
    assert scoped_body["total"] == 3
    # В комбинированном ответе обе ветки: складские строки raw + производственные.
    assert combined_body["total"] == 6
    assert {item["section_id"] for item in combined_body["items"]} == {
        raw_sec.id,
        prod1_sec.id,
    }

    scoped_ids = [item["task_id"] for item in scoped_body["items"]]
    combined_ids = [
        item["task_id"] for item in combined_body["items"]
        if item["section_id"] == prod1_sec.id
    ]
    scoped_skus = [item["product_sku"] for item in scoped_body["items"]]
    assert scoped_skus == ["RDY-2P-B", "RDY-2P-A", "RDY-2P"]
    # Порядок выбран второй колонкой, а не tiebreaker'ом: убывание по SKU
    # совпадает с убыванием task_id (SKU заводились по возрастанию).
    assert scoped_ids == sorted(scoped_ids, reverse=True)
    assert combined_ids == scoped_ids


@pytest.mark.asyncio
async def test_ready_multi_sort_sequence_then_product_sku(client, session) -> None:
    """Вторая колонка ?sort= перебивает равные значения первой (все строки одного этапа)."""
    seeded = await _seed_many_ready_tasks(session, client, count=3)
    sec1 = seeded["setup"]["sections"][0]

    single = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&sort=sequence:asc&limit=50",
    )
    multi = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&sort=sequence:asc,product_sku:desc&limit=50",
    )
    assert single.status_code == 200, single.text
    assert multi.status_code == 200, multi.text

    single_items = single.json()["items"]
    multi_items = multi.json()["items"]
    assert len(single_items) == 3
    assert {item["sequence"] for item in single_items} == {1}

    single_skus = [item["product_sku"] for item in single_items]
    multi_skus = [item["product_sku"] for item in multi_items]
    assert single_skus == ["RDY-PG", "RDY-PG-001", "RDY-PG-002"]
    assert multi_skus == list(reversed(single_skus))
    assert single_skus != multi_skus


def test_ready_sort_tables_agree() -> None:
    """Обе таблицы резолва полей ready обязаны описывать один и тот же набор.

    Расхождение = одни и те же задания приходят в разном порядке в зависимости
    от ветки (производственная SQL-таблица против общего Python-прохода).
    """
    from sqlalchemy.orm import aliased

    from app.models.internal_plan import SectionPlanLine
    from app.models.route import RouteStage
    from app.transfers import queries as ready_queries

    assert set(ready_queries._READY_SORT_KEYS) == set(ready_queries.READY_SORT_FIELDS)

    production_columns = ready_queries._ready_production_sort_columns(
        transferable_expr=WorkTask.planned_quantity,
        from_line=aliased(SectionPlanLine, name="from_line"),
        from_stage=aliased(RouteStage, name="from_stage"),
        next_section=aliased(Section, name="next_section"),
    )
    assert set(production_columns) == set(ready_queries.READY_SORT_FIELDS)


@pytest.mark.asyncio
async def test_ready_default_order_is_sequence_asc(client, session) -> None:
    """Без параметра сортировки порядок прежний: этап (sequence) по возрастанию.

    ``sequence`` — это номер строки маршрута, то есть у всех заданий одного
    участка он одинаков. Порядок по нему виден только между участками, поэтому
    фикстура даёт две группы строк: складскую (заводятся остатками) и
    производственную (задания участка закрыты). Проверять дефолт на одном
    участке бессмысленно — там сортировка ничего не различает.
    """
    user = await _make_user(session, "rdy-seq@local")
    skus = ["RDY-SEQ-0", "RDY-SEQ-1", "RDY-SEQ-2"]
    fx = await _seed_raw_to_prod_route(
        session, client, sku_prefix="RDY-SEQ-0", skus=skus, qty=Decimal("5"),
    )
    raw_sec, prod1_sec = fx["sections"][0], fx["sections"][1]

    for sku in skus:
        product = (
            await session.execute(select(Product).where(Product.sku == sku))
        ).scalar_one()
        await _seed_balance(
            session,
            user_id=user.id,
            location_id=raw_sec.id,
            product_id=product.id,
            qty=Decimal("5"),
        )
    await _complete_section_tasks(
        session, prod1_sec.id, user_id=user.id, stock_code="RDY-SEQ-STK-A",
    )

    resp = await client.get("/api/transfers/ready?limit=50")
    assert resp.status_code == 200, resp.text
    rows = [(item["section_id"], item["sequence"]) for item in resp.json()["items"]]

    assert {section_id for section_id, _ in rows} == {raw_sec.id, prod1_sec.id}, rows
    # Порядок без параметра — по возрастанию sequence, то есть склад раньше участка.
    assert [sequence for _, sequence in rows] == sorted(
        sequence for _, sequence in rows
    )
    assert rows[0][0] == raw_sec.id

    desc = await client.get("/api/transfers/ready?sort=sequence:desc&limit=50")
    assert desc.status_code == 200, desc.text
    desc_rows = [(item["section_id"], item["sequence"]) for item in desc.json()["items"]]
    assert [sequence for _, sequence in desc_rows] == sorted(
        (sequence for _, sequence in desc_rows), reverse=True
    )
    assert set(desc_rows) == set(rows)


@pytest.mark.asyncio
async def test_ready_rejects_unknown_sort_field(client, session) -> None:
    """Неизвестное поле сортировки — 400, а не молчаливый откат на дефолт."""
    await _seed_many_ready_tasks(session, client, count=1)

    resp = await client.get("/api/transfers/ready?sort=unknown:asc")
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_ready_rejects_unknown_direction(client, session) -> None:
    """Направление вне asc/desc — 400."""
    await _seed_many_ready_tasks(session, client, count=1)

    resp = await client.get("/api/transfers/ready?sort=sequence:sideways")
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_ready_ignores_legacy_sort_by_params(client, session) -> None:
    """Сепарактные sort_by/sort_order больше не объявлены и не сортируют."""
    seeded = await _seed_many_ready_tasks(session, client, count=3)
    sec1 = seeded["setup"]["sections"][0]

    legacy = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&sort_by=task_id&sort_order=desc&limit=50",
    )
    assert legacy.status_code == 200, legacy.text
    legacy_ids = [item["task_id"] for item in legacy.json()["items"]]
    assert legacy_ids == sorted(legacy_ids)

    # «По task_id убыванию» — обратный порядок: значит подставленные legacy-поля
    # проявились бы, если бы сервер их читал.
    by_task_desc = await client.get(
        f"/api/transfers/ready?section_id={sec1.id}&sort=task_id:desc&limit=50",
    )
    assert by_task_desc.status_code == 200, by_task_desc.text
    assert [item["task_id"] for item in by_task_desc.json()["items"]] == list(
        reversed(legacy_ids),
    )