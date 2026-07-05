"""Pagination, total, search and sort for GET /api/shopfloor/sections/{id}/board."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.internal_plan import InternalPlan, InternalPlanStatus, SectionPlanLine
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
from app.models.user import User, UserRole
from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.shopfloor.queries_sections import get_section_board


async def _make_user(session: AsyncSession) -> User:
    user = User(
        username="board-page-tester",
        email="board-page-tester@local",
        password_hash="x",
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
            quantity=Decimal("10"),
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
            planned_quantity=Decimal("10"),
        )
        target_line = SectionPlanLine(
            internal_plan_id=internal_plan.id,
            plan_position_id=position.id,
            route_id=route.id,
            route_stage_id=target_stage.id,
            section_id=target_stage.section_id,
            product_id=product.id,
            sequence=2,
            planned_quantity=Decimal("10"),
            due_date=date(2026, 1, 1 + (i % 28)),
        )
        session.add_all([raw_line, target_line])
        await session.flush()

        session.add_all([
            WorkTask(
                section_plan_line_id=raw_line.id,
                section_id=raw_line.section_id,
                product_id=product.id,
                route_stage_id=raw_line.route_stage_id,
                planned_quantity=Decimal("10"),
                status=WorkTaskStatus.completed,
            ),
            WorkTask(
                section_plan_line_id=target_line.id,
                section_id=target_line.section_id,
                product_id=product.id,
                route_stage_id=target_line.route_stage_id,
                planned_quantity=Decimal("10"),
                status=WorkTaskStatus.ready,
                due_date=target_line.due_date,
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
        sort_by="product_sku",
        sort_order="asc",
        limit=50,
    )
    skus = [task["product_sku"] for task in board["tasks"]]
    assert skus == sorted(skus)


@pytest.mark.asyncio
async def test_board_limit_max_validation(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    _, target_section, _, _, _ = await _setup_two_stage_route(session)

    resp = await client.get(f"/api/shopfloor/sections/{target_section.id}/board?limit=1000")
    assert resp.status_code == 422