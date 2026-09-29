"""Каскадное удаление маршрута и критерий «маршрут-сирота» (#228).

Контракты, которые здесь защищаются:
* ``DELETE /routes/{id}`` без ``force`` на связанном маршруте → 409 со
  списком того, что уйдёт, включая задания (регрессия #228) — и НИЧЕГО
  в БД не меняется;
* ``?force=true`` сносит весь граф, включая операции этапов и условия
  правил привязки — «висячих» операций не остаётся;
* уборка сирот не трогает маршрут с позицией плана;
* уборка по умолчанию — dry run, удаляет только при ``execute=True``.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_plan import InternalPlan, SectionPlanLine
from app.models.production_plan import PlanPosition
from app.models.route import (
    ProductionRoute,
    RouteMatchingRule,
    RouteOperation,
    RouteRuleCondition,
    RouteStage,
)
from app.models.work_task import WorkTask
from app.services.route_deletion import cleanup_orphan_routes, find_orphan_routes
from tests.stock.test_shopfloor_stage3 import _setup_minimal_route

pytestmark = pytest.mark.asyncio


# ─── helpers ────────────────────────────────────────────────────────────────


async def _route_id(session: AsyncSession, name: str) -> int:
    route_id = await session.scalar(select(ProductionRoute.id).where(ProductionRoute.name == name))
    assert route_id is not None, f"Маршрут {name!r} не создан фикстурой"
    return int(route_id)


async def _add_matching_rule(session: AsyncSession, route_id: int) -> tuple[int, int]:
    """Правило привязки с одним условием — каскад обязан снести оба."""
    rule = RouteMatchingRule(route_id=route_id, priority=10)
    session.add(rule)
    await session.flush()
    condition = RouteRuleCondition(
        rule_id=rule.id, field="product_type", operator="eq", value="panel"
    )
    session.add(condition)
    await session.flush()
    return rule.id, condition.id


async def _make_orphan_route(
    session: AsyncSession, *, name: str, code: str, section_id: int
) -> int:
    """Маршрут без позиций плана, строк плана участков и заданий."""
    route = ProductionRoute(name=name, code=code, is_active=True)
    session.add(route)
    await session.flush()
    stage = RouteStage(route_id=route.id, sequence=1, section_id=section_id, is_final=True)
    session.add(stage)
    await session.flush()
    session.add(
        RouteOperation(
            route_stage_id=stage.id, sequence=1, operation_code="OP1", operation_name="Op1"
        )
    )
    await session.commit()
    return route.id


async def _count(session: AsyncSession, stmt) -> int:
    return int(await session.scalar(stmt) or 0)


# ─── tests ──────────────────────────────────────────────────────────────────


async def test_delete_linked_route_without_force_returns_409(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Связанный маршрут без force → 409, перечисляющий ВСЕ связи, включая задания."""
    fx = await _setup_minimal_route(session, sku="RD-409", qty=Decimal("10"))
    route_id = await _route_id(session, "R-RD-409")
    task_id = fx["task"].id

    resp = await client.delete(f"/api/routes/{route_id}")

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail.startswith("Будут удалены:"), detail
    assert "шаг(ов) маршрута" in detail, detail
    # Точные количества, а не только подстрока: регрессия #228 была в том,
    # что задания вообще не попадали в связи маршрута (0 → часть исчезает).
    assert "1 шаг(ов) маршрута" in detail, detail
    assert "1 линия(ий) плана участков" in detail, detail
    assert "1 задание(ий)" in detail, f"Зания не попали в предупреждение (#228): {detail}"
    assert "1 позиция(ий) плана" in detail, detail

    # 409 — отказ, а не «удалили и предупредили»: весь граф на месте.
    assert await _count(session, select(func.count()).select_from(ProductionRoute).where(ProductionRoute.id == route_id)) == 1
    assert await _count(session, select(func.count()).select_from(RouteStage).where(RouteStage.route_id == route_id)) == 1
    assert await _count(
        session,
        select(func.count())
        .select_from(RouteOperation)
        .join(RouteStage, RouteOperation.route_stage_id == RouteStage.id)
        .where(RouteStage.route_id == route_id),
    ) == 1
    assert await _count(session, select(func.count()).select_from(SectionPlanLine).where(SectionPlanLine.route_id == route_id)) == 1
    assert await _count(session, select(func.count()).select_from(WorkTask).where(WorkTask.id == task_id)) == 1
    assert await _count(session, select(func.count()).select_from(PlanPosition).where(PlanPosition.route_id == route_id)) == 1


async def test_delete_linked_route_with_force_removes_whole_graph(
    client: AsyncClient, session: AsyncSession
) -> None:
    """force=true сносит весь граф: операции этапов и условия правил в том числе."""
    fx = await _setup_minimal_route(session, sku="RD-FORCE", qty=Decimal("10"))
    route_id = await _route_id(session, "R-RD-FORCE")
    rule_id, condition_id = await _add_matching_rule(session, route_id)
    await session.commit()

    assert (
        await _count(session, select(func.count()).select_from(RouteRuleCondition).where(RouteRuleCondition.id == condition_id))
        == 1
    ), "Предусловие: условие правила создано"

    resp = await client.delete(f"/api/routes/{route_id}?force=true")

    assert resp.status_code == 204, resp.text

    assert await _count(session, select(func.count()).select_from(ProductionRoute).where(ProductionRoute.id == route_id)) == 0
    assert await _count(session, select(func.count()).select_from(RouteStage).where(RouteStage.route_id == route_id)) == 0
    # Главное: операции сносились вместе с этапами, а не остались сиротами.
    assert await _count(session, select(func.count()).select_from(RouteOperation)) == 0
    assert await _count(
        session,
        select(func.count())
        .select_from(RouteOperation)
        .join(RouteStage, RouteOperation.route_stage_id == RouteStage.id),
    ) == 0, "Остались операции без этапа"
    assert await _count(session, select(func.count()).select_from(RouteMatchingRule).where(RouteMatchingRule.id == rule_id)) == 0
    assert await _count(session, select(func.count()).select_from(RouteRuleCondition).where(RouteRuleCondition.id == condition_id)) == 0
    assert await _count(session, select(func.count()).select_from(SectionPlanLine).where(SectionPlanLine.route_id == route_id)) == 0
    assert await _count(session, select(func.count()).select_from(WorkTask).where(WorkTask.id == fx["task"].id)) == 0
    assert await _count(session, select(func.count()).select_from(PlanPosition).where(PlanPosition.route_id == route_id)) == 0
    # Внутренний план остался пустой оболочкой — его тоже убирают.
    assert await _count(session, select(func.count()).select_from(InternalPlan)) == 0


async def test_orphan_routes_exclude_routes_with_positions(
    session: AsyncSession,
) -> None:
    """Сирота — маршрут без позиций плана/строк/заданий; маршрут с позицией плана — не сирота."""
    fx = await _setup_minimal_route(session, sku="RD-ORPH", qty=Decimal("10"))
    linked_id = await _route_id(session, "R-RD-ORPH")
    orphan_id = await _make_orphan_route(
        session, name="RD-orphan-1", code="RD-ORPHAN-1", section_id=fx["prod"].id
    )

    orphans = await find_orphan_routes(session)
    orphan_ids = [o.id for o in orphans]

    assert orphan_id in orphan_ids
    assert linked_id not in orphan_ids, "Маршрут с позицией плана не должен считаться сиротой"
    stages = {o.id: o.stages for o in orphans}
    assert stages[orphan_id] == 1


async def test_cleanup_orphan_routes_is_dry_run_by_default_and_executes_on_flag(
    session: AsyncSession,
) -> None:
    """Без execute уборка только читает; с execute сносит сирот вместе с этапами."""
    fx = await _setup_minimal_route(session, sku="RD-DRY", qty=Decimal("10"))
    linked_id = await _route_id(session, "R-RD-DRY")
    dry1 = await _make_orphan_route(
        session, name="RD-dry-1", code="RD-DRY-1", section_id=fx["prod"].id
    )
    dry2 = await _make_orphan_route(
        session, name="RD-dry-2", code="RD-DRY-2", section_id=fx["prod"].id
    )

    report = await cleanup_orphan_routes(session)

    assert report.executed is False
    assert report.deleted_ids == []
    assert {dry1, dry2} <= {o.id for o in report.found}
    assert await _count(session, select(func.count()).select_from(ProductionRoute).where(ProductionRoute.id.in_([dry1, dry2]))) == 2

    report = await cleanup_orphan_routes(session, execute=True)

    assert report.executed is True
    assert set(report.deleted_ids) >= {dry1, dry2}
    assert await _count(session, select(func.count()).select_from(ProductionRoute).where(ProductionRoute.id.in_([dry1, dry2]))) == 0
    assert await _count(
        session,
        select(func.count())
        .select_from(RouteStage)
        .where(RouteStage.route_id.in_([dry1, dry2])),
    ) == 0
    assert await _count(
        session,
        select(func.count())
        .select_from(RouteOperation)
        .join(RouteStage, RouteOperation.route_stage_id == RouteStage.id)
        .where(RouteStage.route_id.in_([dry1, dry2])),
    ) == 0
    # Уборка не должна задеть маршрут с позицией плана.
    assert await _count(session, select(func.count()).select_from(ProductionRoute).where(ProductionRoute.id == linked_id)) == 1
    assert await _count(session, select(func.count()).select_from(PlanPosition).where(PlanPosition.route_id == linked_id)) == 1
