"""Фабрика «план + позиции» для тестов плана.

Сетап из четырёх таблиц (продукт, секции, маршрут с этапами, план с позициями)
нужен каждому тесту, который проверяет доступ к плановым ручкам. Определения
перенесены из `tests.test_bulk_planning` (там они остаются локальными, пока
модуль не переведён на общий хелпер) — как это сделано в
`tests/helpers/transfers.py`.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.product import Product, ProductType
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section


async def _make_route(session: AsyncSession, sku: str) -> tuple[Product, ProductionRoute]:
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

    for idx, (section, op_code) in enumerate(
        zip(sections, ["ISSUE_RAW", "ACCEPT_FINISHED"], strict=True), start=1
    ):
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
) -> tuple[ProductionPlan, list[PlanPosition], ProductionRoute]:
    """План с `n_positions` позициями в статусе `status`, у каждой — маршрут."""
    product, route = await _make_route(session, sku)
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
    for _ in range(n_positions):
        pos = PlanPosition(
            production_plan_id=plan.id,
            product_id=product.id,
            source_type=PlanSourceType.manual,
            source_sku=product.sku,
            source_name=product.name,
            quantity=Decimal("10"),
            source_payload={},
            status=status,
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
