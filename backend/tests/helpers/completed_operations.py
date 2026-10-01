"""Фабрика маршрута с реальными ``section_operations`` (ADR-0043, #207).

Признак «пройденные операции» выводится из справочника ``section_operations``
по СЕКЦИИ этапа (``completed_operations_through_stage``). Общие фабрики
``tests/helpers/transfers.py`` заводят только операции уровня этапа
(``RouteOperation``) — для регрессий #207 этого мало, поэтому здесь
строится маршрут, у которого есть и этапы, и операции их секций.

Модуль новый и ничего не меняет в общих фабриках, на которые опираются
тесты других доменов.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from app.models.internal_plan import InternalPlan, InternalPlanStatus, SectionPlanLine
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import (
    ProductionRoute,
    RouteOperation,
    RouteStage,
    SectionOperation,
)
from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.user import User
from app.models.work_task import WorkTask, WorkTaskStatus
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_integrity_invariants import _make_user

__all__ = [
    "build_operation_route",
    "build_plan",
    "build_product",
    "build_stock_to_shop_route",
    "ops_through",
]


def ops_through(stages: Sequence[tuple[str, str, Sequence[str]]], through: int) -> list[str]:
    """Ожидаемый признак материала, вышедшего с этапа ``through`` (1-based).

    Чистая функция от ОБЪЯВЛЕННОГО описания маршрута: ожидаемое
    значение теста задаётся данными фикстуры, а не вычисляется тем же
    кодом, что и проверяемая реализация.
    """
    codes: set[str] = set()
    for _name, _type, ops in stages[:through]:
        codes.update(ops)
    return sorted(codes)


async def build_operation_route(
    session: AsyncSession,
    *,
    sku: str,
    stages: Sequence[tuple[str, str, Sequence[str]]],
    transform_at: int | None = None,
    input_quantity: Decimal | None = None,
    input_dimensions: dict | None = None,
    outputs: list[dict] | None = None,
    qty: Decimal = Decimal(100),
    with_plan_lines: bool = True,
    position_input_quantity: Decimal | None = None,
    position_outputs: list[dict] | None = None,
) -> dict:
    """Маршрут + позиция плана + строки плана + задание на КАЖДЫЙ этап.

    ``stages`` — список ``(имя секции, Section.type, коды операций)`` в
    порядке маршрута. Для каждого этапа заводятся ``Section``,
    ``SectionOperation`` (по одному на код), ``RouteStage`` и
    ``RouteOperation``, а также ``SectionPlanLine`` и ``WorkTask``.

    Возвращает словарь с ``user``/``product``/``route``/``sections``/
    ``route_stages``/``plan_lines``/``tasks``.

    ``transform_at`` (1-based) — этап-позиция маркируется
    ``transforms_dimensions=True``, а её задание получает
    ``input_quantity``/``input_dimensions``/``outputs`` (ADR-0002).

    ``with_plan_lines=False`` — только каталог/маршрут/позиция плана, без
    ``SectionPlanLine``/``WorkTask``: для путей, которые сами создают
    задания при выпуске (``plan_generation.release_batch``).
    """
    user: User = await _make_user(session, f"{sku}@local")

    sections: list[Section] = []
    for index, (name, sec_type, ops) in enumerate(stages, start=1):
        section = Section(
            code=f"{sku}-{index:02d}",
            name=name,
            type=sec_type,
            is_active=True,
            sort_order=index,
        )
        session.add(section)
        await session.flush()
        for order, code in enumerate(ops, start=1):
            session.add(
                SectionOperation(
                    section_id=section.id,
                    operation_code=code,
                    operation_name=code,
                    is_significant=True,
                    sort_order=order,
                )
            )
        sections.append(section)
    await session.flush()

    spg = StorageProductionGroup(code=f"{sku}-SPG", name="SPG", is_active=True, sort_order=0)
    session.add(spg)
    await session.flush()
    for order, section in enumerate(sections, start=1):
        session.add(SpgSection(spg_id=spg.id, section_id=section.id, sort_order=order))
    await session.flush()

    product = Product(
        sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True
    )
    session.add(product)
    await session.flush()

    route = ProductionRoute(name=f"R-{sku}", is_active=True)
    session.add(route)
    await session.flush()

    route_stages: list[RouteStage] = []
    for index, (section, (_name, _type, ops)) in enumerate(
        zip(sections, stages), start=1
    ):
        stage = RouteStage(
            route_id=route.id,
            sequence=index,
            section_id=section.id,
            is_final=(index == len(stages)),
            transforms_dimensions=(index == transform_at),
        )
        session.add(stage)
        await session.flush()
        for order, code in enumerate(ops, start=1):
            # Код операции ЭТАПА намеренно отличается от кода операции
            # СЕКЦИИ: признак «пройденные операции» выводится из
            # справочника section_operations, и тесты должны отличать
            # одно от другого, а не сойтись на общих кодах.
            stage_code = f"{code}@STAGE"
            session.add(
                RouteOperation(
                    route_stage_id=stage.id,
                    sequence=order,
                    operation_code=stage_code,
                    operation_name=stage_code,
                )
            )
        route_stages.append(stage)
    await session.flush()

    plan = ProductionPlan(
        plan_no=f"P-{sku}",
        name="p",
        status=ProductionPlanStatus.approved,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
    )
    session.add(plan)
    await session.flush()

    position = PlanPosition(
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
        route_id=route.id,
        route_assigned_at=None,
        input_quantity=position_input_quantity,
        input_dimensions=input_dimensions,
        outputs=[dict(entry) for entry in (position_outputs or [])],
    )
    session.add(position)
    await session.flush()

    plan_lines: list[SectionPlanLine] = []
    tasks: list[WorkTask] = []
    if with_plan_lines:
        internal_plan = InternalPlan(
            production_plan_id=plan.id, status=InternalPlanStatus.active
        )
        session.add(internal_plan)
        await session.flush()

        for index, (section, stage) in enumerate(zip(sections, route_stages), start=1):
            line = SectionPlanLine(
                internal_plan_id=internal_plan.id,
                plan_position_id=position.id,
                section_id=section.id,
                product_id=product.id,
                route_id=route.id,
                route_stage_id=stage.id,
                sequence=index,
                planned_quantity=qty,
            )
            session.add(line)
            await session.flush()
            plan_lines.append(line)

            task = WorkTask(
                section_plan_line_id=line.id,
                section_id=section.id,
                product_id=product.id,
                route_stage_id=stage.id,
                planned_quantity=qty,
                status=WorkTaskStatus.in_progress,
                due_date=plan.period_end,
                input_quantity=input_quantity if index == transform_at else None,
                input_dimensions=input_dimensions if index == transform_at else None,
                outputs=[dict(entry) for entry in (outputs or [])],
            )
            session.add(task)
            await session.flush()
            tasks.append(task)

    await session.commit()
    return {
        "user": user,
        "product": product,
        "route": route,
        "plan": plan,
        "position": position,
        "sections": sections,
        "route_stages": route_stages,
        "plan_lines": plan_lines,
        "tasks": tasks,
    }


async def build_product(session: AsyncSession, *, sku: str) -> Product:
    """Артикул-компонент с физическим складским остатком (тикет #207)."""
    product = Product(sku=sku, name=f"Raw {sku}", type=ProductType.component, unit="pcs")
    session.add(product)
    await session.commit()
    return product


async def build_stock_to_shop_route(
    session: AsyncSession, *, prefix: str
) -> tuple[Section, Section, ProductionRoute, list[RouteStage]]:
    """Маршрут склад → участок: две секции, два этапа, операция на каждом.

    Возвращает ``(склад, участок, маршрут, этапы)``. Склад — ``raw_stock``,
    то есть источник свободного остатка индикатора (#207); второй этап
    финальный. Правку этой фикстуры положено делать один раз: ею пользуются
    и тесты индикатора остатка, и тесты пропуска этапа.
    """
    stock = Section(
        code=f"{prefix}-STK", name=f"{prefix}-STK", type="raw_stock", is_active=True, sort_order=0
    )
    prod = Section(
        code=f"{prefix}-PROD", name=f"{prefix}-PROD", type="production", is_active=True, sort_order=1
    )
    session.add_all([stock, prod])
    await session.flush()

    route = ProductionRoute(name=f"Route {prefix}", is_active=True)
    session.add(route)
    await session.flush()

    stages: list[RouteStage] = []
    for index, (section, code) in enumerate([(stock, "ISSUE"), (prod, "DRILL")], start=1):
        stage = RouteStage(
            route_id=route.id, sequence=index, section_id=section.id, is_final=index == 2
        )
        session.add(stage)
        await session.flush()
        session.add(
            RouteOperation(
                route_stage_id=stage.id, sequence=1, operation_code=code, operation_name=code
            )
        )
        stages.append(stage)
    await session.commit()
    return stock, prod, route, stages


async def build_plan(session: AsyncSession, *, prefix: str) -> ProductionPlan:
    """План производства месяца — контейнер позиций для тестов #207."""
    plan = ProductionPlan(
        plan_no=f"PLAN-{prefix}",
        name=f"Plan {prefix}",
        status=ProductionPlanStatus.approved,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
    )
    session.add(plan)
    await session.commit()
    return plan
