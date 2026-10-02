"""Справочник значений серверной колонки доски участка (#211).

Поповер фильтра колонки заполняется из текущей СТРАНИЦЫ доски, поэтому
значение с соседней страницы в нём не появляется. Эндпоинт
``/sections/{id}/board/column-values`` отдаёт различные значения колонки под
теми же фильтрами, что и доска, но без фильтра самой колонки (иначе список
схлопнулся бы к выбранному значению).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from app.models.internal_plan import InternalPlan, InternalPlanStatus, SectionPlanLine
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
)
from app.models.work_task import WorkTask, WorkTaskStatus
from sqlalchemy import null, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_shopfloor_board_pagination import (
    _seed_board_tasks,
    _setup_two_stage_route,
)


async def _seed_paired_position(
    session: AsyncSession, *, target_section, route, target_stage, source_sku: str
) -> None:
    """Позиция парного профиля: артикул строки — собранный «A+B»."""
    plan = ProductionPlan(plan_no=f"CV-PAIR-{uuid.uuid4().hex[:8]}", name="CV Pair Plan")
    session.add(plan)
    await session.flush()
    internal_plan = InternalPlan(production_plan_id=plan.id, status=InternalPlanStatus.active)
    session.add(internal_plan)
    await session.flush()

    product = Product(sku="CV-PAIR-OUT", name="CV pair output", type=ProductType.finished_good, unit="pcs")
    session.add(product)
    await session.flush()
    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.excel_import,
        source_sku=source_sku,
        output_sku=source_sku,
        quantity=Decimal(5),
        status=PlanPositionStatus.released,
        validation_status=PlanPositionValidationStatus.valid,
        route_id=route.id,
        source_payload={},
    )
    session.add(position)
    await session.flush()
    line = SectionPlanLine(
        internal_plan_id=internal_plan.id,
        plan_position_id=position.id,
        route_id=route.id,
        route_stage_id=target_stage.id,
        section_id=target_section.id,
        product_id=product.id,
        sequence=2,
        planned_quantity=Decimal(5),
    )
    session.add(line)
    await session.flush()
    session.add(
        WorkTask(
            section_plan_line_id=line.id,
            section_id=target_section.id,
            product_id=product.id,
            route_stage_id=target_stage.id,
            planned_quantity=Decimal(5),
            status=WorkTaskStatus.ready,
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_column_values_not_capped_by_board_page(auth_client, session: AsyncSession) -> None:
    """Значения не зависят от страницы: доска отдаёт 50, справочник — все 60."""
    _, target_section, route, raw_stage, target_stage = await _setup_two_stage_route(session)
    await _seed_board_tasks(
        session,
        target_section=target_section,
        route=route,
        raw_stage=raw_stage,
        target_stage=target_stage,
        count=60,
        sku_prefix="CV-PAGE",
    )

    response = await auth_client.get(
        f"/api/shopfloor/sections/{target_section.id}/board/column-values",
        params={"column": "product_sku", "limit": 500},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["column"] == "product_sku"
    assert body["truncated"] is False
    assert len(body["values"]) == 60
    assert body["values"] == sorted(body["values"])

    # Та же доска с дефолтным лимитом: на странице 50 значений из 60 — поповер
    # по строкам страницы потерял бы десять.
    board = (await auth_client.get(f"/api/shopfloor/sections/{target_section.id}/board")).json()
    assert board["total"] == 60
    page_skus = {task["product_sku"] for task in board["tasks"]}
    assert len(page_skus) == 50
    assert set(body["values"]) - page_skus, "справочник не добавил значений вне страницы"


@pytest.mark.asyncio
async def test_column_values_ignore_own_filter_but_keep_others(auth_client, session: AsyncSession) -> None:
    """Фильтр самой колонки отбрасывается, соседние фильтры — нет."""
    _, target_section, route, raw_stage, target_stage = await _setup_two_stage_route(session)
    await _seed_board_tasks(
        session,
        target_section=target_section,
        route=route,
        raw_stage=raw_stage,
        target_stage=target_stage,
        count=3,
        sku_prefix="CV-OWN",
    )

    # Выбранное значение в колонке не схлопывает список до одного элемента.
    own = (
        await auth_client.get(
            f"/api/shopfloor/sections/{target_section.id}/board/column-values",
            params={"column": "product_sku", "product_sku": "CV-OWN-0000"},
        )
    ).json()
    assert own["values"] == ["CV-OWN-0000", "CV-OWN-0001", "CV-OWN-0002"]

    # Соседний фильтр (статус) продолжает действовать: задачи участка — ready.
    ready = (
        await auth_client.get(
            f"/api/shopfloor/sections/{target_section.id}/board/column-values",
            params={"column": "product_sku", "status": "ready"},
        )
    ).json()
    assert ready["values"] == ["CV-OWN-0000", "CV-OWN-0001", "CV-OWN-0002"]
    completed = (
        await auth_client.get(
            f"/api/shopfloor/sections/{target_section.id}/board/column-values",
            params={"column": "product_sku", "status": "completed"},
        )
    ).json()
    assert completed["values"] == []


@pytest.mark.asyncio
async def test_column_values_limit_cuts_from_top(auth_client, session: AsyncSession) -> None:
    """Срез сверху: limit режет список и поднимает признак `truncated`."""
    _, target_section, route, raw_stage, target_stage = await _setup_two_stage_route(session)
    await _seed_board_tasks(
        session,
        target_section=target_section,
        route=route,
        raw_stage=raw_stage,
        target_stage=target_stage,
        count=5,
        sku_prefix="CV-CAP",
    )

    body = (
        await auth_client.get(
            f"/api/shopfloor/sections/{target_section.id}/board/column-values",
            params={"column": "product_sku", "limit": 2},
        )
    ).json()
    assert body["values"] == ["CV-CAP-0000", "CV-CAP-0001"]
    assert body["limit"] == 2
    assert body["truncated"] is True


@pytest.mark.asyncio
async def test_column_values_show_paired_sku(auth_client, session: AsyncSession) -> None:
    """Значение колонки — то же, что видно в строке: для пары это «A+B»."""
    _, target_section, route, _raw_stage, target_stage = await _setup_two_stage_route(session)
    await _seed_paired_position(
        session,
        target_section=target_section,
        route=route,
        target_stage=target_stage,
        source_sku="CV-PAIR-A+CV-PAIR-B",
    )

    body = (
        await auth_client.get(
            f"/api/shopfloor/sections/{target_section.id}/board/column-values",
            params={"column": "product_sku"},
        )
    ).json()
    assert body["values"] == ["CV-PAIR-A+CV-PAIR-B"]


@pytest.mark.asyncio
async def test_column_values_reject_unknown_column(auth_client) -> None:
    """Колонка без справочника — 400, а не пустой список или 500."""
    response = await auth_client.get(
        "/api/shopfloor/sections/1/board/column-values",
        params={"column": "status"},
    )
    assert response.status_code == 400
    assert "справочник" in response.json()["detail"]


@pytest.mark.asyncio
async def test_column_values_dimensions_narrow_the_board(auth_client, session: AsyncSession) -> None:
    """Значение «Размера» сужает доску, даже если вход этапа — другой (#286).

    Колонка показывает габарит задания (``dimensions``), и справочник обязан
    отдавать ровно его. До #286 «Размер» в справочник не входил: доска
    показывала ``input_dimensions`` трансформирующей строки, а фильтр сравнивал
    ``WorkTask.dimensions`` — выбранное значение дало бы пустую таблицу.
    """
    _, target_section, route, raw_stage, target_stage = await _setup_two_stage_route(session)
    target_stage.transforms_dimensions = True
    await session.flush()
    await _seed_board_tasks(
        session,
        target_section=target_section,
        route=route,
        raw_stage=raw_stage,
        target_stage=target_stage,
        count=2,
        sku_prefix="CV-DIM",
        dimensions={"length_mm": 2000},
    )
    # Вход трансформирующего этапа — другой размер: в колонку он не протекает.
    await session.execute(
        update(WorkTask)
        .where(WorkTask.section_id == target_section.id)
        .values(input_dimensions={"length_mm": 3000}, input_quantity=Decimal(10))
    )
    await session.commit()

    body = (
        await auth_client.get(
            f"/api/shopfloor/sections/{target_section.id}/board/column-values",
            params={"column": "dimensions"},
        )
    ).json()
    assert body["column"] == "dimensions"
    assert body["values"] == ['{"length_mm":2000}']

    board = (
        await auth_client.get(
            f"/api/shopfloor/sections/{target_section.id}/board",
            params={"dimensions": body["values"][0]},
        )
    ).json()
    assert board["total"] == 2


@pytest.mark.asyncio
async def test_column_values_dimensions_offer_dimensionless(auth_client, session: AsyncSession) -> None:
    """Безразмерные — одно значение «null»: «—» в поповере выбирается.

    Безразмерное значение хранится и как SQL `NULL`, и как JSON `null` —
    для `DISTINCT` это два разных значения, для оператора — одно «—».
    """
    _, target_section, route, raw_stage, target_stage = await _setup_two_stage_route(session)
    await _seed_board_tasks(
        session,
        target_section=target_section,
        route=route,
        raw_stage=raw_stage,
        target_stage=target_stage,
        count=2,
        sku_prefix="CV-DIM-NONE",
        dimensions=None,
    )
    # Одна из безразмерных задач — с SQL NULL вместо JSON `null` (SQLAlchemy
    # JSONB пишет `None` как JSON `null`; легаси-строки несут SQL NULL).
    dimensionless_id = await session.scalar(
        select(WorkTask.id)
        .where(WorkTask.section_id == target_section.id)
        .order_by(WorkTask.id)
        .limit(1)
    )
    await session.execute(
        update(WorkTask).where(WorkTask.id == dimensionless_id).values(dimensions=null())
    )
    await session.commit()
    await _seed_board_tasks(
        session,
        target_section=target_section,
        route=route,
        raw_stage=raw_stage,
        target_stage=target_stage,
        count=1,
        sku_prefix="CV-DIM-SIZE",
        dimensions={"length_mm": 2000},
    )

    body = (
        await auth_client.get(
            f"/api/shopfloor/sections/{target_section.id}/board/column-values",
            params={"column": "dimensions"},
        )
    ).json()
    assert body["values"] == ["null", '{"length_mm":2000}']

    board = (
        await auth_client.get(
            f"/api/shopfloor/sections/{target_section.id}/board",
            params={"dimensions": "null"},
        )
    ).json()
    assert board["total"] == 2
