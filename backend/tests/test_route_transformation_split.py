"""
test_route_transformation_split.py
===================================
Тест сценария: 6 позиций плана с одним артикулом → на складе сырья объединяются
в одну группу (т.к. до них ничего не было), а на следующих этапах разделяются
по операциям (пресс, цвет, упаковка).

Сценарий:
  6 PlanPosition с артикулом ЮП-460, каждая с разным source_payload
    → Склад сырья: 6 задач, но grouping key одинаковый (пустой route_history)
    → Пресс: 6 задач, разделяются по operation_code (PRESS_WINDOW / PRESS_COMB)
    → Анодирование: 6 задач, route_history = [Выдача сырья]
    → Склад ГП: 6 задач, route_history = [Выдача сырья, Анодирование]

Проверяем:
  1. route_history для первого этапа пустой (ничего не было до)
  2. route_history_after для первого этапа содержит только текущую операцию
  3. На этапах после первого route_history содержит все значимые операции до
  4. Суммарный план на каждом этапе = 1000
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.internal_plan import InternalPlan, InternalPlanStatus, SectionPlanLine
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
from app.models.route import ProductionRoute, RouteStep, SectionOperation
from app.models.section import Section
from app.models.techcard import Techcard, TechcardLine
from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.shopfloor.queries_sections import get_section_board


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_transformation_route(session, sku: str = "SPLIT-1") -> tuple[Product, list[Section], ProductionRoute]:
    """Создать продукт и маршрут с трансформацией на прессе/аноде/упаковке.

    Маршрут:
      1. RAW_WH   — Выдача сырья (sequence=1, is_significant=True)
      2. PRESS    — Пресс (sequence=2, operation_code=NULL, определяется из payload)
      3. ANOD     — Анодирование (sequence=3, is_significant=True)
      4. PACK     — Упаковка (sequence=4)
      5. FG_WH    — Склад готовой продукции (sequence=5, is_final=True)
    """
    product = Product(sku=sku, name=f"Profile {sku}", type=ProductType.finished_good, unit="pcs")
    component = Product(sku=f"{sku}-BILLET", name=f"Billet {sku}", type=ProductType.component, unit="pcs")

    sections = [
        Section(code=f"{sku}-RAW", name="Склад сырья", kind="raw_stock"),
        Section(code=f"{sku}-PRESS", name="Пресс", kind="production"),
        Section(code=f"{sku}-ANOD", name="Анодирование", kind="production"),
        Section(code=f"{sku}-PACK", name="Упаковка", kind="production"),
        Section(code=f"{sku}-FG", name="Склад ГП", kind="finished_stock"),
    ]
    session.add_all([product, component, *sections])
    await session.flush()

    # Section operations
    session.add_all([
        SectionOperation(section_id=sections[0].id, operation_code="ISSUE_RAW", operation_name="Выдача сырья", is_significant=True),
        SectionOperation(section_id=sections[1].id, operation_code="PRESS_WINDOW", operation_name="Пресс (окно)", is_significant=True),
        SectionOperation(section_id=sections[1].id, operation_code="PRESS_COMB", operation_name="Пресс (гребенка)", is_significant=True),
        SectionOperation(section_id=sections[2].id, operation_code="ANODIZE", operation_name="Анодирование", is_significant=True),
        SectionOperation(section_id=sections[3].id, operation_code="PACK_STRETCH", operation_name="Стрейч"),
        SectionOperation(section_id=sections[3].id, operation_code="PACK_SPUNBOND", operation_name="Спанбонд"),
    ])
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(TechcardLine(techcard_id=techcard.id, component_product_id=component.id, quantity=Decimal("1"), unit="pcs"))

    route = ProductionRoute(name=f"Route {sku}", is_active=True)
    session.add(route)
    await session.flush()

    steps_config = [
        {"section_idx": 0, "op_code": "ISSUE_RAW", "op_name": "Выдача сырья", "significant": True},
        {"section_idx": 1, "op_code": None, "op_name": "Пресс", "significant": False},
        {"section_idx": 2, "op_code": "ANODIZE", "op_name": "Анодирование", "significant": True},
        {"section_idx": 3, "op_code": None, "op_name": "Упаковка", "significant": False},
        {"section_idx": 4, "op_code": "FG_WH", "op_name": "Склад ГП", "is_final": True},
    ]

    for idx, cfg in enumerate(steps_config, start=1):
        session.add(
            RouteStep(
                route_id=route.id,
                sequence=idx,
                section_id=sections[cfg["section_idx"]].id,
                operation_code=cfg.get("op_code"),
                operation_name=cfg["op_name"],
                is_significant=cfg.get("significant", False),
                is_final=cfg.get("is_final", False),
            )
        )

    await session.flush()
    return product, sections, route


# ---------------------------------------------------------------------------
# 6 вариантов — разные комбинации пресса, цвета, упаковки
# ---------------------------------------------------------------------------

VARIANTS = [
    {"quantity": 200, "operation_code": "PRESS_WINDOW", "output_kind": "silver", "pack_operation": "PACK_STRETCH"},
    {"quantity": 150, "operation_code": "PRESS_WINDOW", "output_kind": "silver", "pack_operation": "PACK_SPUNBOND"},
    {"quantity": 180, "operation_code": "PRESS_WINDOW", "output_kind": "black", "pack_operation": "PACK_STRETCH"},
    {"quantity": 170, "operation_code": "PRESS_COMB", "output_kind": "silver", "pack_operation": "PACK_STRETCH"},
    {"quantity": 160, "operation_code": "PRESS_COMB", "output_kind": "black", "pack_operation": "PACK_SPUNBOND"},
    {"quantity": 140, "operation_code": "PRESS_COMB", "output_kind": "black", "pack_operation": "PACK_STRETCH"},
]


async def _create_six_positions_and_tasks(
    session,
    product: Product,
    sections: list[Section],
    route: ProductionRoute,
) -> tuple[ProductionPlan, list[PlanPosition]]:
    """Создать 6 PlanPosition + InternalPlan + SectionPlanLine + WorkTask.

    Каждая PlanPosition — отдельная строка плана с разным source_payload.
    Все проходят через один и тот же маршрут.
    """
    from datetime import UTC, datetime

    route_steps = (
        await session.execute(
            select(RouteStep)
            .where(RouteStep.route_id == route.id)
            .order_by(RouteStep.sequence)
        )
    ).scalars().all()

    plan = ProductionPlan(
        plan_no=f"PLAN-{product.sku}",
        name=f"Plan {product.sku}",
        status=ProductionPlanStatus.approved,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()

    positions = []
    internal_plans = []

    for idx, var in enumerate(VARIANTS, start=1):
        qty = Decimal(str(var["quantity"]))
        # PlanPosition
        # Не кладём operation_code в source_payload напрямую — он подхватывается
        # fallback-логикой на всех этапах. Вместо этого используем selected_operation_code
        # на задачах где route_step.operation_code = NULL (пресс, упаковка).
        payload = {
            "operation_name": f'Пресс ({var["operation_code"]})',
            "output_kind": var["output_kind"],
            "pack_operation": var["pack_operation"],
        }

        # PlanPosition
        pos = PlanPosition(
            production_plan_id=plan.id,
            product_id=product.id,
            source_type=PlanSourceType.manual,
            source_sku=product.sku,
            source_name=product.name,
            output_sku=product.sku,
            quantity=qty,
            source_payload=payload,
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
        session.add(pos)
        await session.flush()
        positions.append(pos)

        # InternalPlan
        internal_plan = InternalPlan(production_plan_id=plan.id, status=InternalPlanStatus.active)
        session.add(internal_plan)
        await session.flush()
        internal_plans.append(internal_plan)

        # SectionPlanLine + WorkTask for each route step
        for step_idx, step in enumerate(route_steps, start=1):
            line = SectionPlanLine(
                internal_plan_id=internal_plan.id,
                plan_position_id=pos.id,
                route_id=route.id,
                route_step_id=step.id,
                section_id=step.section_id,
                product_id=product.id,
                sequence=step_idx,
                planned_quantity=qty,
            )
            session.add(line)
            await session.flush()

            status = WorkTaskStatus.ready if step_idx == 1 else WorkTaskStatus.waiting_previous

            # selected_operation_code: ставим только на этапах где route_step.operation_code = NULL
            # Пресс (step_idx=2) и Упаковка (step_idx=4) имеют NULL operation_code
            effective_op_code = None
            if step_idx == 2:
                # Пресс — берём operation_code из варианта
                effective_op_code = var["operation_code"]
            elif step_idx == 4:
                # Упаковка — берём pack_operation
                effective_op_code = var["pack_operation"]

            task = WorkTask(
                section_plan_line_id=line.id,
                section_id=step.section_id,
                product_id=product.id,
                route_step_id=step.id,
                planned_quantity=qty,
                status=status,
                selected_operation_code=effective_op_code,
            )
            session.add(task)
            await session.flush()

    await session.commit()
    return plan, positions


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_one_sku_splits_into_six_by_operations(client, session) -> None:
    """6 позиций с одним артикулом → объединяются на первом этапе → разделяются дальше.

    Склад сырья: 6 задач, route_history пустой у всех (ничего не было до).
    Пресс: 6 задач, route_history = [Выдача сырья], разные operation_code.
    Анод: 6 задач, route_history = [Выдача сырья] (Пресс не значимый).
    Склад ГП: 6 задач, route_history = [Выдача сырья, Анодирование].
    """
    product, sections, route = await _make_transformation_route(session, "ЮП-460")
    await _create_six_positions_and_tasks(session, product, sections, route)

    # -----------------------------------------------------------------------
    # 1. Склад сырья: 6 задач, route_history пустой у всех
    # -----------------------------------------------------------------------
    raw_section = sections[0]
    raw_board = await get_section_board(session, section_id=raw_section.id)
    raw_tasks = raw_board["tasks"]

    assert len(raw_tasks) == 6, f"Expected 6 raw tasks, got {len(raw_tasks)}"

    total_raw_plan = sum(Decimal(t["planned_quantity"]) for t in raw_tasks)
    assert total_raw_plan == Decimal("1000"), f"Total raw plan should be 1000, got {total_raw_plan}"

    for task in raw_tasks:
        assert task["route_history"] == [], (
            f"First stage route_history should be empty, got {task['route_history']}"
        )

    # -----------------------------------------------------------------------
    # 2. route_history_after для первого этапа — только текущая операция
    # -----------------------------------------------------------------------
    for task in raw_tasks:
        after = task["route_history_after"]
        assert len(after) == 1, (
            f"First stage route_history_after should have 1 op (current), got {len(after)}"
        )
        assert after[0]["operation_code"] == "ISSUE_RAW"
        assert after[0]["is_significant"] is True

    # -----------------------------------------------------------------------
    # 3. Пресс: 6 задач, route_history = [Выдача сырья]
    # -----------------------------------------------------------------------
    press_section = sections[1]
    press_board = await get_section_board(session, section_id=press_section.id)
    press_tasks = press_board["tasks"]
    assert len(press_tasks) == 6, f"Expected 6 press tasks, got {len(press_tasks)}"

    for task in press_tasks:
        history = task["route_history"]
        assert len(history) == 1, (
            f"Press route_history should have 1 op (Выдача сырья), got {len(history)}"
        )
        assert history[0]["operation_code"] == "ISSUE_RAW"
        assert history[0]["is_significant"] is True

    # Разные operation_code на прессе
    press_op_codes = set(t["operation_code"] for t in press_tasks)
    assert "PRESS_WINDOW" in press_op_codes, "Expected PRESS_WINDOW in press tasks"
    assert "PRESS_COMB" in press_op_codes, "Expected PRESS_COMB in press tasks"

    # -----------------------------------------------------------------------
    # 3.1. На прессе: ДО выполнения — 1 группа (все с одинаковой историей)
    #      ПОСЛЕ выполнения — 2 группы (разделились по операциям)
    # -----------------------------------------------------------------------
    # Группировка по route_history (ДО) — все одинаковые [ISSUE_RAW]
    press_history_keys = [
        tuple(op["operation_code"] for op in t["route_history"])
        for t in press_tasks
    ]
    unique_before = set(press_history_keys)
    assert len(unique_before) == 1, (
        f"Press: before completion should have 1 history group, got {len(unique_before)}"
    )

    # Группировка по route_history_after (ПОСЛЕ) — 2 группы
    press_after_keys = [
        tuple(op["operation_code"] for op in t["route_history_after"])
        for t in press_tasks
    ]
    unique_after = set(press_after_keys)
    assert len(unique_after) == 2, (
        f"Press: after completion should have 2 history groups (PRESS_WINDOW/PRESS_COMB), "
        f"got {len(unique_after)}: {unique_after}"
    )

    # План по прессу: 3 позиции с PRESS_WINDOW, 3 с PRESS_COMB
    window_tasks = [t for t in press_tasks if t["operation_code"] == "PRESS_WINDOW"]
    comb_tasks = [t for t in press_tasks if t["operation_code"] == "PRESS_COMB"]
    assert len(window_tasks) == 3, f"Expected 3 PRESS_WINDOW tasks, got {len(window_tasks)}"
    assert len(comb_tasks) == 3, f"Expected 3 PRESS_COMB tasks, got {len(comb_tasks)}"

    plan_window = sum(Decimal(t["planned_quantity"]) for t in window_tasks)
    plan_comb = sum(Decimal(t["planned_quantity"]) for t in comb_tasks)
    assert plan_window == Decimal("530"), f"PRESS_WINDOW plan should be 530, got {plan_window}"  # 200+150+180
    assert plan_comb == Decimal("470"), f"PRESS_COMB plan should be 470, got {plan_comb}"  # 170+160+140

    # -----------------------------------------------------------------------
    # 4. Анодирование: 6 задач, route_history = [Выдача сырья]
    # (Пресс не is_significant, поэтому только Выдача сырья)
    # -----------------------------------------------------------------------
    anod_section = sections[2]
    anod_board = await get_section_board(session, section_id=anod_section.id)
    anod_tasks = anod_board["tasks"]
    assert len(anod_tasks) == 6

    for task in anod_tasks:
        history = task["route_history"]
        assert len(history) == 1
        assert history[0]["operation_code"] == "ISSUE_RAW"

    # -----------------------------------------------------------------------
    # 5. Склад ГП: 6 задач, route_history = [Выдача сырья, Анодирование]
    # -----------------------------------------------------------------------
    fg_section = sections[4]
    fg_board = await get_section_board(session, section_id=fg_section.id)
    fg_tasks = fg_board["tasks"]
    assert len(fg_tasks) == 6, f"Expected 6 FG tasks, got {len(fg_tasks)}"

    for task in fg_tasks:
        history = task["route_history"]
        assert len(history) == 2, (
            f"FG route_history should have 2 ops, got {len(history)}: {history}"
        )
        assert history[0]["operation_code"] == "ISSUE_RAW"
        assert history[1]["operation_code"] == "ANODIZE"

    # -----------------------------------------------------------------------
    # 6. route_history_after для последнего этапа = route_history + текущая
    # -----------------------------------------------------------------------
    for task in fg_tasks:
        after = task["route_history_after"]
        assert len(after) == 3, (
            f"FG route_history_after should have 3 ops, got {len(after)}"
        )
        assert after[0]["operation_code"] == "ISSUE_RAW"
        assert after[1]["operation_code"] == "ANODIZE"
        assert after[2]["operation_code"] == "FG_WH"

    # -----------------------------------------------------------------------
    # 7. Суммарный план на всех этапах = 1000
    # -----------------------------------------------------------------------
    for stage_name, tasks in [("raw", raw_tasks), ("press", press_tasks), ("anod", anod_tasks), ("fg", fg_tasks)]:
        total = sum(Decimal(t["planned_quantity"]) for t in tasks)
        assert total == Decimal("1000"), f"Total {stage_name} plan should be 1000, got {total}"


@pytest.mark.asyncio
async def test_first_stage_groups_by_sku_only(client, session) -> None:
    """На первом этапе все 6 задач имеют одинаковый grouping key.

    Для профиля ["productSku", "routeHistory", "operationCode"]:
    - productSku одинаковый
    - route_history пустой у всех → operationCode НЕ разделяет
    → все 6 задач → одна группа
    """
    product, sections, route = await _make_transformation_route(session, "ЮП-460-GROUP")
    await _create_six_positions_and_tasks(session, product, sections, route)

    raw_board = await get_section_board(session, section_id=sections[0].id)

    # Все задачи имеют одинаковый SKU
    skus = set(t["product_sku"] for t in raw_board["tasks"])
    assert len(skus) == 1, f"Expected 1 unique SKU on first stage, got {skus}"

    # Все задачи имеют пустой route_history
    route_histories = [tuple(op["operation_code"] for op in t["route_history"]) for t in raw_board["tasks"]]
    unique_histories = set(route_histories)
    assert len(unique_histories) == 1, (
        f"Expected 1 unique route_history on first stage, got {unique_histories}"
    )
    assert list(unique_histories)[0] == (), "First stage route_history should be empty tuple"

    # На прессе route_history уже не пустой → operationCode разделяет
    press_board = await get_section_board(session, section_id=sections[1].id)
    press_histories = [tuple(op["operation_code"] for op in t["route_history"]) for t in press_board["tasks"]]
    # Все имеют одинаковую историю [ISSUE_RAW], но разные operation_code
    press_op_codes = set(t["operation_code"] for t in press_board["tasks"])
    assert len(press_op_codes) == 2, f"Expected 2 different operation_codes on press, got {press_op_codes}"
