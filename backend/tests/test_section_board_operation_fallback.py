"""Tests for operation_code resolution in section board queries.

Priority order:
1. task.selected_operation_code (explicit override via API)
2. source_payload["operation_code"] (100% confirmed from import)
3. route_step.operation_code (fallback, may be NULL for multi-op sections)

When route_step.operation_code is NULL, the operation comes from source_payload.
This is the correct behavior for sections like Press that have multiple operations
(PRESS_WINDOW, PRESS_COMB) — the specific operation is determined per-task.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.internal_plan import SectionPlanLine, InternalPlan, InternalPlanStatus
from app.models.production_plan import ProductionPlan, PlanPositionStatus, PlanPosition, PlanSourceType, PlanPositionValidationStatus
from app.models.product import Product, ProductType
from app.models.route import ProductionRoute, RouteStep, SectionOperation
from app.models.section import Section
from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.shopfloor.queries_sections import get_section_board


async def _setup_press_section_with_null_route_step(session):
    """Create a press section where route_steps have NULL operation_code.

    This is the correct setup: operation comes from source_payload (import).
    """
    raw_section = Section(code="RAW", name="Склад сырья", is_active=True)
    press_section = Section(code="PRESS", name="Пресс", is_active=True)
    session.add_all([raw_section, press_section])
    await session.flush()

    session.add_all([
        SectionOperation(section_id=press_section.id, operation_code="PRESS_WINDOW", operation_name="Пресс (окно)", is_significant=True),
        SectionOperation(section_id=press_section.id, operation_code="PRESS_COMB", operation_name="Пресс (гребенка)", is_significant=True),
    ])
    session.add(SectionOperation(section_id=raw_section.id, operation_code="ISSUE_RAW", operation_name="Выдача сырья"))
    await session.flush()

    route = ProductionRoute(name="Test Press Route", is_active=True)
    session.add(route)
    await session.flush()

    raw_step = RouteStep(route_id=route.id, sequence=1, section_id=raw_section.id, operation_code="ISSUE_RAW", operation_name="Выдача сырья", is_final=False)
    press_step = RouteStep(route_id=route.id, sequence=2, section_id=press_section.id, operation_code=None, operation_name="Пресс", is_final=True)
    session.add_all([raw_step, press_step])
    await session.flush()

    return raw_section, press_section, route, raw_step, press_step


async def _create_task_for_route(session, route, raw_step, press_route_step, source_payload: dict):
    """Create plan position + section plan lines + work tasks."""
    product = Product(sku="TEST-PRODUCT", name="Test Product", type=ProductType.finished_good, unit="pcs")
    session.add(product)
    await session.flush()

    plan = ProductionPlan(plan_no="PLAN-TEST", name="Test Plan")
    session.add(plan)
    await session.flush()

    internal_plan = InternalPlan(production_plan_id=plan.id, status=InternalPlanStatus.active)
    session.add(internal_plan)
    await session.flush()

    pp = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.excel_import,
        source_sku="TEST-PRODUCT",
        output_sku="TEST-PRODUCT",
        quantity=Decimal("100"),
        status=PlanPositionStatus.released,
        validation_status=PlanPositionValidationStatus.valid,
        route_id=route.id,
        source_payload=source_payload,
    )
    session.add(pp)
    await session.flush()

    raw_line = SectionPlanLine(
        internal_plan_id=internal_plan.id,
        plan_position_id=pp.id,
        route_id=route.id,
        route_step_id=raw_step.id,
        section_id=raw_step.section_id,
        product_id=product.id,
        sequence=1,
        planned_quantity=Decimal("100"),
    )
    press_line = SectionPlanLine(
        internal_plan_id=internal_plan.id,
        plan_position_id=pp.id,
        route_id=route.id,
        route_step_id=press_route_step.id,
        section_id=press_route_step.section_id,
        product_id=product.id,
        sequence=2,
        planned_quantity=Decimal("100"),
    )
    session.add_all([raw_line, press_line])
    await session.flush()

    raw_task = WorkTask(
        section_plan_line_id=raw_line.id,
        section_id=raw_line.section_id,
        product_id=product.id,
        route_step_id=raw_line.route_step_id,
        planned_quantity=Decimal("100"),
        status=WorkTaskStatus.completed,
    )
    press_task = WorkTask(
        section_plan_line_id=press_line.id,
        section_id=press_line.section_id,
        product_id=product.id,
        route_step_id=press_line.route_step_id,
        planned_quantity=Decimal("100"),
        status=WorkTaskStatus.ready,
    )
    session.add_all([raw_task, press_task])
    await session.flush()

    return product, pp, raw_task, press_task


@pytest.mark.asyncio
async def test_section_board_uses_source_payload_when_route_step_is_null(session):
    """When route_step.operation_code is NULL, source_payload operation is used."""
    raw_section, press_section, route, raw_step, press_step = await _setup_press_section_with_null_route_step(session)

    source_payload = {
        "operation_code": "PRESS_WINDOW",
        "operation_name": "Пресс окно",
        "color": "silver",
    }
    product, pp, raw_task, press_task = await _create_task_for_route(session, route, raw_step, press_step, source_payload)

    board = await get_section_board(session, section_id=press_section.id)

    task_codes = [t["operation_code"] for t in board["tasks"]]
    assert "PRESS_WINDOW" in task_codes, f"Expected PRESS_WINDOW in {task_codes}"
    task_names = [t["operation_name"] for t in board["tasks"]]
    assert "Пресс (окно)" in task_names, f"Expected 'Пресс (окно)' in {task_names}"


@pytest.mark.asyncio
async def test_section_board_uses_press_comb_from_source_payload(session):
    """Same with PRESS_COMB — operation comes from source_payload."""
    raw_section, press_section, route, raw_step, press_step = await _setup_press_section_with_null_route_step(session)

    source_payload = {
        "operation_code": "PRESS_COMB",
        "operation_name": "Пресс гребенка",
        "color": "black",
    }
    product, pp, raw_task, press_task = await _create_task_for_route(session, route, raw_step, press_step, source_payload)

    board = await get_section_board(session, section_id=press_section.id)

    task_codes = [t["operation_code"] for t in board["tasks"]]
    assert "PRESS_COMB" in task_codes, f"Expected PRESS_COMB in {task_codes}"
    task_names = [t["operation_name"] for t in board["tasks"]]
    assert "Пресс (гребенка)" in task_names, f"Expected 'Пресс (гребенка)' in {task_names}"


@pytest.mark.asyncio
async def test_section_board_task_override_has_highest_priority(session):
    """task.selected_operation_code overrides source_payload."""
    raw_section, press_section, route, raw_step, press_step = await _setup_press_section_with_null_route_step(session)

    source_payload = {
        "operation_code": "PRESS_WINDOW",
        "color": "silver",
    }
    product, pp, raw_task, press_task = await _create_task_for_route(session, route, raw_step, press_step, source_payload)

    # Set task override
    press_task.selected_operation_code = "PRESS_COMB"
    await session.flush()

    board = await get_section_board(session, section_id=press_section.id)

    task_codes = [t["operation_code"] for t in board["tasks"]]
    assert "PRESS_COMB" in task_codes, f"Expected PRESS_COMB (from task override) in {task_codes}"


@pytest.mark.asyncio
async def test_section_board_no_source_payload_uses_step_operation(session):
    """When source_payload has no operation_code and route_step is NULL,
    effective operation_code is NULL and operation_name comes from step.
    """
    raw_section, press_section, route, raw_step, press_step = await _setup_press_section_with_null_route_step(session)

    source_payload = {
        "color": "silver",
    }
    product, pp, raw_task, press_task = await _create_task_for_route(session, route, raw_step, press_step, source_payload)

    board = await get_section_board(session, section_id=press_section.id)

    task_codes = [t["operation_code"] for t in board["tasks"]]
    # operation_code should be None (from route_step) — displayed as empty or "—"
    assert None in task_codes or "" in task_codes, f"Expected NULL or empty operation_code in {task_codes}"


@pytest.mark.asyncio
async def test_section_board_combined_anod_tasks_have_resolvable_operations(session):
    """On the anodizing section, combined tasks may have operation_code=None
    but combined_operation_names contains the actual operation names.
    The board response must include both available_operations and per-task
    operation data so the frontend can filter correctly.
    """
    # Create anodizing section with multiple operations
    raw_section = Section(code="ANOD-RAW", name="Склад сырья", kind="raw_stock", is_active=True)
    anod_section = Section(code="ANOD", name="Анодирование", kind="production", is_active=True)
    session.add_all([raw_section, anod_section])
    await session.flush()

    # Register operations on anodizing section
    session.add_all([
        SectionOperation(section_id=anod_section.id, operation_code="ANOD_05", operation_name="Чёрный", is_significant=True),
        SectionOperation(section_id=anod_section.id, operation_code="PACK_STRETCH", operation_name="Стрейч", is_significant=True),
        SectionOperation(section_id=raw_section.id, operation_code="ISSUE_RAW", operation_name="Выдача сырья"),
    ])
    await session.flush()

    route = ProductionRoute(name="Anod Route", is_active=True)
    session.add(route)
    await session.flush()

    # Route steps: raw warehouse → anodizing combined group (2 steps same cog)
    raw_step = RouteStep(route_id=route.id, sequence=1, section_id=raw_section.id, operation_code="ISSUE_RAW", operation_name="Выдача сырья", is_final=False)
    # First step of combined group — operation_code=None (placeholder)
    anod_step1 = RouteStep(route_id=route.id, sequence=2, section_id=anod_section.id, operation_code=None, operation_name="Анодирование", combined_op_group="anod_pack", is_final=False)
    # Second step of combined group — has operation_code
    anod_step2 = RouteStep(route_id=route.id, sequence=3, section_id=anod_section.id, operation_code="PACK_STRETCH", operation_name="Стрейч", combined_op_group="anod_pack", is_final=True)
    session.add_all([raw_step, anod_step1, anod_step2])
    await session.flush()

    # Create a product with source_payload specifying the anodizing color
    product = Product(sku="ANOD-TEST-1", name="Test Anodized", type=ProductType.finished_good, unit="pcs")
    session.add(product)
    await session.flush()

    plan = ProductionPlan(plan_no="PLAN-ANOD", name="Anod Plan")
    session.add(plan)
    await session.flush()

    internal_plan = InternalPlan(production_plan_id=plan.id, status=InternalPlanStatus.active)
    session.add(internal_plan)
    await session.flush()

    pp = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.excel_import,
        source_sku=product.sku,
        output_sku=product.sku,
        quantity=Decimal("100"),
        status=PlanPositionStatus.released,
        validation_status=PlanPositionValidationStatus.valid,
        route_id=route.id,
        source_payload={"operation_code": "ANOD_05", "operation_name": "Чёрный"},
    )
    session.add(pp)
    await session.flush()

    # Create SectionPlanLines for each step
    raw_line = SectionPlanLine(
        internal_plan_id=internal_plan.id, plan_position_id=pp.id, route_id=route.id,
        route_step_id=raw_step.id, section_id=raw_section.id, product_id=product.id,
        sequence=1, planned_quantity=Decimal("100"),
    )
    anod_line1 = SectionPlanLine(
        internal_plan_id=internal_plan.id, plan_position_id=pp.id, route_id=route.id,
        route_step_id=anod_step1.id, section_id=anod_section.id, product_id=product.id,
        sequence=2, planned_quantity=Decimal("100"),
    )
    anod_line2 = SectionPlanLine(
        internal_plan_id=internal_plan.id, plan_position_id=pp.id, route_id=route.id,
        route_step_id=anod_step2.id, section_id=anod_section.id, product_id=product.id,
        sequence=3, planned_quantity=Decimal("100"),
    )
    session.add_all([raw_line, anod_line1, anod_line2])
    await session.flush()

    # Create work tasks
    raw_task = WorkTask(section_plan_line_id=raw_line.id, section_id=raw_section.id, product_id=product.id, route_step_id=raw_step.id, planned_quantity=Decimal("100"), status=WorkTaskStatus.completed)
    anod_task1 = WorkTask(section_plan_line_id=anod_line1.id, section_id=anod_section.id, product_id=product.id, route_step_id=anod_step1.id, planned_quantity=Decimal("100"), status=WorkTaskStatus.ready)
    anod_task2 = WorkTask(section_plan_line_id=anod_line2.id, section_id=anod_section.id, product_id=product.id, route_step_id=anod_step2.id, planned_quantity=Decimal("100"), status=WorkTaskStatus.waiting_previous)
    session.add_all([raw_task, anod_task1, anod_task2])
    await session.commit()

    # Get board for anodizing section
    board = await get_section_board(session, section_id=anod_section.id)

    # Verify available_operations has both anodizing operations
    avail_codes = {op["operation_code"] for op in board["available_operations"]}
    avail_names = {op["operation_name"] for op in board["available_operations"]}
    assert "ANOD_05" in avail_codes, f"ANOD_05 not in available_operations codes: {avail_codes}"
    assert "PACK_STRETCH" in avail_codes, f"PACK_STRETCH not in available_operations codes: {avail_codes}"
    assert "Чёрный" in avail_names, f"'Чёрный' not in available_operations names: {avail_names}"
    assert "Стрейч" in avail_names, f"'Стрейч' not in available_operations names: {avail_names}"

    # Each task on the board must have resolvable operation:
    # either operation_code or combined_operation_names matching available_operations
    for task in board["tasks"]:
        op_code = task.get("operation_code")
        combined_names = task.get("combined_operation_names", [])
        is_combined = task.get("is_combined_primary", False)

        if is_combined:
            # Combined task — check that combined_operation_names overlaps with available
            matching_names = [n for n in combined_names if n in avail_names]
            assert len(matching_names) > 0, (
                f"Combined task {task['id']} has combined_operation_names={combined_names} "
                f"but none match available_operations names: {avail_names}"
            )
        else:
            # Non-combined task — operation_code should be in available_operations
            assert op_code in avail_codes, (
                f"Task {task['id']} has operation_code='{op_code}' "
                f"not in available_operations: {avail_codes}"
            )
