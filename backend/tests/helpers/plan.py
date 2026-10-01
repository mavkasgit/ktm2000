"""Фабрика «план + позиции» для тестов плана.

Сетап из четырёх таблиц (продукт, секции, маршрут с этапами, план с позициями)
нужен каждому тесту, который проверяет доступ к плановым ручкам. Определения
живут здесь, а `tests.test_bulk_planning` реэкспортирует их под прежними
именами — та же схема, что в `tests/helpers/transfers.py`: одно определение,
старые пути импорта продолжают работать.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section
from sqlalchemy.ext.asyncio import AsyncSession


async def make_route(session: AsyncSession, sku: str) -> tuple[Product, ProductionRoute]:
    """Продукт + маршрут из двух секций (сырьё → готовая продукция)."""
    product = Product(
        sku=sku,
        name=f"Finished {sku}",
        type=ProductType.finished_good,
        unit="pcs",
    )
    sections = [
        Section(code=f"{sku}-ISSUE", name="Issue", type="raw_stock"),
        Section(code=f"{sku}-FINAL", name="Final", type="finished_stock"),
    ]
    session.add_all([product, *sections])
    await session.flush()

    route = ProductionRoute(name=f"Route {sku}", is_active=True)
    session.add(route)
    await session.flush()

    step_ops = ["ISSUE_RAW", "ACCEPT_FINISHED"]
    for idx, (section, op_code) in enumerate(zip(sections, step_ops, strict=True), start=1):
        stage = RouteStage(
            route_id=route.id,
            sequence=idx,
            section_id=section.id,
            is_final=idx == len(sections),
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
    await session.flush()
    return product, route


async def make_plan_with_positions(
    session: AsyncSession,
    sku: str,
    n_positions: int,
    *,
    status: PlanPositionStatus = PlanPositionStatus.draft,
    cancelled_count: int = 0,
) -> tuple[ProductionPlan, list[PlanPosition], ProductionRoute]:
    """План с `n_positions` позициями статуса `status`; первые `cancelled_count` — отменённые.

    У каждой позиции есть маршрут: без него её не утвердить.
    """
    product, route = await make_route(session, sku)
    plan = ProductionPlan(
        plan_no=f"PLAN-{sku}",
        name=f"Plan {sku}",
        status=ProductionPlanStatus.draft,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()

    positions: list[PlanPosition] = []
    for i in range(n_positions):
        target_status = PlanPositionStatus.cancelled if i < cancelled_count else status
        pos = PlanPosition(
            production_plan_id=plan.id,
            product_id=product.id,
            source_type=PlanSourceType.manual,
            source_sku=product.sku,
            source_name=product.name,
            quantity=Decimal(10),
            source_payload={},
            status=target_status,
            validation_status=PlanPositionValidationStatus.valid,
            validation_errors=[],
            period_start=plan.period_start,
            period_end=plan.period_end,
            has_pack_ops=False,
        )
        pos.route_id = route.id
        session.add(pos)
        positions.append(pos)
    await session.commit()
    return plan, positions, route
