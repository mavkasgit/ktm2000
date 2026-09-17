"""Трансформирующий этап маршрута и генерация заданий (ADR-0002, issue #7).

Задание на трансформирующем этапе несёт вход (количество × входной габарит)
и спецификацию выходов из позиции плана; на нетрансформирующих этапах
задания создаются как раньше. Маркер — поле модели, заполняется сидом.
"""
from datetime import UTC, date, datetime
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
from app.models.route import ProductionRoute, RouteOperation, RouteStage, SectionOperation
from app.models.section import Section
from app.models.work_task import WorkTask
from app.services.route_transform import (
    build_transform_spec,
    resolve_stage_transforms_dimensions,
)
from app.services.shopfloor.queries_sections import get_section_board


# --- helpers ---


async def _make_product_with_route(
    session,
    sku: str,
    *,
    transform_stage_sequence: int | None = None,
) -> tuple[Product, list[Section], ProductionRoute, list[RouteStage]]:
    """Продукт + маршрут из 6 производственных этапов.

    Этап с ``sequence == transform_stage_sequence`` помечается маркером
    трансформации напрямую (эквивалент того, что делает сид).
    """
    product = Product(sku=sku, name=f"Finished {sku}", type=ProductType.finished_good, unit="pcs")
    component = Product(sku=f"{sku}-RAW", name=f"Raw {sku}", type=ProductType.component, unit="pcs")
    sections = [
        Section(code=f"{sku}-ISSUE", name="Issue", type="production"),
        Section(code=f"{sku}-DRILL", name="Drill", type="production"),
        Section(code=f"{sku}-SAWLIKE", name="Sawlike", type="production"),
        Section(code=f"{sku}-ANOD", name="Anod", type="production"),
        Section(code=f"{sku}-WIP", name="WIP", type="production"),
        Section(code=f"{sku}-FINAL", name="Final", type="production"),
    ]
    session.add_all([product, component, *sections])
    await session.flush()

    await session.flush()

    route = ProductionRoute(name=f"Route {sku}", is_active=True)
    session.add(route)
    await session.flush()

    stages: list[RouteStage] = []
    step_ops = ["ISSUE_RAW", "DRILL", "SAW", "ANOD", "MOVE_TO_WIP", "ACCEPT_FINISHED"]
    for index, (section, op_code) in enumerate(zip(sections, step_ops, strict=True), start=1):
        stage = RouteStage(
            route_id=route.id,
            sequence=index,
            section_id=section.id,
            is_final=index == len(sections),
            transforms_dimensions=index == transform_stage_sequence,
        )
        session.add(stage)
        await session.flush()
        session.add(
            RouteOperation(
                route_stage_id=stage.id,
                sequence=1,
                operation_code=op_code,
                operation_name=op_code,
            )
        )
        stages.append(stage)
    await session.flush()
    return product, sections, route, stages


async def _make_position(
    session,
    product: Product,
    route: ProductionRoute,
    *,
    quantity: Decimal,
    input_quantity: Decimal | None = None,
    input_dimensions: dict | None = None,
    outputs: list[dict] | None = None,
) -> tuple[ProductionPlan, PlanPosition]:
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
        input_quantity=input_quantity,
        input_dimensions=input_dimensions,
        outputs=outputs or [],
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


async def _release(client, plan: ProductionPlan, position: PlanPosition, quantity: str) -> None:
    create_response = await client.post(
        f"/api/production-plans/{plan.id}/release-batches",
        json={"positions": [{"plan_position_id": position.id, "release_quantity": quantity}]},
    )
    assert create_response.status_code == 201, create_response.text
    release_response = await client.post(f"/api/release-batches/{create_response.json()['id']}/release")
    assert release_response.status_code == 200, release_response.text


async def _tasks_by_sequence(session, position: PlanPosition) -> list[WorkTask]:
    return (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == position.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()


MULTI_OUTPUTS = [
    {"row_number": 6, "quantity": "150", "dimensions": {"length_mm": 900}},
    {"row_number": 7, "quantity": "150", "dimensions": {"length_mm": 1800}},
]


# --- генерация заданий ---


@pytest.mark.asyncio
async def test_transforming_stage_task_carries_input_and_multiple_outputs(client, session) -> None:
    product, _, route, stages = await _make_product_with_route(session, "FG-TR-MULTI", transform_stage_sequence=3)
    plan, position = await _make_position(
        session,
        product,
        route,
        quantity=Decimal("300"),
        input_quantity=Decimal("150"),
        input_dimensions={"length_mm": 2700},
        outputs=MULTI_OUTPUTS,
    )
    await session.commit()

    await _release(client, plan, position, "300")

    tasks = await _tasks_by_sequence(session, position)
    assert len(tasks) == 6

    transform_task = tasks[2]
    assert transform_task.route_stage_id == stages[2].id
    assert transform_task.input_quantity == Decimal("150")
    assert transform_task.input_dimensions == {"length_mm": 2700}
    assert transform_task.outputs == MULTI_OUTPUTS

    # На нетрансформирующих этапах задания не изменились.
    for task in tasks[:2] + tasks[3:]:
        assert task.input_quantity is None
        assert task.input_dimensions is None
        assert task.outputs == []


@pytest.mark.asyncio
async def test_transforming_stage_task_single_output(client, session) -> None:
    product, _, route, stages = await _make_product_with_route(session, "FG-TR-SINGLE", transform_stage_sequence=3)
    single = [{"row_number": 6, "quantity": "100", "dimensions": {"length_mm": 900}}]
    plan, position = await _make_position(
        session,
        product,
        route,
        quantity=Decimal("100"),
        input_quantity=Decimal("100"),
        input_dimensions={"length_mm": 2700},
        outputs=single,
    )
    await session.commit()

    await _release(client, plan, position, "100")

    tasks = await _tasks_by_sequence(session, position)
    transform_task = tasks[2]
    assert transform_task.input_quantity == Decimal("100")
    assert transform_task.input_dimensions == {"length_mm": 2700}
    assert transform_task.outputs == single


@pytest.mark.asyncio
async def test_position_without_dimensions_creates_plain_tasks(client, session) -> None:
    product, _, route, _ = await _make_product_with_route(session, "FG-TR-PLAIN", transform_stage_sequence=3)
    plan, position = await _make_position(session, product, route, quantity=Decimal("100"))
    await session.commit()

    await _release(client, plan, position, "100")

    tasks = await _tasks_by_sequence(session, position)
    assert len(tasks) == 6
    for task in tasks:
        assert task.input_quantity is None
        assert task.input_dimensions is None
        assert task.outputs == []


@pytest.mark.asyncio
async def test_partial_release_scales_input_and_outputs(client, session) -> None:
    product, _, route, _ = await _make_product_with_route(session, "FG-TR-PART", transform_stage_sequence=3)
    plan, position = await _make_position(
        session,
        product,
        route,
        quantity=Decimal("300"),
        input_quantity=Decimal("150"),
        input_dimensions={"length_mm": 2700},
        outputs=MULTI_OUTPUTS,
    )
    await session.commit()

    await _release(client, plan, position, "150")

    tasks = await _tasks_by_sequence(session, position)
    transform_task = tasks[2]
    assert transform_task.input_quantity == Decimal("75")
    assert transform_task.input_dimensions == {"length_mm": 2700}
    assert [entry["quantity"] for entry in transform_task.outputs] == ["75", "75"]
    assert [entry["dimensions"] for entry in transform_task.outputs] == [
        {"length_mm": 900},
        {"length_mm": 1800},
    ]


@pytest.mark.asyncio
async def test_stages_before_transform_planned_in_raw_input_units(client, session) -> None:
    """До пилы группа идёт одним заданием в штуках входа (сырьё), с пилы — в штуках позиции."""
    product, _, route, stages = await _make_product_with_route(session, "FG-TR-RAW", transform_stage_sequence=3)
    plan, position = await _make_position(
        session,
        product,
        route,
        quantity=Decimal("300"),
        input_quantity=Decimal("150"),
        input_dimensions={"length_mm": 2700},
        outputs=MULTI_OUTPUTS,
    )
    await session.commit()

    await _release(client, plan, position, "300")

    tasks = await _tasks_by_sequence(session, position)
    assert len(tasks) == 6

    transform_stage = next(stage for stage in stages if stage.transforms_dimensions)
    pre_stage_ids = {stage.id for stage in stages if stage.sequence < transform_stage.sequence}
    pre_tasks = [task for task in tasks if task.route_stage_id in pre_stage_ids]
    assert len(pre_stage_ids) >= 2, "маршрут-хелпер: перед пилой есть этапы"
    assert len(pre_tasks) == len(pre_stage_ids), "каждый этап до пилы получает задание"
    for task in pre_tasks:
        # Сырьё: 150 штук входа, а не 300 штук выходов.
        assert task.planned_quantity == Decimal("150")
        assert task.input_quantity is None

    transform_task = next(task for task in tasks if task.route_stage_id == transform_stage.id)
    assert transform_task.planned_quantity == Decimal("300")
    assert transform_task.input_quantity == Decimal("150")

    post_tasks = [
        task for task in tasks if task.route_stage_id not in (pre_stage_ids | {transform_stage.id})
    ]
    assert len(post_tasks) == 3, "этапы после пилы получают задания"
    for task in post_tasks:
        # Пила и далее — штуки позиции (выходы).
        assert task.planned_quantity == Decimal("300")


@pytest.mark.asyncio
async def test_partial_release_scales_stages_before_transform(client, session) -> None:
    """Частичный релиз: до пилы план — доля входа, с пилы — доля выхода."""
    product, _, route, stages = await _make_product_with_route(session, "FG-TR-RAW-PART", transform_stage_sequence=3)
    plan, position = await _make_position(
        session,
        product,
        route,
        quantity=Decimal("300"),
        input_quantity=Decimal("150"),
        input_dimensions={"length_mm": 2700},
        outputs=MULTI_OUTPUTS,
    )
    await session.commit()

    await _release(client, plan, position, "150")

    tasks = await _tasks_by_sequence(session, position)
    transform_stage = next(stage for stage in stages if stage.transforms_dimensions)
    pre_stage_ids = {stage.id for stage in stages if stage.sequence < transform_stage.sequence}
    assert len(pre_stage_ids) >= 2, "маршрут-хелпер: перед пилой есть этапы"

    for task in tasks:
        if task.route_stage_id in pre_stage_ids:
            # 150 штук входа × (150 / 300) — половина сырья.
            assert task.planned_quantity == Decimal("75")
        else:
            # Пила и далее — половина штук позиции.
            assert task.planned_quantity == Decimal("150")

    transform_task = next(task for task in tasks if task.route_stage_id == transform_stage.id)
    assert transform_task.input_quantity == Decimal("75")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sku", "transform_stage_sequence", "input_quantity"),
    [
        ("FG-TR-NOINPUT", 3, None),
        ("FG-TR-NOSAW", None, Decimal("150")),
    ],
    ids=["no_input_quantity", "no_transform_stage"],
)
async def test_without_raw_basis_all_stages_planned_in_position_units(
    client,
    session,
    sku: str,
    transform_stage_sequence: int | None,
    input_quantity: Decimal | None,
) -> None:
    """Нет сырьевого базиса (нет входа у позиции или нет пилы в маршруте) → везде штуки позиции."""
    product, _, route, _ = await _make_product_with_route(
        session, sku, transform_stage_sequence=transform_stage_sequence
    )
    plan, position = await _make_position(
        session,
        product,
        route,
        quantity=Decimal("300"),
        input_quantity=input_quantity,
        input_dimensions={"length_mm": 2700} if input_quantity is not None else None,
        outputs=MULTI_OUTPUTS,
    )
    await session.commit()

    await _release(client, plan, position, "300")

    tasks = await _tasks_by_sequence(session, position)
    assert len(tasks) == 6
    for task in tasks:
        assert task.planned_quantity == Decimal("300")


# --- доска участка ---


@pytest.mark.asyncio
async def test_section_board_shows_single_card_with_summary(client, session) -> None:
    product, sections, route, _ = await _make_product_with_route(session, "FG-TR-BOARD", transform_stage_sequence=3)
    plan, position = await _make_position(
        session,
        product,
        route,
        quantity=Decimal("300"),
        input_quantity=Decimal("150"),
        input_dimensions={"length_mm": 2700},
        outputs=MULTI_OUTPUTS,
    )
    await session.commit()

    await _release(client, plan, position, "300")

    board = await get_section_board(session, section_id=sections[2].id)
    assert len(board["tasks"]) == 1  # одна позиция плана = одна карточка
    card = board["tasks"][0]
    assert card["transforms_dimensions"] is True
    assert card["input_quantity"] == "150"
    assert card["input_dimensions"] == {"length_mm": 2700}
    assert card["outputs"] == MULTI_OUTPUTS
    assert card["cut_layout"] == {"input": "2,7", "outputs": ["0,9×150", "1,8×150"]}

    plain_board = await get_section_board(session, section_id=sections[1].id)
    assert len(plain_board["tasks"]) == 1
    plain_card = plain_board["tasks"][0]
    assert plain_card["transforms_dimensions"] is False
    assert plain_card["cut_layout"] is None
    assert plain_card["outputs"] == []


# --- resolve_stage_transforms_dimensions (справочник → этап) ---


async def _make_section_with_ops(session, code: str, ops: list[tuple[str, bool]]) -> Section:
    section = Section(code=code, name=code, type="production")
    session.add(section)
    await session.flush()
    for op_code, transforms in ops:
        session.add(
            SectionOperation(
                section_id=section.id,
                operation_code=op_code,
                operation_name=op_code,
                transforms_dimensions=transforms,
            )
        )
    await session.flush()
    return section


@pytest.mark.asyncio
async def test_resolve_marker_explicit_operation_match(session) -> None:
    section = await _make_section_with_ops(session, "RSV-MATCH", [("SAW", True), ("MOVE", False)])
    assert await resolve_stage_transforms_dimensions(session, section_id=section.id, operation_codes=["SAW"]) is True
    assert await resolve_stage_transforms_dimensions(session, section_id=section.id, operation_codes=["MOVE"]) is False


@pytest.mark.asyncio
async def test_resolve_marker_inherits_section_capability_without_explicit_ops(session) -> None:
    section = await _make_section_with_ops(session, "RSV-INHERIT", [("SAW", True)])
    # Динамические маршруты: operation_code=None → этап наследует способность участка.
    assert await resolve_stage_transforms_dimensions(session, section_id=section.id, operation_codes=[None]) is True
    assert await resolve_stage_transforms_dimensions(session, section_id=section.id) is True


@pytest.mark.asyncio
async def test_resolve_marker_false_without_transforming_ops(session) -> None:
    section = await _make_section_with_ops(session, "RSV-NONE", [("MOVE", False)])
    assert await resolve_stage_transforms_dimensions(session, section_id=section.id) is False
    assert await resolve_stage_transforms_dimensions(session, section_id=None) is False


# --- build_transform_spec (чистая логика) ---


def _position_stub(quantity: str, input_quantity: str | None, outputs: list[dict]) -> PlanPosition:
    return PlanPosition(
        quantity=Decimal(quantity),
        input_quantity=Decimal(input_quantity) if input_quantity is not None else None,
        input_dimensions={"length_mm": 2700} if input_quantity is not None else None,
        outputs=outputs,
    )


def test_build_transform_spec_empty_outputs_gives_no_fields() -> None:
    position = _position_stub("100", None, [])
    assert build_transform_spec(position, Decimal("100")) == {}


def test_build_transform_spec_zero_quantity_gives_no_fields() -> None:
    position = _position_stub("300", "150", list(MULTI_OUTPUTS))
    assert build_transform_spec(position, Decimal("0")) == {}


def test_build_transform_spec_does_not_mutate_position_outputs() -> None:
    outputs = [dict(entry) for entry in MULTI_OUTPUTS]
    position = _position_stub("300", "150", outputs)
    spec = build_transform_spec(position, Decimal("150"))
    assert spec["input_quantity"] == Decimal("75")
    assert [entry["quantity"] for entry in spec["outputs"]] == ["75", "75"]
    # Исходные выходы позиции не изменились.
    assert [entry["quantity"] for entry in outputs] == ["150", "150"]


# --- сид помечает SAWING ---


@pytest.mark.asyncio
async def test_seed_marks_sawing_operation_and_stage_as_transforming(client, session) -> None:
    for index, (code, type_) in enumerate(
        [
            ("RAW_STOCK", "raw_stock"),
            ("DRILLING", "production"),
            ("PRESSING", "production"),
            ("SHOT_BLAST", "production"),
            ("PREP_STOCK", "wip_stock"),
            ("ANODIZING", "production"),
            ("WIP_STOCK", "wip_stock"),
            ("SAWING", "production"),
            ("PACKING", "production"),
            ("FINISHED_STOCK", "finished_stock"),
            ("SHIPMENT", "finished_stock"),
            ("SHIPPED", "finished_stock"),
        ],
        start=1,
    ):
        session.add(Section(code=code, name=code, sort_order=index * 10, type=type_, is_active=True))
    await session.commit()

    response = await client.post("/api/routes-seed")
    assert response.status_code == 201, response.text

    sawing = await session.scalar(select(Section).where(Section.code == "SAWING"))
    saw_op = await session.scalar(
        select(SectionOperation).where(
            SectionOperation.section_id == sawing.id,
            SectionOperation.operation_code == "SAW",
        )
    )
    assert saw_op is not None
    assert saw_op.transforms_dimensions is True

    # Остальные операции справочника — не трансформирующие.
    other_transforming = (
        await session.execute(
            select(SectionOperation).where(
                SectionOperation.transforms_dimensions.is_(True),
                SectionOperation.id != saw_op.id,
            )
        )
    ).scalars().all()
    assert other_transforming == []

    # Этап SAWING в засеянных маршрутах несёт маркер, остальные — нет.
    stages = (
        await session.execute(
            select(RouteStage).where(RouteStage.section_id.isnot(None))
        )
    ).scalars().all()
    assert stages, "seed created no route stages"
    for stage in stages:
        expected = stage.section_id == sawing.id
        assert stage.transforms_dimensions is expected, (
            f"stage seq={stage.sequence} section_id={stage.section_id}: "
            f"transforms_dimensions={stage.transforms_dimensions}, expected {expected}"
        )
