"""Pagination, total, search and sort for GET /api/shopfloor/sections/{id}/board."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from urllib.parse import quote

import pytest
from app.core.security import create_access_token
from app.models.internal_plan import InternalPlan, InternalPlanStatus, SectionPlanLine
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
)
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section
from app.models.user import User, UserRole
from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.shopfloor.queries_sections import get_section_board
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_user(session: AsyncSession) -> User:
    user = User(
        username="board-page-tester",
        email="board-page-tester@local",
        full_name="Board Page Tester",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _setup_two_stage_route(session: AsyncSession) -> tuple[Section, Section, ProductionRoute, RouteStage, RouteStage]:
    raw_section = Section(code="BOARD-RAW", name="Board Raw", is_active=True)
    target_section = Section(code="BOARD-TGT", name="Board Target", is_active=True)
    session.add_all([raw_section, target_section])
    await session.flush()

    route = ProductionRoute(name="Board Pagination Route", is_active=True)
    session.add(route)
    await session.flush()

    raw_stage = RouteStage(route_id=route.id, sequence=1, section_id=raw_section.id, is_final=False)
    target_stage = RouteStage(route_id=route.id, sequence=2, section_id=target_section.id, is_final=True)
    session.add_all([raw_stage, target_stage])
    await session.flush()

    session.add_all([
        RouteOperation(
            route_stage_id=raw_stage.id,
            sequence=1,
            operation_code="ISSUE_RAW",
            operation_name="Выдача сырья",
        ),
        RouteOperation(
            route_stage_id=target_stage.id,
            sequence=1,
            operation_code="PRESS",
            operation_name="Прессование",
        ),
    ])
    await session.flush()
    return raw_section, target_section, route, raw_stage, target_stage


async def _seed_board_tasks(
    session: AsyncSession,
    *,
    target_section: Section,
    route: ProductionRoute,
    raw_stage: RouteStage,
    target_stage: RouteStage,
    count: int,
    sku_prefix: str = "BOARD-SKU",
    operation_name: str = "Прессование",
    plan_no: str | None = None,
    dimensions: dict | None = None,
    due_date: date | None = None,
    set_due_date: bool = False,
) -> None:
    plan = ProductionPlan(
        plan_no=plan_no or f"BOARD-PAGINATION-{uuid.uuid4().hex[:8]}",
        name="Board Pagination Plan",
    )
    session.add(plan)
    await session.flush()

    internal_plan = InternalPlan(production_plan_id=plan.id, status=InternalPlanStatus.active)
    session.add(internal_plan)
    await session.flush()

    for i in range(count):
        sku = f"{sku_prefix}-{i:04d}"
        product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs")
        session.add(product)
        await session.flush()

        position = PlanPosition(
            production_plan_id=plan.id,
            product_id=product.id,
            source_type=PlanSourceType.excel_import,
            source_sku=sku,
            output_sku=sku,
            quantity=Decimal(10),
            status=PlanPositionStatus.released,
            validation_status=PlanPositionValidationStatus.valid,
            route_id=route.id,
            source_payload={"operation_name": operation_name},
        )
        session.add(position)
        await session.flush()

        raw_line = SectionPlanLine(
            internal_plan_id=internal_plan.id,
            plan_position_id=position.id,
            route_id=route.id,
            route_stage_id=raw_stage.id,
            section_id=raw_stage.section_id,
            product_id=product.id,
            sequence=1,
            planned_quantity=Decimal(10),
        )
        target_line = SectionPlanLine(
            internal_plan_id=internal_plan.id,
            plan_position_id=position.id,
            route_id=route.id,
            route_stage_id=target_stage.id,
            section_id=target_stage.section_id,
            product_id=product.id,
            sequence=2,
            planned_quantity=Decimal(10),
            due_date=due_date if set_due_date else date(2026, 1, 1 + (i % 28)),
        )
        session.add_all([raw_line, target_line])
        await session.flush()

        session.add_all([
            WorkTask(
                section_plan_line_id=raw_line.id,
                section_id=raw_line.section_id,
                product_id=product.id,
                route_stage_id=raw_line.route_stage_id,
                planned_quantity=Decimal(10),
                status=WorkTaskStatus.completed,
            ),
            WorkTask(
                section_plan_line_id=target_line.id,
                section_id=target_line.section_id,
                product_id=product.id,
                route_stage_id=target_line.route_stage_id,
                planned_quantity=Decimal(10),
                status=WorkTaskStatus.ready,
                due_date=target_line.due_date,
                dimensions=dimensions,
            ),
        ])
    await session.commit()


@pytest.mark.asyncio
async def test_board_default_limit_returns_total(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    _, target_section, route, raw_stage, target_stage = await _setup_two_stage_route(session)
    await _seed_board_tasks(
        session,
        target_section=target_section,
        route=route,
        raw_stage=raw_stage,
        target_stage=target_stage,
        count=65,
    )

    resp = await client.get(f"/api/shopfloor/sections/{target_section.id}/board")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["tasks"]) == 50
    assert body["total"] == 65
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.asyncio
async def test_board_offset_pagination(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    _, target_section, route, raw_stage, target_stage = await _setup_two_stage_route(session)
    await _seed_board_tasks(
        session,
        target_section=target_section,
        route=route,
        raw_stage=raw_stage,
        target_stage=target_stage,
        count=75,
    )

    first = await client.get(
        f"/api/shopfloor/sections/{target_section.id}/board?limit=50&offset=0",
    )
    second = await client.get(
        f"/api/shopfloor/sections/{target_section.id}/board?limit=50&offset=50",
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    first_ids = {task["id"] for task in first.json()["tasks"]}
    second_ids = {task["id"] for task in second.json()["tasks"]}
    assert len(first_ids) == 50
    assert len(second_ids) == 25
    assert first_ids.isdisjoint(second_ids)
    assert first.json()["total"] == 75
    assert second.json()["total"] == 75


@pytest.mark.asyncio
async def test_board_search_finds_record_on_second_page(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    _, target_section, route, raw_stage, target_stage = await _setup_two_stage_route(session)
    await _seed_board_tasks(
        session,
        target_section=target_section,
        route=route,
        raw_stage=raw_stage,
        target_stage=target_stage,
        count=60,
    )
    await _seed_board_tasks(
        session,
        target_section=target_section,
        route=route,
        raw_stage=raw_stage,
        target_stage=target_stage,
        count=1,
        sku_prefix="UNIQUE-BOARD-MARKER",
        plan_no=f"BOARD-PAGINATION-{uuid.uuid4().hex[:8]}",
    )

    resp = await client.get(
        f"/api/shopfloor/sections/{target_section.id}/board"
        f"?search=UNIQUE-BOARD-MARKER&limit=50&offset=0",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["tasks"]) == 1
    assert body["tasks"][0]["product_sku"] == "UNIQUE-BOARD-MARKER-0000"


@pytest.mark.asyncio
async def test_board_search_by_operation_name(client, session: AsyncSession):
    _, target_section, route, raw_stage, target_stage = await _setup_two_stage_route(session)
    await _seed_board_tasks(
        session,
        target_section=target_section,
        route=route,
        raw_stage=raw_stage,
        target_stage=target_stage,
        count=3,
        operation_name="Обычная операция",
    )
    await _seed_board_tasks(
        session,
        target_section=target_section,
        route=route,
        raw_stage=raw_stage,
        target_stage=target_stage,
        count=1,
        sku_prefix="OP-SEARCH",
        operation_name="UNIQUE-OP-NAME-42",
        plan_no=f"BOARD-PAGINATION-{uuid.uuid4().hex[:8]}",
    )

    board = await get_section_board(
        session,
        section_id=target_section.id,
        search="UNIQUE-OP-NAME-42",
        limit=50,
    )
    assert board["total"] == 1
    assert len(board["tasks"]) == 1
    assert board["tasks"][0]["product_sku"] == "OP-SEARCH-0000"


@pytest.mark.asyncio
async def test_board_sort_by_product_sku(client, session: AsyncSession):
    _, target_section, route, raw_stage, target_stage = await _setup_two_stage_route(session)

    for sku in ("ZZZ-LAST", "AAA-FIRST", "MMM-MID"):
        await _seed_board_tasks(
            session,
            target_section=target_section,
            route=route,
            raw_stage=raw_stage,
            target_stage=target_stage,
            count=1,
            sku_prefix=sku,
            plan_no=f"BOARD-PAGINATION-{uuid.uuid4().hex[:8]}",
        )

    board = await get_section_board(
        session,
        section_id=target_section.id,
        sort="product_sku:asc",
        limit=50,
    )
    skus = [task["product_sku"] for task in board["tasks"]]
    assert skus == sorted(skus)


@pytest.mark.asyncio
async def test_board_sort_by_dimensions_desc(session: AsyncSession):
    """sort_by=dimensions: от большей длины к меньшей, безразмерные (null) — в конец."""
    _, target_section, route, raw_stage, target_stage = await _setup_two_stage_route(session)

    await _seed_board_tasks(
        session, target_section=target_section, route=route,
        raw_stage=raw_stage, target_stage=target_stage, count=1,
        sku_prefix="DIM-1M", plan_no=f"BOARD-DIM-{uuid.uuid4().hex[:8]}",
        dimensions={"length_mm": 1000},
    )
    await _seed_board_tasks(
        session, target_section=target_section, route=route,
        raw_stage=raw_stage, target_stage=target_stage, count=1,
        sku_prefix="DIM-3M", plan_no=f"BOARD-DIM-{uuid.uuid4().hex[:8]}",
        dimensions={"length_mm": 3000},
    )
    await _seed_board_tasks(
        session, target_section=target_section, route=route,
        raw_stage=raw_stage, target_stage=target_stage, count=1,
        sku_prefix="DIM-NONE", plan_no=f"BOARD-DIM-{uuid.uuid4().hex[:8]}",
        dimensions=None,
    )

    board = await get_section_board(
        session,
        section_id=target_section.id,
        sort="dimensions:desc",
        limit=50,
    )
    dims = [task["dimensions"] for task in board["tasks"]]
    assert dims == [{"length_mm": 3000}, {"length_mm": 1000}, None]


@pytest.mark.asyncio
async def test_board_filter_by_dimensions_exact(client, session: AsyncSession):
    """Фильтр dimensions='{"length_mm":2000}' — точное совпадение."""
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    _, target_section, route, raw_stage, target_stage = await _setup_two_stage_route(session)
    await _seed_board_tasks(
        session, target_section=target_section, route=route,
        raw_stage=raw_stage, target_stage=target_stage, count=1,
        sku_prefix="DIM-2M", plan_no=f"BOARD-FILT-{uuid.uuid4().hex[:8]}",
        dimensions={"length_mm": 2000},
    )
    await _seed_board_tasks(
        session, target_section=target_section, route=route,
        raw_stage=raw_stage, target_stage=target_stage, count=1,
        sku_prefix="DIM-OTHER", plan_no=f"BOARD-FILT-{uuid.uuid4().hex[:8]}",
        dimensions={"length_mm": 3500},
    )

    resp = await client.get(
        f"/api/shopfloor/sections/{target_section.id}/board?dimensions={quote('{"length_mm":2000}')}"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["tasks"][0]["product_sku"] == "DIM-2M-0000"
    assert body["tasks"][0]["dimensions"] == {"length_mm": 2000}


@pytest.mark.asyncio
async def test_board_filter_dimensionless(client, session: AsyncSession):
    """Фильтр dimensions=null — только безразмерные задачи."""
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    _, target_section, route, raw_stage, target_stage = await _setup_two_stage_route(session)
    await _seed_board_tasks(
        session, target_section=target_section, route=route,
        raw_stage=raw_stage, target_stage=target_stage, count=1,
        sku_prefix="DIM-SIZED", plan_no=f"BOARD-NULL-{uuid.uuid4().hex[:8]}",
        dimensions={"length_mm": 2000},
    )
    await _seed_board_tasks(
        session, target_section=target_section, route=route,
        raw_stage=raw_stage, target_stage=target_stage, count=1,
        sku_prefix="DIM-DIMLESS", plan_no=f"BOARD-NULL-{uuid.uuid4().hex[:8]}",
        dimensions=None,
    )

    resp = await client.get(
        f"/api/shopfloor/sections/{target_section.id}/board?dimensions=null"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1, f"expected 1, got {body['total']}: {resp.text}"
    assert body["tasks"][0]["product_sku"] == "DIM-DIMLESS-0000"
    assert body["tasks"][0]["dimensions"] is None


@pytest.mark.asyncio
async def test_board_limit_max_validation(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    _, target_section, _, _, _ = await _setup_two_stage_route(session)

    resp = await client.get(f"/api/shopfloor/sections/{target_section.id}/board?limit=1000")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_board_default_order_unchanged(client, session: AsyncSession):
    """Без параметра сортировки доска идёт по sequence, как и до перехода на ?sort=."""
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    _, target_section, route, raw_stage, target_stage = await _setup_two_stage_route(session)
    # Одинаковый sequence у всех задач: порядок целиком определяет tiebreaker.
    for sku in ("ZZZ-LAST", "AAA-FIRST", "MMM-MID"):
        await _seed_board_tasks(
            session,
            target_section=target_section,
            route=route,
            raw_stage=raw_stage,
            target_stage=target_stage,
            count=1,
            sku_prefix=sku,
            plan_no=f"BOARD-DEF-{uuid.uuid4().hex[:8]}",
        )

    board = await get_section_board(session, section_id=target_section.id, limit=50)
    task_ids = [task["id"] for task in board["tasks"]]
    assert len(task_ids) == 3
    assert task_ids == sorted(task_ids), "tiebreaker по id должен быть возрастающим"

    # Явный дефолт даёт тот же порядок, что и отсутствие параметра.
    explicit = await get_section_board(
        session, section_id=target_section.id, sort="sequence:asc", limit=50
    )
    assert [task["id"] for task in explicit["tasks"]] == task_ids

    # Дефолт не «просто любой»: сортировка по не-дефолтному полю переставляет
    # строки. На HEAD, где параметра sort нет, остался бы исходный порядок —
    # этот assert ловит именно перевод на общий контракт.
    by_sku = await get_section_board(
        session, section_id=target_section.id, sort="product_sku:asc", limit=50
    )
    assert [task["product_sku"] for task in by_sku["tasks"]] == [
        "AAA-FIRST-0000",
        "MMM-MID-0000",
        "ZZZ-LAST-0000",
    ]


@pytest.mark.asyncio
async def test_board_multi_sort_priorities(client, session: AsyncSession):
    """Два приоритета: сначала статус, потом артикул.

    Статус у всех задач одинаковый, поэтому порядок по одному полю не алфавитный,
    а по двум — алфавитный. Иначе тест не отличает мультисортировку от
    одиночной сортировки по второму полю.
    """
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    _, target_section, route, raw_stage, target_stage = await _setup_two_stage_route(session)
    for sku in ("ZZZ-LAST", "AAA-FIRST", "MMM-MID"):
        await _seed_board_tasks(
            session,
            target_section=target_section,
            route=route,
            raw_stage=raw_stage,
            target_stage=target_stage,
            count=1,
            sku_prefix=sku,
            plan_no=f"BOARD-MULTI-{uuid.uuid4().hex[:8]}",
        )

    # Один приоритет: статус у всех задач ready, порядок задаёт tiebreaker по id,
    # то есть порядок посева, а не алфавитный.
    by_status = await get_section_board(
        session, section_id=target_section.id, sort="status:asc", limit=50
    )
    seeded_order = [task["product_sku"] for task in by_status["tasks"]]
    assert seeded_order != sorted(seeded_order), (
 "одиночная сортировка по статусу не должна совпасть с алфавитной"
    )

    # Второй приоритет переставляет строки внутри равных по статусу.
    by_both = await get_section_board(
        session,
        section_id=target_section.id,
        sort="status:asc,product_sku:asc",
        limit=50,
    )
    assert [task["product_sku"] for task in by_both["tasks"]] == [
        "AAA-FIRST-0000",
        "MMM-MID-0000",
        "ZZZ-LAST-0000",
    ]


@pytest.mark.asyncio
async def test_board_due_date_nulls_last_both_directions(client, session: AsyncSession):
    """Задачи без срока уходят в конец и при возрастании, и при убывании."""
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    _, target_section, route, raw_stage, target_stage = await _setup_two_stage_route(session)
    await _seed_board_tasks(
        session, target_section=target_section, route=route,
        raw_stage=raw_stage, target_stage=target_stage, count=1,
        sku_prefix="DUE-NONE", plan_no=f"BOARD-DUE-{uuid.uuid4().hex[:8]}",
        due_date=None, set_due_date=True,
    )
    await _seed_board_tasks(
        session, target_section=target_section, route=route,
        raw_stage=raw_stage, target_stage=target_stage, count=1,
        sku_prefix="DUE-LATE", plan_no=f"BOARD-DUE-{uuid.uuid4().hex[:8]}",
        due_date=date(2026, 6, 1), set_due_date=True,
    )
    await _seed_board_tasks(
        session, target_section=target_section, route=route,
        raw_stage=raw_stage, target_stage=target_stage, count=1,
        sku_prefix="DUE-EARLY", plan_no=f"BOARD-DUE-{uuid.uuid4().hex[:8]}",
        due_date=date(2026, 2, 1), set_due_date=True,
    )

    for direction, expected in (
        ("asc", ["DUE-EARLY-0000", "DUE-LATE-0000", "DUE-NONE-0000"]),
        ("desc", ["DUE-LATE-0000", "DUE-EARLY-0000", "DUE-NONE-0000"]),
    ):
        board = await get_section_board(
            session,
            section_id=target_section.id,
            sort=f"due_date:{direction}",
            limit=50,
        )
        assert [task["product_sku"] for task in board["tasks"]] == expected


@pytest.mark.asyncio
async def test_board_rejects_unknown_field_and_direction(client, session: AsyncSession):
    """Неизвестное поле или направление — 400, а не молчаливый фолбэк."""
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    _, target_section, _, _, _ = await _setup_two_stage_route(session)

    unknown_field = await client.get(
        f"/api/shopfloor/sections/{target_section.id}/board?sort=nope:asc"
    )
    assert unknown_field.status_code == 400, unknown_field.text

    bad_direction = await client.get(
        f"/api/shopfloor/sections/{target_section.id}/board?sort=status:sideways"
    )
    assert bad_direction.status_code == 400, bad_direction.text