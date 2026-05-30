"""
test_combined_operations.py
============================
Тесты для проверки группировки операций с combined_op_group.

Когда несколько шагов маршрута имеют одинаковый combined_op_group
и одинаковый section_id, они должны объединяться в одну SectionPlanLine
и одну WorkTask вместо создания дубликатов.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.internal_plan import SectionPlanLine
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionRouteOrigin,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.release_batch import ReleaseBatch, ReleaseBatchPosition, ReleaseBatchStatus
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
from app.models.techcard import Techcard, TechcardLine
from app.models.work_task import WorkTask, WorkTaskStatus


async def _make_combined_route_product(session, sku: str = "COMBO-1") -> tuple[Product, list[Section], ProductionRoute]:
    """Создать продукт с маршрутом где ANOD имеет combined_op_group."""
    product = Product(sku=sku, name=f"Combined {sku}", type=ProductType.finished_good, unit="pcs")
    component = Product(sku=f"{sku}-RAW", name=f"Raw {sku}", type=ProductType.component, unit="pcs")
    sections = [
        Section(code=f"{sku}-WH", name="Склад сырья", kind="raw_stock"),
        Section(code=f"{sku}-SHOT", name="Дробеструй", kind="production"),
        Section(code=f"{sku}-ANOD", name="Анодирование", kind="production"),
        Section(code=f"{sku}-WIP", name="Склад ГП", kind="finished_stock"),
        Section(code=f"{sku}-SHIP", name="Отгрузка", kind="shipment"),
    ]
    session.add_all([product, component, *sections])
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(TechcardLine(techcard_id=techcard.id, component_product_id=component.id, quantity=1, unit="pcs"))

    route = ProductionRoute(name=f"Route {sku}", is_active=True)
    session.add(route)
    await session.flush()

    # Шаги: WH → SHOT → ANOD(Анодирование) → ANOD(Стрейч) → WIP → SHIP
    # Два шага ANOD с одинаковым combined_op_group должны стать одной задачей
    steps_config = [
        {"section_idx": 0, "op_code": "ISSUE_RAW", "op_name": "Выдача сырья"},
        {"section_idx": 1, "op_code": "SHOT", "op_name": "Дробеструй"},
        {"section_idx": 2, "op_code": None, "op_name": "Анодирование", "cog": "anod_pack"},
        {"section_idx": 2, "op_code": "PACK_STRETCH", "op_name": "Стрейч", "cog": "anod_pack"},
        {"section_idx": 3, "op_code": "FG_WH", "op_name": "Склад ГП"},
        {"section_idx": 4, "op_code": "SHIPMENT", "op_name": "Отгрузка", "is_final": True},
    ]

    for index, cfg in enumerate(steps_config, start=1):
        session.add(
            RouteStep(
                route_id=route.id,
                sequence=index,
                section_id=sections[cfg["section_idx"]].id,
                operation_code=cfg.get("op_code"),
                operation_name=cfg["op_name"],
                combined_op_group=cfg.get("cog"),
                is_final=cfg.get("is_final", False),
            )
        )
    await session.flush()
    return product, sections, route


async def _make_plan_position(
    session,
    product: Product,
    route: ProductionRoute,
    quantity: Decimal = Decimal("100"),
) -> tuple[ProductionPlan, PlanPosition]:
    from datetime import UTC, datetime

    plan = ProductionPlan(
        plan_no=f"PLAN-{product.sku}",
        name=f"Plan {product.sku}",
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
        source_name=product.name,
        quantity=quantity,
        source_payload={},
        period_start=plan.period_start,
        period_end=plan.period_end,
        status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        route_id=route.id,
        route_origin=PlanPositionRouteOrigin.manual_confirmed,
        route_assigned_at=datetime.now(UTC),
        route_manual_confirmed_at=datetime.now(UTC),
    )
    session.add(position)
    await session.flush()
    return plan, position


@pytest.mark.asyncio
async def test_combined_op_group_merges_anod_tasks(client, session) -> None:
    """
    Маршрут с combined_op_group='anod_pack' на двух шагах ANOD должен
    создать ОДНУ задачу вместо двух.

    Ожидаемое кол-во задач: 5 (WH, SHOT, ANOD-combined, WIP, SHIP)
    Вместо: 6 (WH, SHOT, ANOD-1, ANOD-2, WIP, SHIP)
    """
    product, sections, route = await _make_combined_route_product(session, "COMBO-ANOD")
    plan, position = await _make_plan_position(session, product, route)
    await session.commit()

    # Создаём release batch
    create_response = await client.post(
        f"/api/production-plans/{plan.id}/release-batches",
        json={"positions": [{"plan_position_id": position.id, "release_quantity": "100"}]},
    )
    assert create_response.status_code == 201
    batch = create_response.json()

    # Проверяем что в snapshot оба шага с combined_op_group
    snapshot_steps = batch["positions"][0]["route_snapshot"]["steps"]
    anod_steps = [s for s in snapshot_steps if s["section_code"].endswith("ANOD")]
    assert len(anod_steps) == 2  # В snapshot оба шага
    assert anod_steps[0]["combined_op_group"] == "anod_pack"
    assert anod_steps[1]["combined_op_group"] == "anod_pack"

    # Релизим
    release_response = await client.post(f"/api/release-batches/{batch['id']}/release")
    assert release_response.status_code == 200
    released = release_response.json()

    # Ключевая проверка: задач должно быть 5, а не 6
    assert released["task_count"] == 5, f"Expected 5 tasks (combined ANOD), got {released['task_count']}"
    assert released["tasks_created"] == 5

    # Проверяем что SectionPlanLine тоже 5
    lines = (
        await session.execute(
            select(SectionPlanLine)
            .where(SectionPlanLine.plan_position_id == position.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()
    assert len(lines) == 5

    # Проверяем что на участке ANOD только одна задача
    anod_section = sections[2]  # Индекс ANOD
    anod_tasks = (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.section_id == anod_section.id)
        )
    ).scalars().all()
    assert len(anod_tasks) == 1, f"Expected 1 ANOD task (combined), got {len(anod_tasks)}"

    # Проверяем последовательность статусов
    tasks = (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()
    assert len(tasks) == 5
    assert tasks[0].status == WorkTaskStatus.ready
    assert all(task.status == WorkTaskStatus.waiting_previous for task in tasks[1:])

    # Проверяем что у каждой задачи заполнены operation_code и operation_name
    # и они соответствуют этапу маршрута
    from app.services.shopfloor.queries_sections import get_section_board

    # Проверяем для первого участка (Склад сырья)
    raw_section = sections[0]
    board = await get_section_board(session, section_id=raw_section.id)
    assert len(board["tasks"]) == 1
    raw_task_data = board["tasks"][0]
    assert raw_task_data["operation_code"] == "ISSUE_RAW"
    assert raw_task_data["operation_name"] == "Выдача сырья"
    # route_history должен быть пустым для первого этапа
    assert raw_task_data["route_history"] == []

    # Проверяем для участка ANOD (комбинированный этап)
    anod_section = sections[2]
    board_anod = await get_section_board(session, section_id=anod_section.id)
    assert len(board_anod["tasks"]) == 1
    anod_task_data = board_anod["tasks"][0]
    # Операция должна быть определена (из route_step или source_payload)
    assert anod_task_data["operation_code"] is not None or anod_task_data["operation_name"] is not None


@pytest.mark.asyncio
async def test_no_combined_op_group_creates_separate_tasks(client, session) -> None:
    """
    Маршрут БЕЗ combined_op_group должен создавать отдельные задачи
    для каждого шага, даже если section_id одинаковый.
    """
    product = Product(sku="NO-COMBO", name="No Combo", type=ProductType.finished_good, unit="pcs")
    component = Product(sku="NO-COMBO-RAW", name="Raw No Combo", type=ProductType.component, unit="pcs")
    sections = [
        Section(code="NC-WH", name="Склад", kind="raw_stock"),
        Section(code="NC-ANOD", name="Анодирование", kind="production"),
        Section(code="NC-FINAL", name="Финал", kind="finished_stock"),
    ]
    session.add_all([product, component, *sections])
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(TechcardLine(techcard_id=techcard.id, component_product_id=component.id, quantity=1, unit="pcs"))

    route = ProductionRoute(name="No Combo Route", is_active=True)
    session.add(route)
    await session.flush()

    # Два шага ANOD БЕЗ combined_op_group
    session.add_all([
        RouteStep(route_id=route.id, sequence=1, section_id=sections[0].id, operation_code="ISSUE_RAW", operation_name="Выдача"),
        RouteStep(route_id=route.id, sequence=2, section_id=sections[1].id, operation_code=None, operation_name="Анодирование"),
        RouteStep(route_id=route.id, sequence=3, section_id=sections[1].id, operation_code="PACK_STRETCH", operation_name="Стрейч"),
        RouteStep(route_id=route.id, sequence=4, section_id=sections[2].id, operation_code="FINAL", operation_name="Финал", is_final=True),
    ])
    await session.flush()

    plan, position = await _make_plan_position(session, product, route)
    await session.commit()

    create_response = await client.post(
        f"/api/production-plans/{plan.id}/release-batches",
        json={"positions": [{"plan_position_id": position.id, "release_quantity": "100"}]},
    )
    assert create_response.status_code == 201
    batch = create_response.json()

    release_response = await client.post(f"/api/release-batches/{batch['id']}/release")
    assert release_response.status_code == 200
    released = release_response.json()

    # Без combined_op_group — 4 отдельные задачи
    assert released["task_count"] == 4
    assert released["tasks_created"] == 4


@pytest.mark.asyncio
async def test_different_cog_same_section_creates_separate_tasks(client, session) -> None:
    """
    Если два шага на одном участке имеют РАЗНЫЕ combined_op_group,
    они должны оставаться отдельными задачами.
    """
    product = Product(sku="DIFF-COG", name="Diff COG", type=ProductType.finished_good, unit="pcs")
    component = Product(sku="DIFF-COG-RAW", name="Raw Diff COG", type=ProductType.component, unit="pcs")
    sections = [
        Section(code="DC-WH", name="Склад", kind="raw_stock"),
        Section(code="DC-ANOD", name="Анодирование", kind="production"),
        Section(code="DC-FINAL", name="Финал", kind="finished_stock"),
    ]
    session.add_all([product, component, *sections])
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(TechcardLine(techcard_id=techcard.id, component_product_id=component.id, quantity=1, unit="pcs"))

    route = ProductionRoute(name="Diff COG Route", is_active=True)
    session.add(route)
    await session.flush()

    # Два шага ANOD с РАЗНЫМИ combined_op_group
    session.add_all([
        RouteStep(route_id=route.id, sequence=1, section_id=sections[0].id, operation_code="ISSUE_RAW", operation_name="Выдача"),
        RouteStep(route_id=route.id, sequence=2, section_id=sections[1].id, operation_name="Анодирование", combined_op_group="anod_pack"),
        RouteStep(route_id=route.id, sequence=3, section_id=sections[1].id, operation_code="PACK_SPUNBOND", operation_name="Спанбонд", combined_op_group="anod_spunbond"),
        RouteStep(route_id=route.id, sequence=4, section_id=sections[2].id, operation_code="FINAL", operation_name="Финал", is_final=True),
    ])
    await session.flush()

    plan, position = await _make_plan_position(session, product, route)
    await session.commit()

    create_response = await client.post(
        f"/api/production-plans/{plan.id}/release-batches",
        json={"positions": [{"plan_position_id": position.id, "release_quantity": "100"}]},
    )
    assert create_response.status_code == 201
    batch = create_response.json()

    release_response = await client.post(f"/api/release-batches/{batch['id']}/release")
    assert release_response.status_code == 200
    released = release_response.json()

    # Разные COG — 4 отдельные задачи
    assert released["task_count"] == 4
